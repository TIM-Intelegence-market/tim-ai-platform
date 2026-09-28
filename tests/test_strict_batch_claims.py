"""Strict-order batches: a contiguous head prefix, processed strictly in order.

The candle worker must never process an item while an older active item is
unprocessed. Batching may only change how many head items one claim takes,
never which item runs next, what a failure does, or the attempt accounting.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

import src.data_ingestion.durable as durable_module
from src.data_ingestion.durable import DurableIngestionStore, DurableOutboxWorker
from src.database.connection import Database


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated durable-ingestion PostgreSQL URL not provided")
BASE = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=2)
SYMBOL = "BATCHX"


def trade(trade_id: int):
    from src.models.market_data import Trade

    return Trade(SYMBOL, 100.0 + trade_id / 10_000, 0.25, BASE + timedelta(seconds=trade_id), trade_id, False)


async def _clean(connection) -> None:
    await connection.execute("DELETE FROM ingestion_outbox WHERE symbol LIKE 'BATCH%'")
    await connection.execute("DELETE FROM agg_trades WHERE symbol LIKE 'BATCH%'")
    await connection.execute("DELETE FROM ingestion_cursors WHERE symbol LIKE 'BATCH%'")
    await connection.execute("DELETE FROM ingestion_gap_incidents WHERE symbol LIKE 'BATCH%'")
    await connection.execute("DELETE FROM ingestion_metrics")


@pytest_asyncio.fixture
async def database():
    assert DATABASE_URL is not None
    value = Database(DATABASE_URL, min_size=1, max_size=4)
    await value.connect()
    await value.initialize_schema()
    async with value.acquire() as connection:
        await _clean(connection)
    yield value
    async with value.acquire() as connection:
        await _clean(connection)
    await value.close()


async def seeded(database, count: int = 5) -> DurableIngestionStore:
    store = DurableIngestionStore(database)
    for trade_id in range(1, count + 1):
        await store.ingest_trade(trade(trade_id))
    return store


async def states(database) -> dict[int, tuple[str, int]]:
    async with database.acquire() as connection:
        rows = await connection.fetch(
            "SELECT aggregate_trade_id,status,attempts FROM ingestion_outbox WHERE symbol=$1", SYMBOL
        )
    return {row["aggregate_trade_id"]: (row["status"], row["attempts"]) for row in rows}


async def execute(database, sql: str, *args) -> None:
    async with database.acquire() as connection:
        await connection.execute(sql, *args)


def recording_worker(store, seen: list[int], *, fail_on: int | None = None, batch_size: int = 100, **kwargs):
    async def handler(item, loaded):
        assert loaded.trade_id == item.aggregate_trade_id
        seen.append(item.aggregate_trade_id)
        if item.aggregate_trade_id == fail_on:
            raise RuntimeError("handler failure")
        return {"trade": item.aggregate_trade_id}

    return DurableOutboxWorker(
        store, "CANDLE_V1", handler, batch_size=batch_size, lease_seconds=kwargs.pop("lease_seconds", 300),
        strict_order=True, **kwargs,
    )


@pytest.mark.asyncio
async def test_prefix_claims_contiguous_head_in_order(database) -> None:
    store = await seeded(database)
    items = await store.claim_strict_prefix("CANDLE_V1", limit=3, lease_seconds=300)
    assert [item.aggregate_trade_id for item in items] == [1, 2, 3]
    assert await states(database) == {
        1: ("PROCESSING", 1), 2: ("PROCESSING", 0), 3: ("PROCESSING", 0), 4: ("PENDING", 0), 5: ("PENDING", 0),
    }, "only the head is charged at claim time; later items are charged when they run"
    # The next claim cannot overtake the leased head.
    assert await store.claim_strict_prefix("CANDLE_V1", limit=3) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("UPDATE ingestion_outbox SET status='RETRY',available_at=clock_timestamp()+interval '1 hour' "
         "WHERE symbol=$1 AND aggregate_trade_id=3", [1, 2]),
        ("UPDATE ingestion_outbox SET status='QUARANTINED',attempts=max_attempts "
         "WHERE symbol=$1 AND aggregate_trade_id=2", [1]),
        ("UPDATE ingestion_outbox SET status='PROCESSING',lease_expires_at=clock_timestamp()+interval '1 hour' "
         "WHERE symbol=$1 AND aggregate_trade_id=4", [1, 2, 3]),
        ("UPDATE ingestion_outbox SET status='QUARANTINED',attempts=max_attempts "
         "WHERE symbol=$1 AND aggregate_trade_id=1", []),
    ],
    ids=["not-yet-available", "quarantined", "leased", "blocked-head"],
)
async def test_prefix_stops_at_first_unclaimable_item(database, sql, expected) -> None:
    store = await seeded(database)
    await execute(database, sql, SYMBOL)
    items = await store.claim_strict_prefix("CANDLE_V1", limit=5, lease_seconds=300)
    assert [item.aggregate_trade_id for item in items] == expected
    preset_lease = {4} if "status='PROCESSING'" in sql else set()
    processing = {trade_id for trade_id, (status, _) in (await states(database)).items() if status == "PROCESSING"}
    assert processing == set(expected) | preset_lease, "nothing behind the stop is claimed"


@pytest.mark.asyncio
async def test_prefix_stops_at_row_locked_by_another_transaction(database) -> None:
    store = await seeded(database)
    async with database.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT 1 FROM ingestion_outbox WHERE symbol=$1 AND aggregate_trade_id=2 FOR UPDATE", SYMBOL
            )
            items = await store.claim_strict_prefix("CANDLE_V1", limit=5)
    assert [item.aggregate_trade_id for item in items] == [1]


@pytest.mark.asyncio
async def test_prefix_reclaims_expired_lease_in_order(database) -> None:
    store = await seeded(database)
    await execute(
        database,
        "UPDATE ingestion_outbox SET status='PROCESSING',attempts=1,lease_expires_at=clock_timestamp()-interval '1 second' "
        "WHERE symbol=$1 AND aggregate_trade_id=1",
        SYMBOL,
    )
    items = await store.claim_strict_prefix("CANDLE_V1", limit=5)
    assert [item.aggregate_trade_id for item in items] == [1, 2, 3, 4, 5]
    assert items[0].attempts == 2


@pytest.mark.asyncio
async def test_worker_batch_processes_all_in_order(database) -> None:
    store = await seeded(database)
    seen: list[int] = []
    result = await recording_worker(store, seen).run_once()
    assert seen == [1, 2, 3, 4, 5]
    assert result["claimed"] == 5 and result["completed"] == 5 and result["returned"] == 0
    assert set((await states(database)).values()) == {("COMPLETED", 1)}


@pytest.mark.asyncio
async def test_failure_mid_batch_returns_rest_untouched_and_keeps_order(database) -> None:
    store = await seeded(database)
    seen: list[int] = []
    worker = recording_worker(store, seen, fail_on=3)
    result = await worker.run_once()
    assert seen == [1, 2, 3]
    assert result == {"claimed": 5, "completed": 2, "retried": 1, "quarantined": 0, "returned": 2}
    after = await states(database)
    assert after[1] == after[2] == ("COMPLETED", 1)
    assert after[3] == ("RETRY", 1), "the failing item is accounted exactly like the single-item path"
    assert after[4] == after[5] == ("RETRY", 0), "untouched items keep their attempt budget"

    # While the failed head backs off, nothing behind it may run.
    again = await worker.run_once()
    assert again["claimed"] == 0 and seen == [1, 2, 3]

    await execute(database, "UPDATE ingestion_outbox SET available_at=clock_timestamp() WHERE symbol=$1", SYMBOL)
    worker.handler = recording_worker(store, seen).handler
    result = await worker.run_once()
    assert seen == [1, 2, 3, 3, 4, 5]
    assert result["completed"] == 3
    after = await states(database)
    assert after[3] == ("COMPLETED", 2) and after[4] == after[5] == ("COMPLETED", 1)


@pytest.mark.asyncio
async def test_missing_raw_event_fails_only_that_item(database) -> None:
    store = await seeded(database)
    # A foreign key keeps raw rows from vanishing; simulate the defensive case.
    load_trades = store.load_trades

    async def without_two(symbol, ids):
        return {key: value for key, value in (await load_trades(symbol, ids)).items() if key != 2}

    store.load_trades = without_two
    seen: list[int] = []
    result = await recording_worker(store, seen).run_once()
    assert seen == [1]
    assert result["completed"] == 1 and result["retried"] == 1 and result["returned"] == 3
    async with database.acquire() as connection:
        error = await connection.fetchval(
            "SELECT last_error FROM ingestion_outbox WHERE symbol=$1 AND aggregate_trade_id=2", SYMBOL
        )
    assert "missing raw event" in error


@pytest.mark.asyncio
async def test_last_attempt_failure_quarantines_and_blocks(database) -> None:
    store = await seeded(database)
    await execute(
        database, "UPDATE ingestion_outbox SET attempts=max_attempts-1 WHERE symbol=$1 AND aggregate_trade_id=2", SYMBOL
    )
    seen: list[int] = []
    worker = recording_worker(store, seen, fail_on=2)
    result = await worker.run_once()
    assert result["quarantined"] == 1 and result["completed"] == 1
    assert (await states(database))[2][0] == "QUARANTINED"
    blocked = await worker.run_once()
    assert blocked["status"] == "TERMINAL_BLOCKED"
    assert blocked["terminal_blocker"]["trade_id"] == 2
    assert seen == [1, 2]


@pytest.mark.asyncio
async def test_cancellation_returns_current_and_remaining_items(database) -> None:
    store = await seeded(database)
    seen: list[int] = []

    async def handler(item, loaded):
        seen.append(item.aggregate_trade_id)
        if item.aggregate_trade_id == 2:
            raise asyncio.CancelledError
        return {}

    worker = DurableOutboxWorker(store, "CANDLE_V1", handler, batch_size=100, lease_seconds=300, strict_order=True)
    with pytest.raises(asyncio.CancelledError):
        await worker.run_once()
    after = await states(database)
    assert after[1] == ("COMPLETED", 1)
    assert all(after[trade_id] == ("RETRY", 0) for trade_id in (2, 3, 4, 5))


@pytest.mark.asyncio
async def test_remaining_leases_are_renewed_during_long_batch(database, monkeypatch) -> None:
    monkeypatch.setattr(durable_module, "LEASE_RENEWAL_INTERVAL_SECONDS", 0.0)
    store = await seeded(database, count=4)
    seen: list[int] = []

    async def slow(item, loaded):
        seen.append(item.aggregate_trade_id)
        await asyncio.sleep(0.8)
        # Anything whose lease lapsed would be taken away here.
        await store.release_expired_leases("CANDLE_V1")
        return {}

    worker = DurableOutboxWorker(store, "CANDLE_V1", slow, batch_size=100, lease_seconds=2, strict_order=True)
    result = await worker.run_once()
    assert seen == [1, 2, 3, 4]
    assert result["completed"] == 4, "3.2 s of work under a 2 s lease only succeeds with renewal"


@pytest.mark.asyncio
async def test_lost_lease_stops_batch_without_processing_it(database, monkeypatch) -> None:
    monkeypatch.setattr(durable_module, "LEASE_RENEWAL_INTERVAL_SECONDS", 0.0)
    store = await seeded(database)
    seen: list[int] = []

    async def handler(item, loaded):
        seen.append(item.aggregate_trade_id)
        if item.aggregate_trade_id == 2:
            # Simulate an operator/lease-expiry takeover of item 4.
            await execute(
                database,
                "UPDATE ingestion_outbox SET status='RETRY',lease_expires_at=NULL WHERE symbol=$1 AND aggregate_trade_id=4",
                SYMBOL,
            )
        return {}

    worker = DurableOutboxWorker(store, "CANDLE_V1", handler, batch_size=100, lease_seconds=300, strict_order=True)
    result = await worker.run_once()
    assert seen == [1, 2]
    assert result["completed"] == 2 and result["returned"] == 3
    after = await states(database)
    assert after[3] == ("RETRY", 0) and after[5] == ("RETRY", 0)
    assert after[4] == ("RETRY", 0), "the taken-over item is left to its new owner, never charged by this batch"


@pytest.mark.asyncio
async def test_batch_size_one_keeps_single_item_path(database) -> None:
    store = await seeded(database, count=3)
    seen: list[int] = []
    result = await recording_worker(store, seen, batch_size=1).run_once()
    assert seen == [1] and result["claimed"] == 1 and "returned" not in result


def test_batch_size_setting_is_bounded(monkeypatch) -> None:
    from config.settings import Settings

    monkeypatch.delenv("TIM_OUTBOX_BATCH_SIZE", raising=False)
    assert Settings().outbox_batch_size == 100
    monkeypatch.setenv("TIM_OUTBOX_BATCH_SIZE", "1")
    assert Settings().outbox_batch_size == 1
    for bad in ("0", "1001"):
        monkeypatch.setenv("TIM_OUTBOX_BATCH_SIZE", bad)
        with pytest.raises(ValueError, match="TIM_OUTBOX_BATCH_SIZE"):
            Settings()


@pytest.mark.asyncio
async def test_crash_mid_batch_does_not_spend_attempts_of_items_that_never_ran(database) -> None:
    store = await seeded(database)
    for _ in range(6):
        items = await store.claim_strict_prefix("CANDLE_V1", limit=5, lease_seconds=300)
        assert [item.aggregate_trade_id for item in items] == [1, 2, 3, 4, 5]
        # Process killed (SIGKILL/OOM): no defer runs, the leases simply expire.
        await execute(
            database,
            "UPDATE ingestion_outbox SET lease_expires_at=clock_timestamp()-interval '1 second' "
            "WHERE symbol=$1 AND status='PROCESSING'",
            SYMBOL,
        )
        await store.release_expired_leases("CANDLE_V1")
    after = await states(database)
    assert after[1] == ("RETRY", 6), "the head is charged per claim, exactly like the single-item path"
    assert all(after[trade_id] == ("RETRY", 0) for trade_id in (2, 3, 4, 5))


@pytest.mark.asyncio
async def test_locked_head_is_never_skipped_by_either_claim_path(database) -> None:
    store = await seeded(database)
    seen: list[int] = []
    async with database.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                "SELECT 1 FROM ingestion_outbox WHERE symbol=$1 AND aggregate_trade_id=1 FOR UPDATE", SYMBOL
            )
            assert await store.claim("CANDLE_V1", limit=1, strict_order=True) == []
            result = await recording_worker(store, seen).run_once()
            single = await recording_worker(store, seen, batch_size=1).run_once()
    assert seen == [] and result["claimed"] == 0 and single["claimed"] == 0
    assert set((await states(database)).values()) == {("PENDING", 0)}
