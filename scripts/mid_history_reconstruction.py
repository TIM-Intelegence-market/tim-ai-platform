"""Dedicated MID historical reconstruction executor (bounded, guarded).

Reads raw agg_trades, replays the canonical CandleAggregator, and writes
only missing candles through a compare-before-write guard:

  absent    -> INSERT
  identical -> NOOP (OHLC exact, volume per engine tolerance)
  different -> HISTORICAL_CONFLICT, abort fail-closed (no silent overwrite)

Safety:
  - default is dry-run (read-only); writes need --execute
  - --execute is allowed ONLY for the fixed canary range, except when
    TIM_RECONSTRUCTION_TEST_MODE=1 AND the target database name matches
    a test pattern (isolated tests only)
  - explicit --database-url is required (no default, no fallback)
  - rejects: invalid/unordered range, future timestamps, unknown symbol,
    unknown timeframe, conflicting candles, unexpected write counts
  - one transaction for the bounded write set (all-or-nothing)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_ingestion.aggregator import CandleAggregator
from src.database.connection import Database
from src.models.market_data import Trade

SYMBOL_ALLOWLIST = ("BTCUSDT",)
TIMEFRAMES = ("1m", "5m", "15m", "1h")
CANARY_FROM = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
CANARY_TO = datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc)
CANARY_EXPECTED = {"1m": 60, "5m": 12, "15m": 4, "1h": 1}


class ReconstructionError(Exception):
    pass


class HistoricalConflict(ReconstructionError):
    pass


def parse_ts(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ReconstructionError("invalid timestamp: %r" % value) from error
    if parsed.tzinfo is None:
        raise ReconstructionError("timestamp must be timezone-aware: %r" % value)
    return parsed.astimezone(timezone.utc)


def candle_key(symbol: str, timeframe: str, open_time: datetime) -> tuple:
    return (symbol, timeframe, open_time.isoformat())


def volume_matches(existing: float, computed: float) -> bool:
    tolerance = max(1e-9, abs(computed) * 1e-9)
    return abs(existing - computed) <= tolerance


def candles_identical(row, candle) -> bool:
    return (
        row["open"] == candle.open
        and row["high"] == candle.high
        and row["low"] == candle.low
        and row["close"] == candle.close
        and volume_matches(row["volume"], candle.volume)
        and row["trade_count"] == candle.trade_count
        and row["close_time"] == candle.close_time
        and row["closed"] == candle.closed
    )


def candle_fingerprint(candle) -> str:
    return hashlib.sha256(
        ("%s|%s|%s|%r|%r|%r|%r|%r|%d|%s" % (
            candle.symbol, candle.timeframe, candle.open_time.isoformat(),
            candle.open, candle.high, candle.low, candle.close,
            candle.volume, candle.trade_count, candle.closed,
        )).encode(),
    ).hexdigest()


async def load_trades(conn, symbol: str, start: datetime, end: datetime):
    rows = await conn.fetch(
        "SELECT symbol,price,quantity,trade_time,aggregate_trade_id,buyer_is_maker "
        "FROM agg_trades WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3 "
        "ORDER BY aggregate_trade_id",
        symbol, start, end,
    )
    trades = [
        Trade(r["symbol"], r["price"], r["quantity"], r["trade_time"],
              r["aggregate_trade_id"], r["buyer_is_maker"])
        for r in rows
    ]
    # Bucket-closure evidence: in-range tail buckets ([.., end)) complete only
    # on later evidence. Read the single first trade at/after `end` (read-only)
    # so tails close exactly as the live engine would have closed them. That
    # trade opens out-of-range buckets that can never complete here and are
    # never persisted. Bounded: abort if the next evidence is over 1h away.
    if trades:
        tail = await conn.fetch(
            "SELECT symbol,price,quantity,trade_time,aggregate_trade_id,buyer_is_maker "
            "FROM agg_trades WHERE symbol=$1 AND trade_time >= $2 "
            "ORDER BY aggregate_trade_id LIMIT 1",
            symbol, end,
        )
        if not tail:
            raise ReconstructionError("no closing evidence at/after range end")
        if (tail[0]["trade_time"] - end).total_seconds() > 3600:
            raise ReconstructionError("closing evidence too far past range end")
        first = tail[0]
        trades.append(Trade(
            first["symbol"], first["price"], first["quantity"], first["trade_time"],
            first["aggregate_trade_id"], first["buyer_is_maker"],
        ))
    return trades


def replay_candles(trades) -> dict[str, list]:
    aggregator = CandleAggregator(TIMEFRAMES)
    by_tf: dict[str, list] = {}
    for trade in trades:
        for candle in aggregator.add_trade(trade):
            by_tf.setdefault(candle.timeframe, []).append(candle)
    return by_tf


async def classify(conn, by_tf: dict, end: datetime) -> dict:
    """Read-only verdict per candle: INSERT / NOOP / CONFLICT. No writes.

    Only buckets fully inside [start, end) are eligible. Buckets opened by
    the closing-evidence trade (open_time >= end) can never complete in this
    run and are excluded from verdicts and counts.
    """
    verdicts: list[dict] = []
    for timeframe, candles in by_tf.items():
        if timeframe not in TIMEFRAMES:
            raise ReconstructionError("unexpected timeframe: %r" % timeframe)
        for candle in candles:
            if candle.open_time >= end:
                continue
            row = await conn.fetchrow(
                "SELECT open,high,low,close,volume,trade_count,close_time,closed FROM candles "
                "WHERE symbol=$1 AND timeframe=$2 AND open_time=$3",
                candle.symbol, candle.timeframe, candle.open_time,
            )
            if row is None:
                verdicts.append({"action": "INSERT", "candle": candle})
            elif candles_identical(row, candle):
                verdicts.append({"action": "NOOP", "candle": candle})
            else:
                verdicts.append({"action": "CONFLICT", "candle": candle})
    return {"verdicts": verdicts}


async def main_async(args) -> int:
    symbol = args.symbol
    if symbol not in SYMBOL_ALLOWLIST:
        print("REJECTED: unexpected symbol %r" % symbol, flush=True)
        return 2
    start = parse_ts(args.from_time)
    end = parse_ts(args.to_time)
    now = datetime.now(timezone.utc)
    if start >= end:
        print("REJECTED: invalid range", flush=True)
        return 2
    if end > now:
        print("REJECTED: future timestamps", flush=True)
        return 2
    is_canary = (symbol == "BTCUSDT" and start == CANARY_FROM and end == CANARY_TO)
    writing = bool(args.execute)
    if writing and not is_canary:
        test_mode = os.environ.get("TIM_RECONSTRUCTION_TEST_MODE") == "1"
        db_name = (args.database_url.rsplit("/", 1)[-1].split("?")[0]).lower()
        if not (test_mode and "test" in db_name):
            print("REJECTED: writes only for the fixed canary range "
                  "(custom ranges need TIM_RECONSTRUCTION_TEST_MODE=1 on a test database)", flush=True)
            return 2

    database = Database(args.database_url, min_size=1, max_size=2)
    await database.connect()
    try:
        async with database.acquire() as conn:
            trades = await load_trades(conn, symbol, start, end)
        if not trades:
            print("REJECTED: empty raw input", flush=True)
            return 2
        raw_hash = hashlib.sha256(
            ("%d|%d|%d" % (len(trades), trades[0].trade_id, trades[-1].trade_id)).encode()
        ).hexdigest()
        by_tf = replay_candles(trades)
        counts = {tf: len(by_tf.get(tf, [])) for tf in TIMEFRAMES}
        manifest = {
            "reconstruction_id": "mid-canary-20260915-0900" if is_canary else "mid-custom",
            "symbol": symbol,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "raw_trades": len(trades),
            "raw_hash": raw_hash,
            "counts": counts,
            "expected_writes": sum(counts.values()),
            "dry_run": not writing,
        }
        if is_canary:
            for tf, expected in CANARY_EXPECTED.items():
                if counts.get(tf, 0) != expected:
                    print("REJECTED: unexpected canary count %s=%d expected=%d" % (
                        tf, counts.get(tf, 0), expected), flush=True)
                    return 2
        print("MANIFEST " + json.dumps(manifest, sort_keys=True), flush=True)

        async with database.acquire() as conn:
            plan = await classify(conn, by_tf, end)
        inserts = [v for v in plan["verdicts"] if v["action"] == "INSERT"]
        noops = [v for v in plan["verdicts"] if v["action"] == "NOOP"]
        conflicts = [v for v in plan["verdicts"] if v["action"] == "CONFLICT"]
        print("PLAN inserts=%d noops=%d conflicts=%d" % (len(inserts), len(noops), len(conflicts)), flush=True)
        if conflicts:
            first = conflicts[0]["candle"]
            print("HISTORICAL_CONFLICT %s %s %s: aborting, zero writes" % (
                first.symbol, first.timeframe, first.open_time.isoformat()), flush=True)
            return 3
        if not writing:
            print("DRY_RUN_OK zero writes performed", flush=True)
            return 0
        if len(inserts) + len(noops) != manifest["expected_writes"]:
            print("REJECTED: verdicts do not account all computed candles", flush=True)
            return 2
        async with database.acquire() as conn:
            async with conn.transaction():
                for verdict in inserts:
                    c = verdict["candle"]
                    await conn.execute(
                        "INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,"
                        "volume,trade_count,closed) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                        c.symbol, c.timeframe, c.open_time, c.close_time, c.open, c.high,
                        c.low, c.close, c.volume, c.trade_count, c.closed,
                    )
        print("WROTE inserts=%d noops=%d" % (len(inserts), len(noops)), flush=True)
        return 0
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded MID history reconstruction (dry-run by default)")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--from", dest="from_time", default="2026-09-15T09:00:00+00:00")
    parser.add_argument("--to", dest="to_time", default="2026-09-15T10:00:00+00:00")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--execute", action="store_true", help="perform writes (canary range only)")
    parser.add_argument("--canary", action="store_true", help="use the fixed authorized canary range")
    args = parser.parse_args()
    if args.canary:
        args.from_time = CANARY_FROM.isoformat()
        args.to_time = CANARY_TO.isoformat()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
