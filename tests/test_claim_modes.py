"""Focused tests for DurableIngestionStore.claim() in both ordering modes.

Regression context: the strict_order=False branch once passed four bind
arguments to a three-placeholder statement (leftover $4 guard), so every
non-strict claim raised InterfaceError. These tests prove arity, semantics,
lease safety and lock exclusion for both modes against isolated PostgreSQL.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.data_ingestion.durable import DurableIngestionStore
from src.database.connection import Database


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated durable-ingestion PostgreSQL URL not provided")
BASE = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=2)


def trade(symbol: str, trade_id: int):
    from src.models.market_data import Trade

    return Trade(symbol, 100.0 + trade_id / 10_000, 0.25, BASE + timedelta(seconds=trade_id), trade_id, False)


@pytest_asyncio.fixture
async def database():
    assert DATABASE_URL is not None
    value = Database(DATABASE_URL, min_size=1, max_size=3)
    await value.connect()
    await value.initialize_schema()
    yield value
    async with value.acquire() as connection:
        await connection.execute("DELETE FROM ingestion_outbox WHERE symbol LIKE 'CLAIM%'")
        await connection.execute("DELETE FROM agg_trades WHERE symbol LIKE 'CLAIM%'")
        await connection.execute("DELETE FROM ingestion_cursors WHERE symbol LIKE 'CLAIM%'")
        await connection.execute("DELETE FROM ingestion_gap_incidents WHERE symbol LIKE 'CLAIM%'")
        await connection.execute("DELETE FROM ingestion_metrics")
    await value.close()


async def seed(store: DurableIngestionStore, symbol: str, first: int, count: int) -> None:
    for trade_id in range(first, first + count):
        await store.ingest_trade(trade(symbol, trade_id))


@pytest.mark.asyncio
async def test_both_modes_bind_correctly(database) -> None:
    """Arity regression: both modes must execute (no placeholder mismatch)."""
    store = DurableIngestionStore(database)
    await seed(store, "CLAIMA", 1, 3)
    strict_items = await store.claim("CANDLE_V1", limit=5, strict_order=True)
    assert [item.aggregate_trade_id for item in strict_items] == [1]
    await seed(store, "CLAIMB", 10, 3)
    loose_items = await store.claim("CANDLE_V1", limit=5, strict_order=False)
    assert sorted(item.aggregate_trade_id for item in loose_items) == [2, 3, 10, 11, 12]


@pytest.mark.asyncio
async def test_non_strict_claim_sets_lease_and_attempts(database) -> None:
    store = DurableIngestionStore(database)
    await seed(store, "CLAIMC", 20, 2)
    items = await store.claim("CANDLE_V1", limit=2, strict_order=False, lease_seconds=300)
    assert len(items) == 2
    async with database.acquire() as connection:
        rows = await connection.fetch(
            "SELECT aggregate_trade_id,attempts,lease_expires_at,status FROM ingestion_outbox "
            "WHERE symbol='CLAIMC' ORDER BY aggregate_trade_id"
        )
    assert [row["status"] for row in rows] == ["PROCESSING", "PROCESSING"]
    assert [row["attempts"] for row in rows] == [1, 1]
    assert all(row["lease_expires_at"] is not None for row in rows)


@pytest.mark.asyncio
async def test_non_strict_skips_ineligible_and_never_duplicates(database) -> None:
    store = DurableIngestionStore(database, max_attempts=1)
    await seed(store, "CLAIMD", 30, 3)
    first = await store.claim("CANDLE_V1", limit=1, strict_order=False)
    assert [item.aggregate_trade_id for item in first] == [30]
    # Quarantine trade 30 via fail(); it must never be claimed again.
    assert await store.fail(first[0].outbox_id, RuntimeError("TEST_ONLY")) == "QUARANTINED"
    second = await store.claim("CANDLE_V1", limit=10, strict_order=False)
    assert sorted(item.aggregate_trade_id for item in second) == [31, 32]
    third = await store.claim("CANDLE_V1", limit=10, strict_order=False)
    # 30 QUARANTINED, 31/32 PROCESSING with live leases: nothing claimable.
    assert third == []


@pytest.mark.asyncio
async def test_overlapping_transaction_cannot_steal_locked_rows(database) -> None:
    """SKIP LOCKED: rows locked by another open transaction are skipped."""
    store = DurableIngestionStore(database)
    await seed(store, "CLAIME", 40, 3)
    async with database.acquire() as locker:
        transaction = locker.transaction()
        await transaction.start()
        try:
            locked = await locker.fetch(
                "SELECT outbox_id FROM ingestion_outbox WHERE symbol='CLAIME' FOR UPDATE"
            )
            assert len(locked) == 3
            skipped = await store.claim("CANDLE_V1", limit=10, strict_order=False)
            assert skipped == []
        finally:
            await transaction.rollback()
    recovered = await store.claim("CANDLE_V1", limit=10, strict_order=False)
    assert sorted(item.aggregate_trade_id for item in recovered) == [40, 41, 42]


@pytest.mark.asyncio
async def test_strict_mode_claims_head_only(database) -> None:
    store = DurableIngestionStore(database)
    await seed(store, "CLAIMF", 50, 3)
    items = await store.claim("CANDLE_V1", limit=5, strict_order=True)
    assert [item.aggregate_trade_id for item in items] == [50]
