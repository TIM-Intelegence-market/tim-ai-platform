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

from src.data_ingestion.aggregator import CandleAggregator, TIMEFRAME_SECONDS
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


async def execute_range(database, symbol: str, start: datetime, end: datetime,
                      execute: bool, expected_counts: dict | None = None,
                      reconstruction_id: str = "mid-custom") -> dict:
    """Replay one bounded range with guarded writes. Raises ReconstructionError
    on any rejection; returns result dict on success (including dry-run).

    The range start must align to every persisted timeframe boundary.
    Otherwise the first bucket of a timeframe would open mid-bucket on a
    fresh aggregator and persist corrupt partial OHLC. (Chunks step in
    multiples of all timeframes, so aligned starts are always available.)
    Unaligned tail buckets at `end` simply stay open by the tail rule.
    """
    epoch = int(start.timestamp())
    for timeframe in TIMEFRAMES:
        if epoch % TIMEFRAME_SECONDS[timeframe] != 0:
            raise ReconstructionError(
                "range start not aligned to %s boundary" % timeframe)
    async with database.acquire() as conn:
        trades = await load_trades(conn, symbol, start, end)
    if not trades:
        raise ReconstructionError("empty raw input")
    raw_hash = hashlib.sha256(
        ("%d|%d|%d" % (len(trades), trades[0].trade_id, trades[-1].trade_id)).encode()
    ).hexdigest()
    by_tf = replay_candles(trades)
    counts = {tf: len(by_tf.get(tf, [])) for tf in TIMEFRAMES}
    if expected_counts is not None:
        for tf, expected in expected_counts.items():
            if counts.get(tf, 0) != expected:
                raise ReconstructionError(
                    "unexpected count %s=%d expected=%d" % (tf, counts.get(tf, 0), expected))
    async with database.acquire() as conn:
        plan = await classify(conn, by_tf, end)
    inserts = [v for v in plan["verdicts"] if v["action"] == "INSERT"]
    noops = [v for v in plan["verdicts"] if v["action"] == "NOOP"]
    conflicts = [v for v in plan["verdicts"] if v["action"] == "CONFLICT"]
    if conflicts:
        first = conflicts[0]["candle"]
        raise HistoricalConflict("conflict %s %s %s: zero writes" % (
            first.symbol, first.timeframe, first.open_time.isoformat()))
    if len(inserts) + len(noops) != sum(counts.values()):
        raise ReconstructionError("verdicts do not account all computed candles")
    if not execute:
        return {"reconstruction_id": reconstruction_id, "dry_run": True,
                "raw_trades": len(trades), "raw_hash": raw_hash, "counts": counts,
                "inserts": 0, "noops": len(noops)}
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
    return {"reconstruction_id": reconstruction_id, "dry_run": False,
            "raw_trades": len(trades), "raw_hash": raw_hash, "counts": counts,
            "inserts": len(inserts), "noops": len(noops)}


async def main_async(args) -> int:
    if args.manifest:
        return await main_manifest(args)
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
        expected = dict(CANARY_EXPECTED) if is_canary else None
        try:
            result = await execute_range(
                database, symbol, start, end, writing, expected,
                "mid-canary-20260915-0900" if is_canary else "mid-custom")
        except HistoricalConflict as error:
            print("HISTORICAL_CONFLICT %s: aborting, zero writes" % error, flush=True)
            return 3
        except ReconstructionError as error:
            print("REJECTED: %s" % error, flush=True)
            return 2
        print("MANIFEST " + json.dumps({
            "reconstruction_id": result["reconstruction_id"], "symbol": symbol,
            "from": start.isoformat(), "to": end.isoformat(),
            "raw_trades": result["raw_trades"], "raw_hash": result["raw_hash"],
            "counts": result["counts"], "expected_writes": sum(result["counts"].values()),
            "dry_run": not writing}, sort_keys=True), flush=True)
        if not writing:
            print("DRY_RUN_OK zero writes performed", flush=True)
            return 0
        print("WROTE inserts=%d noops=%d" % (result["inserts"], result["noops"]), flush=True)
        return 0
    finally:
        await database.close()


async def main_manifest(args) -> int:
    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    digest = hashlib.sha256(json.dumps(
        {k: v for k, v in manifest.items() if k != "manifest_hash"},
        sort_keys=True).encode()).hexdigest()
    if manifest.get("manifest_hash") != digest:
        print("MANIFEST_HASH_MISMATCH", flush=True)
        return 2
    if args.scope != manifest.get("authorized_scope"):
        print("REJECTED: scope mismatch (pass --scope exactly as authorized)", flush=True)
        return 2
    try:
        scope_from = parse_ts(manifest["scope_from"])
        scope_to = parse_ts(manifest["scope_to"])
    except (KeyError, ReconstructionError) as error:
        print("REJECTED: bad scope window: %s" % error, flush=True)
        return 2
    checkpoint_path = Path(str(manifest_path) + ".checkpoint.json")
    checkpoint: dict = {}
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text())

    database = Database(args.database_url, min_size=1, max_size=2)
    await database.connect()
    try:
        for chunk in manifest["chunks"]:
            cid = chunk["id"]
            state = checkpoint.get(cid, {})
            if state.get("status") == "CHUNK_DONE":
                print("SKIP_DONE chunk=%d" % cid, flush=True)
                continue
            start = parse_ts(chunk["from"])
            end = parse_ts(chunk["to"])
            if not (scope_from <= start and end <= scope_to):
                print("REJECTED: chunk %d outside authorized scope" % cid, flush=True)
                return 2
            t0 = datetime.now(timezone.utc)
            try:
                result = await execute_range(
                    database, manifest["symbol"], start, end, args.execute,
                    chunk.get("expected_counts"), manifest["reconstruction_id"])
            except HistoricalConflict as error:
                print("CHUNK_CONFLICT chunk=%d %s: aborting" % (cid, error), flush=True)
                return 3
            except ReconstructionError as error:
                print("CHUNK_REJECTED chunk=%d %s: aborting" % (cid, error), flush=True)
                return 2
            checkpoint[cid] = {"status": "CHUNK_DONE",
                               "inserts": result["inserts"], "noops": result["noops"],
                               "raw_hash": result["raw_hash"],
                               "ms": int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)}
            checkpoint_path.write_text(json.dumps(checkpoint, indent=1))
            print("CHUNK_DONE id=%d inserts=%d noops=%d ms=%d" % (
                cid, result["inserts"], result["noops"], checkpoint[cid]["ms"]), flush=True)
        print("MANIFEST_DONE chunks=%d" % len(manifest["chunks"]), flush=True)
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
    parser.add_argument("--manifest", default=None, help="hash-verified chunk manifest for bounded runs")
    parser.add_argument("--scope", default=None, help="must match the manifest authorized_scope exactly")
    args = parser.parse_args()
    if args.canary:
        args.from_time = CANARY_FROM.isoformat()
        args.to_time = CANARY_TO.isoformat()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
