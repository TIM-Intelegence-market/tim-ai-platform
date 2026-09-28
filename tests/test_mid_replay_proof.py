"""Isolated MID reconstruction proof (design-validation file).

Proves the canonical replay path (CandleAggregator + guarded candle writer)
on the isolated test database. The raw slice is staged separately (session
step, read-only prod SELECT); these tests only ever touch tim_test through
the guarded Database class.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.data_ingestion.aggregator import CandleAggregator
from src.database.connection import Database
from src.models.market_data import Trade


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="isolated test PostgreSQL URL not provided"
)
SYMBOL = "BTCUSDT"
TIMEFRAMES = ("1m", "5m", "15m", "1h")
SLICE_START = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
SLICE_END = datetime(2026, 9, 10, 13, 10, tzinfo=timezone.utc)
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


def expected_total(trades) -> int:
    return sum(expected_completed(trades, tf) for tf in TIMEFRAMES)


def expected_completed(trades, timeframe: str) -> int:
    """Buckets [s,e) complete iff a later-bucket trade was fed: s+tf <= last minute start."""
    from src.data_ingestion.aggregator import bucket_start as _bs

    last_min = _bs(max(t.event_time for t in trades), "1m")
    secs = TF_SECONDS[timeframe]
    n = 0
    s = _bs(SLICE_START, timeframe)
    while s + timedelta(seconds=secs) <= last_min:
        n += 1
        s += timedelta(seconds=secs)
    return n


class HistoricalConflict(Exception):
    pass


def candle_key(candle) -> tuple:
    return (candle.symbol, candle.timeframe, candle.open_time.isoformat())


def candle_row(candle) -> tuple:
    return (
        candle.symbol, candle.timeframe, candle.open_time, candle.close_time,
        candle.open, candle.high, candle.low, candle.close,
        candle.volume, candle.trade_count, candle.closed,
    )


async def copy_raw_slice(prod_db: Database, test_db: Database) -> int:
    raise AssertionError("raw staging happens outside tests; see mission notes")


async def load_trades(test_db: Database):
    async with test_db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT symbol,price,quantity,trade_time,aggregate_trade_id,buyer_is_maker "
            "FROM agg_trades WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3 "
            "ORDER BY aggregate_trade_id",
            SYMBOL, SLICE_START, SLICE_END,
        )
    return [
        Trade(r["symbol"], r["price"], r["quantity"], r["trade_time"], r["aggregate_trade_id"], r["buyer_is_maker"])
        for r in rows
    ]


async def guarded_write(test_db: Database, candle) -> str:
    """Compare-before-write: missing->INSERT, identical->NOOP, different->abort."""
    async with test_db.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT open,high,low,close,volume,trade_count,closed FROM candles "
            "WHERE symbol=$1 AND timeframe=$2 AND open_time=$3",
            candle.symbol, candle.timeframe, candle.open_time,
        )
        if row is None:
            await conn.execute(
                "INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed) "
                "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
                *candle_row(candle),
            )
            return "INSERT"
        same = (
            row["open"] == candle.open and row["high"] == candle.high and row["low"] == candle.low
            and row["close"] == candle.close and row["volume"] == candle.volume
            and row["trade_count"] == candle.trade_count and row["closed"] == candle.closed
        )
        if same:
            return "NOOP"
        raise HistoricalConflict("existing candle differs for %s %s %s" % (
            candle.symbol, candle.timeframe, candle.open_time.isoformat()))


@pytest_asyncio.fixture
async def dbs():
    assert DATABASE_URL is not None
    test = Database(DATABASE_URL, min_size=1, max_size=2)
    await test.connect()
    await test.initialize_schema()
    async with test.acquire() as conn:
        staged = await conn.fetchval(
            "SELECT COUNT(*) FROM agg_trades WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3",
            SYMBOL, SLICE_START, SLICE_END,
        )
    if staged == 0:
        pytest.skip("raw slice not staged (session staging step required)")
    yield test
    async with test.acquire() as conn:
        # Candles are test output: always cleaned. The staged raw slice is
        # session input and persists across tests (staging is idempotent).
        await conn.execute("DELETE FROM candles WHERE symbol='BTCUSDT'")
    await test.close()


@pytest.mark.asyncio
async def test_copy_slice_is_contiguous(dbs) -> None:
    test = dbs
    async with test.acquire() as conn:
        check = await conn.fetchrow(
            "SELECT COUNT(*) n, MIN(aggregate_trade_id) mn, MAX(aggregate_trade_id) mx "
            "FROM agg_trades WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3",
            SYMBOL, SLICE_START, SLICE_END,
        )
    assert check["n"] > 10000, "slice must be realistic, got %d" % check["n"]
    assert check["n"] == check["mx"] - check["mn"] + 1


@pytest.mark.asyncio
async def test_replay_levels_reconcile(dbs) -> None:
    test = dbs
    trades = await load_trades(test)
    aggregator = CandleAggregator(TIMEFRAMES)
    by_tf: dict[str, list] = {}
    for trade in trades:
        for candle in aggregator.add_trade(trade):
            by_tf.setdefault(candle.timeframe, []).append(candle)
            await guarded_write(test, candle)
    assert len(by_tf["1m"]) == expected_completed(trades, "1m")
    assert len(by_tf["5m"]) == expected_completed(trades, "5m")
    assert len(by_tf["15m"]) == expected_completed(trades, "15m")
    assert len(by_tf["1h"]) == expected_completed(trades, "1h") == 1
    hour = by_tf["1h"][0]
    assert (hour.open_time, hour.close_time) == (
        datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 10, 13, 0, tzinfo=timezone.utc),
    )
    minutes = sorted(by_tf["1m"], key=lambda c: c.open_time)
    hour_minutes = [c for c in minutes if hour.open_time <= c.open_time < hour.close_time]
    # Hierarchical float summation order differs between levels (inherent IEEE754
    # effect, ~4e-13 relative here). Use the engine's own reconciliation tolerance
    # (expansion.volume_profile): max(1e-9, volume*1e-9). Counts are exact integers.
    tolerance = max(1e-9, hour.volume * 1e-9)
    assert abs(sum(c.volume for c in hour_minutes) - hour.volume) <= tolerance
    assert sum(c.trade_count for c in hour_minutes) == hour.trade_count
    assert hour_minutes[0].open == hour.open and hour_minutes[-1].close == hour.close
    assert hour.high == max(c.high for c in minutes) and hour.low == min(c.low for c in minutes)
    assert all(c.closed for c in minutes) and hour.closed
    for candle in minutes:
        assert (candle.close_time - candle.open_time).total_seconds() == 60


async def run_replay(test_db: Database, trades) -> dict:
    counts = {"INSERT": 0, "NOOP": 0}
    aggregator = CandleAggregator(TIMEFRAMES)
    for trade in trades:
        for candle in aggregator.add_trade(trade):
            counts[await guarded_write(test_db, candle)] += 1
    return counts


def candles_hash(test_db_rows) -> str:
    blob = json.dumps(test_db_rows, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


@pytest.mark.asyncio
async def test_idempotent_noop_and_conflict_abort(dbs) -> None:
    test = dbs
    trades = await load_trades(test)
    first = await run_replay(test, trades)
    total = expected_total(trades)
    assert first["INSERT"] == total and first["NOOP"] == 0
    second = await run_replay(test, trades)
    assert second["INSERT"] == 0 and second["NOOP"] == total
    async with test.acquire() as conn:
        await conn.execute(
            "UPDATE candles SET close = close + 1.0 WHERE symbol=$1 AND timeframe='1m' "
            "AND open_time = (SELECT MIN(open_time) FROM candles WHERE symbol=$1 AND timeframe='1m')",
            SYMBOL,
        )
    with pytest.raises(HistoricalConflict):
        await run_replay(test, trades)


@pytest.mark.asyncio
async def test_resume_after_interruption(dbs) -> None:
    test = dbs
    trades = await load_trades(test)
    third = len(trades) * 2 // 3
    part1 = await run_replay(test, trades[:third])
    assert part1["INSERT"] > 0
    # "interrupt": drop in-memory aggregator state, resume from raw
    part2 = await run_replay(test, trades)
    assert part2["NOOP"] >= part1["INSERT"]
    async with test.acquire() as conn:
        n = await conn.fetchval("SELECT COUNT(*) FROM candles WHERE symbol=$1", SYMBOL)
    assert n == expected_total(trades)
    third_run = await run_replay(test, trades)
    assert third_run["INSERT"] == 0


@pytest.mark.asyncio
async def test_determinism_across_runs(dbs) -> None:
    test = dbs
    trades = await load_trades(test)

    async def snapshot():
        async with test.acquire() as conn:
            rows = await conn.fetch(
                "SELECT symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed "
                "FROM candles WHERE symbol=$1 ORDER BY timeframe,open_time", SYMBOL,
            )
        return candles_hash([dict(r) for r in rows])

    await run_replay(test, trades)
    hash_a = await snapshot()
    async with test.acquire() as conn:
        await conn.execute("DELETE FROM candles WHERE symbol=$1", SYMBOL)
    await run_replay(test, trades)
    hash_b = await snapshot()
    assert hash_a == hash_b


@pytest.mark.asyncio
async def test_lookahead_safety(dbs) -> None:
    test = dbs
    trades = await load_trades(test)
    aggregator = CandleAggregator(TIMEFRAMES)
    fed_max = None
    for trade in trades:
        fed_max = trade.event_time
        for candle in aggregator.add_trade(trade):
            assert candle.close_time <= fed_max, "candle emitted beyond fed data"
            await guarded_write(test, candle)
    async with test.acquire() as conn:
        bad = await conn.fetchval(
            "SELECT COUNT(*) FROM candles WHERE symbol=$1 AND close_time > $2", SYMBOL, fed_max,
        )
    assert bad == 0
    # the 1h bucket completes only once its 60th minute arrived
    async with test.acquire() as conn:
        h = await conn.fetchrow(
            "SELECT open_time,close_time FROM candles WHERE symbol=$1 AND timeframe='1h'", SYMBOL,
        )
    assert (h["close_time"] - h["open_time"]).total_seconds() == 3600


@pytest.mark.asyncio
async def test_volume_profile_runs_on_reconstructed_minutes(dbs) -> None:
    from src.research_intelligence.expansion import volume_profile

    test = dbs
    trades = await load_trades(test)
    await run_replay(test, trades)
    async with test.acquire() as conn:
        minute_rows = await conn.fetch(
            "SELECT open_time AS start, close_time AS end, open, high, low, close, volume "
            "FROM candles WHERE symbol=$1 AND timeframe='1m' ORDER BY open_time", SYMBOL,
        )
    minutes = [
        {"seconds": 60, "complete": True, "start": r["start"].isoformat(), "end": r["end"].isoformat(),
         "available_at": r["end"].isoformat(), "provenance": "VERIFIED",
         "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
        for r in minute_rows
    ]
    at = datetime(2026, 9, 10, 13, 9, tzinfo=timezone.utc).isoformat()
    trade_dicts = [
        {"symbol": t.symbol, "price": t.price, "quantity": t.quantity,
         "event_time": t.event_time.isoformat(), "available_at": t.event_time.isoformat(),
         "trade_id": t.trade_id, "source": "test-replay", "provenance": "VERIFIED"}
        for t in trades
    ]
    result = volume_profile(trade_dicts, minutes, at, 3600)
    assert result["coverage_complete"] is True


@pytest.mark.asyncio
async def test_performance_baseline(dbs, capsys) -> None:
    test = dbs
    trades = await load_trades(test)
    t0 = time.monotonic()
    counts = await run_replay(test, trades)
    dt = time.monotonic() - t0
    async with test.acquire() as conn:
        written = await conn.fetchval("SELECT COUNT(*) FROM candles WHERE symbol=$1", SYMBOL)
    print("PERF trades=%d candles=%d seconds=%.2f trades_per_sec=%.0f candles_per_sec=%.0f" % (
        len(trades), written, dt, len(trades) / dt, written / dt))
    assert written == expected_total(trades)
    assert counts["INSERT"] == expected_total(trades)
