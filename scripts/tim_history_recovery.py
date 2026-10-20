#!/usr/bin/env python3
"""Resume large raw gaps and rebuild independently verified historical candles."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.database.connection import Database
from src.data_ingestion.catchup import PublicBinanceAggTradeClient, PublicRateLimitError, PublicDataError
from src.data_ingestion.durable import DurableIngestionStore
from src.operational.history_recovery import persist_historical_batch, rebuild_verified_minute
from src.operational.horizon_readiness import horizon_bounds


def save(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


async def run(*, max_gaps: int = 10, max_pages: int = 10, max_candles: int = 120,
              scan_ids: int = 100_000, client=None, raw_seconds: float = 40, candle_seconds: float = 40) -> dict:
    path = ROOT / "data/operational/history_recovery.json"
    try:
        previous = json.loads(path.read_text())
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    progress = previous.get("gap_resume_ids", {})
    progress = progress if isinstance(progress, dict) else {}
    dirty = set(previous.get("dirty_minutes", []))
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "status": "PASS", "mode": "OBSERVE",
              "trading_actions": 0, "gaps_resolved": 0, "raw_persisted": 0, "rest_pages": 0,
              "candles_rebuilt": 0, "candles_waiting_for_raw": 0, "candle_proofs": [], "errors": [],
              "last_gap_id": str(previous.get("last_gap_id", "")),
              "last_minute": previous.get("last_minute"), "gap_resume_ids": progress,
              "dirty_minutes": [], "budget": {"max_gaps": max_gaps, "max_pages": max_pages,
                                              "max_candles": max_candles, "scan_ids": scan_ids}}
    database = Database(settings.database_url, min_size=1, max_size=2)
    await database.connect()
    try:
        now = datetime.now(timezone.utc)
        symbol = settings.symbol.upper()
        start, end = horizon_bounds(now, 10080)
        store = DurableIngestionStore(database, historical_queue_capacity=0)
        cursor = await store.get_cursor(symbol)
        if not cursor or cursor.last_aggregate_trade_id is None:
            report["status"] = "PAUSED"
            report["errors"].append("no trusted live cursor")
            return report
        report["live_cursor_before"] = cursor.last_aggregate_trade_id
        source = client or PublicBinanceAggTradeClient(minimum_interval=0.2)
        cooldown = previous.get("retry_after_utc")
        try:
            rest_allowed = cooldown is None or datetime.fromisoformat(cooldown) <= now
        except (TypeError, ValueError):
            rest_allowed = False
        if not rest_allowed:
            report["retry_after_utc"] = cooldown

        async def raw_phase():
            async with database.acquire() as connection:
                query = """SELECT gap_id,missing_from_id,missing_to_id FROM ingestion_gap_incidents
                           WHERE symbol=$1 AND status='OPEN' AND missing_from_id >= 0
                             AND missing_to_id >= missing_from_id AND missing_to_id < $2
                             AND gap_id > $3 ORDER BY gap_id LIMIT $4"""
                candidates = await connection.fetch(query, symbol, cursor.last_aggregate_trade_id, report["last_gap_id"], max_gaps)
                if not candidates and report["last_gap_id"]:
                    candidates = await connection.fetch(query, symbol, cursor.last_aggregate_trade_id, "", max_gaps)
            for gap in candidates:
                gap_id = gap["gap_id"]
                report["last_gap_id"] = gap_id
                try:
                    if await store.resolve_gap(gap_id):
                        report["gaps_resolved"] += 1
                        progress.pop(gap_id, None)
                        continue
                    resume = progress.get(gap_id, gap["missing_from_id"])
                    if type(resume) is not int or not gap["missing_from_id"] <= resume <= gap["missing_to_id"]:
                        resume = gap["missing_from_id"]
                    stop = min(gap["missing_to_id"], resume+scan_ids-1)
                    async with database.acquire() as connection:
                        rows = await connection.fetch(
                            """SELECT aggregate_trade_id FROM agg_trades WHERE symbol=$1
                               AND aggregate_trade_id BETWEEN $2 AND $3 ORDER BY aggregate_trade_id LIMIT $4""",
                            symbol, resume, stop, scan_ids,
                        )
                    expected = resume
                    for row in rows:
                        if row["aggregate_trade_id"] != expected:
                            break
                        expected += 1
                    if expected > stop:
                        progress[gap_id] = expected
                        continue
                    progress[gap_id] = expected
                    if not rest_allowed or report["rest_pages"] >= max_pages:
                        continue
                    report["rest_pages"] += 1
                    batch = await source.fetch(symbol, expected, limit=min(1000, stop-expected+1))
                    if not batch:
                        raise PublicDataError("public source returned no data for historical range")
                    if any(trade.symbol != symbol or trade.trade_id != expected+offset
                           or trade.trade_id > stop or trade.event_time >= end
                           for offset, trade in enumerate(batch)):
                        raise PublicDataError("historical response violates requested IDs, symbol or settled-time boundary")
                    persisted = await persist_historical_batch(store, batch)
                    report["raw_persisted"] += persisted["persisted"]
                    inserted_ids = set(persisted["inserted_ids"])
                    for trade in batch:
                        minute = trade.event_time.astimezone(timezone.utc).replace(second=0, microsecond=0)
                        if trade.trade_id in inserted_ids and start <= minute < end:
                            dirty.add(minute.isoformat())
                    progress[gap_id] = batch[-1].trade_id+1
                except PublicRateLimitError as error:
                    report["retry_after_utc"] = (datetime.now(timezone.utc)+timedelta(seconds=error.retry_after_seconds)).isoformat()
                    report["errors"].append("public rate limit; REST cooldown recorded")
                    break
                except Exception as error:
                    report["errors"].append(f"gap {gap_id}: {type(error).__name__}")

        try:
            async with asyncio.timeout(raw_seconds):
                await raw_phase()
        except TimeoutError:
            report["raw_budget_exhausted"] = True
        except Exception as error:
            report["errors"].append(f"raw repair: {type(error).__name__}")

        async def candle_phase():
            try:
                after = datetime.fromisoformat(str(report["last_minute"]))
                if after.tzinfo is None:
                    after = start-timedelta(minutes=1)
            except (ValueError, TypeError):
                after = start-timedelta(minutes=1)
            async with database.acquire() as connection:
                query = """SELECT minute FROM generate_series($2::timestamptz,$3::timestamptz-interval '1 minute',
                           interval '1 minute') AS minute WHERE minute > $4 AND NOT EXISTS (
                             SELECT 1 FROM candles c WHERE c.symbol=$1 AND c.timeframe='1m' AND c.open_time=minute
                               AND c.closed=true AND c.close_time=minute+interval '1 minute'
                               AND c.low <= LEAST(c.open,c.close) AND c.high >= GREATEST(c.open,c.close)
                               AND c.low <= c.high AND c.volume >= 0 AND c.trade_count > 0)
                           ORDER BY minute LIMIT $5"""
                missing = await connection.fetch(query, symbol, start, end, after, max_candles)
                if not missing:
                    missing = await connection.fetch(query, symbol, start, end, start-timedelta(minutes=1), max_candles)
            dirty_minutes = []
            for value in sorted(dirty):
                try:
                    minute = datetime.fromisoformat(value)
                    if minute.tzinfo is not None and start <= minute < end:
                        dirty_minutes.append(minute)
                    else:
                        dirty.discard(value)
                except (ValueError, TypeError):
                    dirty.discard(value)
            dirty_limit = min(len(dirty_minutes), max(1, max_candles//2))
            candidates = [(minute, True) for minute in dirty_minutes[:dirty_limit]]
            seen = {minute for minute, _ in candidates}
            candidates += [(row["minute"], False) for row in missing if row["minute"] not in seen]
            for minute, is_dirty in candidates[:max_candles]:
                if not is_dirty:
                    report["last_minute"] = minute.isoformat()
                async with database.acquire() as connection:
                    result = await rebuild_verified_minute(connection, symbol, minute, now=now)
                if result["status"] == "REBUILT":
                    report["candles_rebuilt"] += 1
                    report["candle_proofs"].append({"minute": minute.isoformat(), **result})
                    dirty.discard(minute.isoformat())
                else:
                    report["candles_waiting_for_raw"] += 1
        try:
            async with asyncio.timeout(candle_seconds):
                await candle_phase()
        except TimeoutError:
            report["candle_budget_exhausted"] = True
        except Exception as error:
            report["errors"].append(f"candle repair: {type(error).__name__}")
        if report["errors"]:
            report["status"] = "ATTENTION_REQUIRED"
        return report
    finally:
        report["dirty_minutes"] = sorted(dirty)
        save(path, report)
        await database.close()


def main() -> int:
    import fcntl
    lock_path = ROOT / "data/operational/history_recovery.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"status":"ALREADY_RUNNING"}')
            return 0
        report = asyncio.run(run())
        summary = {key: value for key, value in report.items()
                   if key not in {"gap_resume_ids", "dirty_minutes", "candle_proofs"}}
        print(json.dumps(summary, indent=2, default=str))
        return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
