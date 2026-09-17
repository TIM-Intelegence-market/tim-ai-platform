"""Isolated tests for scripts/mid_history_reconstruction.py.

All database access targets the isolated test database through the guarded
Database class. Production is never touched by these tests.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from scripts.mid_history_reconstruction import (
    HistoricalConflict,
    classify,
    main_async,
    parse_ts,
    replay_candles,
)
from src.data_ingestion.aggregator import CandleAggregator
from src.database.connection import Database
from src.models.market_data import Trade


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated test PostgreSQL URL not provided")
SYMBOL = "BTCUSDT"
RANGE_FROM = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
RANGE_TO = datetime(2026, 9, 10, 13, 5, tzinfo=timezone.utc)


class Args:
    def __init__(self, **kwargs):
        self.symbol = kwargs.get("symbol", SYMBOL)
        self.from_time = kwargs.get("from_time", RANGE_FROM.isoformat())
        self.to_time = kwargs.get("to_time", RANGE_TO.isoformat())
        self.database_url = kwargs.get("database_url", DATABASE_URL)
        self.execute = kwargs.get("execute", False)
        self.canary = kwargs.get("canary", False)


@pytest_asyncio.fixture
async def database():
    assert DATABASE_URL is not None
    value = Database(DATABASE_URL, min_size=1, max_size=2)
    await value.connect()
    await value.initialize_schema()
    async with value.acquire() as conn:
        staged = await conn.fetchval(
            "SELECT COUNT(*) FROM agg_trades WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3",
            SYMBOL, RANGE_FROM, RANGE_TO,
        )
    if staged == 0:
        pytest.skip("raw slice not staged")
    yield value
    async with value.acquire() as conn:
        await conn.execute("DELETE FROM candles WHERE symbol=$1", SYMBOL)
    await value.close()


def test_parse_ts_rejects_naive_and_bad_input() -> None:
    assert parse_ts("2026-09-10T12:00:00+00:00").tzinfo is not None
    with pytest.raises(Exception):
        parse_ts("2026-09-10 12:00:00")
    with pytest.raises(Exception):
        parse_ts("not-a-date")


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(database, capsys) -> None:
    async with database.acquire() as conn:
        before = await conn.fetchval("SELECT COUNT(*) FROM candles WHERE symbol=$1", SYMBOL)
    code = await main_async(Args())
    assert code == 0
    async with database.acquire() as conn:
        after = await conn.fetchval("SELECT COUNT(*) FROM candles WHERE symbol=$1", SYMBOL)
    assert before == after == 0
    out = capsys.readouterr().out
    assert "MANIFEST" in out and "DRY_RUN_OK" in out


@pytest.mark.asyncio
async def test_rejects_bad_symbol_range_and_future(database) -> None:
    assert await main_async(Args(symbol="NOPE")) == 2
    assert await main_async(Args(from_time=RANGE_TO.isoformat(), to_time=RANGE_FROM.isoformat())) == 2
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert await main_async(Args(to_time=future)) == 2


@pytest.mark.asyncio
async def test_custom_range_execute_refused_without_test_mode(database, monkeypatch) -> None:
    monkeypatch.delenv("TIM_RECONSTRUCTION_TEST_MODE", raising=False)
    assert await main_async(Args(execute=True)) == 2


@pytest.mark.asyncio
async def test_execute_idempotent_and_conflict_aborts(database, monkeypatch) -> None:
    monkeypatch.setenv("TIM_RECONSTRUCTION_TEST_MODE", "1")
    first = await main_async(Args(execute=True))
    assert first == 0
    async with database.acquire() as conn:
        written = await conn.fetchval("SELECT COUNT(*) FROM candles WHERE symbol=$1", SYMBOL)
    # 64x1m + 12x5m + 4x15m + 1x1h per the tail rule (buckets close only on
    # later-bucket evidence; verified against MANIFEST counts, not assumed).
    assert written == 64 + 12 + 4 + 1
    # Second run: all identical -> zero writes.
    second = await main_async(Args(execute=True))
    assert second == 0
    # Tamper one candle -> conflict aborts with zero new writes.
    async with database.acquire() as conn:
        await conn.execute(
            "UPDATE candles SET close = close + 1.0 WHERE symbol=$1 AND timeframe='1m' "
            "AND open_time = (SELECT MIN(open_time) FROM candles WHERE symbol=$1 AND timeframe='1m')",
            SYMBOL,
        )
    assert await main_async(Args(execute=True)) == 3
    async with database.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM candles WHERE symbol=$1", SYMBOL) == written
