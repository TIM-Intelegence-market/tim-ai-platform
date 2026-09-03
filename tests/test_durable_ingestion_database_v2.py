from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from src.data_ingestion.durable import (
    DurableIngestionStore,
    QueueCapacityError,
    cursor_hash,
)
from src.database.connection import Database
from src.models.market_data import Trade


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated durable-ingestion PostgreSQL URL not provided")
BASE = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=2)


def trade(symbol: str, trade_id: int, seconds: int = 0) -> Trade:
    return Trade(symbol, 100.0 + trade_id / 10_000, 0.25, BASE + timedelta(seconds=seconds), trade_id, False)


@pytest_asyncio.fixture
async def database():
    assert DATABASE_URL is not None
    value = Database(DATABASE_URL, min_size=1, max_size=3)
    await value.connect()
    await value.initialize_schema()
    async with value.acquire() as connection:
        await connection.execute("DELETE FROM orderflow_validations")
        await connection.execute("DELETE FROM orderflow_observations")
        await connection.execute("DELETE FROM observations")
        await connection.execute("DELETE FROM research_cases")
        await connection.execute("DELETE FROM candles")
        await connection.execute("DELETE FROM ingestion_outbox")
        await connection.execute("DELETE FROM ingestion_gap_incidents")
        await connection.execute("DELETE FROM ingestion_cursors")
        await connection.execute("DELETE FROM ingestion_metrics")
        await connection.execute("DELETE FROM agg_trades")
    yield value
    async with value.acquire() as connection:
        await connection.execute("DELETE FROM orderflow_validations")
        await connection.execute("DELETE FROM orderflow_observations")
        await connection.execute("DELETE FROM observations")
        await connection.execute("DELETE FROM research_cases")
        await connection.execute("DELETE FROM candles")
        await connection.execute("DELETE FROM ingestion_outbox")
        await connection.execute("DELETE FROM ingestion_gap_incidents")
        await connection.execute("DELETE FROM ingestion_cursors")
        await connection.execute("DELETE FROM ingestion_metrics")
        await connection.execute("DELETE FROM agg_trades")
    await value.close()


@pytest.mark.asyncio
async def test_raw_cursor_and_outbox_commit_together_and_duplicate_is_idempotent(database) -> None:
    store = DurableIngestionStore(database, queue_capacity=10)
    first = await store.ingest_trade(trade("DURABLEA", 100))
    duplicate = await store.ingest_trade(trade("DURABLEA", 100))
    assert first.raw_inserted and first.outbox_inserted
    assert duplicate.duplicate and not duplicate.outbox_inserted
    async with database.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM agg_trades WHERE symbol='DURABLEA'") == 1
        assert await connection.fetchval("SELECT count(*) FROM ingestion_outbox WHERE symbol='DURABLEA'") == 1
        row = await connection.fetchrow("SELECT * FROM ingestion_cursors WHERE symbol='DURABLEA'")
    assert row["last_aggregate_trade_id"] == 100
    assert row["cursor_hash"] == cursor_hash(
        symbol="DURABLEA",
        last_aggregate_trade_id=100,
        last_event_time=row["last_event_time"],
        last_trade_time=row["last_trade_time"],
        last_persisted_at=row["last_persisted_at"],
        recovery_state="NORMAL",
    )


@pytest.mark.asyncio
async def test_failure_after_cursor_write_rolls_back_raw_cursor_and_outbox(database, monkeypatch) -> None:
    store = DurableIngestionStore(database)

    async def crash_after_cursor(_connection, name, _value, _metadata=None):
        if name == "queue_depth":
            raise RuntimeError("TEST_ONLY crash after cursor")

    monkeypatch.setattr(store, "_gauge", crash_after_cursor)
    with pytest.raises(RuntimeError, match="after cursor"):
        await store.ingest_trade(trade("DURABLEB", 200))
    async with database.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM agg_trades WHERE symbol='DURABLEB'") == 0
        assert await connection.fetchval("SELECT count(*) FROM ingestion_outbox WHERE symbol='DURABLEB'") == 0
        assert await connection.fetchval("SELECT count(*) FROM ingestion_cursors WHERE symbol='DURABLEB'") == 0


@pytest.mark.asyncio
async def test_queue_overflow_rejects_without_half_persistence_and_records_gap(database) -> None:
    store = DurableIngestionStore(database, queue_capacity=1)
    await store.ingest_trade(trade("DURABLEC", 300))
    with pytest.raises(QueueCapacityError):
        await store.ingest_trade(trade("DURABLEC", 301, 1))
    async with database.acquire() as connection:
        assert await connection.fetchval("SELECT count(*) FROM agg_trades WHERE symbol='DURABLEC'") == 1
        assert await connection.fetchval("SELECT last_aggregate_trade_id FROM ingestion_cursors WHERE symbol='DURABLEC'") == 300
        gap = await connection.fetchrow(
            "SELECT reason,status FROM ingestion_gap_incidents WHERE symbol='DURABLEC'"
        )
    assert dict(gap) == {"reason": "OUTBOX_CAPACITY", "status": "OPEN"}


@pytest.mark.asyncio
async def test_gap_resolution_requires_every_raw_id_and_outbox_retries_quarantine(database) -> None:
    store = DurableIngestionStore(database, queue_capacity=20, max_attempts=2)
    await store.ingest_trade(trade("DURABLED", 400))
    gap = await store.ingest_trade(trade("DURABLED", 403, 3))
    assert gap.gap_detected
    assert await store.resolve_gaps_through("DURABLED", 402) == 0
    await store.ingest_trade(trade("DURABLED", 401, 1))
    assert await store.resolve_gaps_through("DURABLED", 402) == 0
    await store.ingest_trade(trade("DURABLED", 402, 2))
    assert await store.resolve_gaps_through("DURABLED", 402) == 1

    claimed = await store.claim("CANDLE_V1", limit=1)
    assert len(claimed) == 1
    assert await store.fail(claimed[0].outbox_id, RuntimeError("TEST_ONLY"), retry_delay_seconds=0) == "RETRY"
    second = await store.claim("CANDLE_V1", limit=1)
    assert len(second) == 1
    assert await store.fail(second[0].outbox_id, RuntimeError("TEST_ONLY"), retry_delay_seconds=0) == "QUARANTINED"


@pytest.mark.asyncio
async def test_strict_order_reports_quarantined_head_without_skipping_pending(database) -> None:
    store = DurableIngestionStore(database, queue_capacity=20, max_attempts=1)
    await store.ingest_trade(trade("DURABLEQ", 410))
    await store.ingest_trade(trade("DURABLEQ", 411, 1))
    claimed = await store.claim("CANDLE_V1", limit=1, strict_order=True)
    assert await store.fail(claimed[0].outbox_id, RuntimeError("POISON"), retry_delay_seconds=0) == "QUARANTINED"

    result = await store.claim_detailed("CANDLE_V1", limit=1, strict_order=True)
    assert result.status == "TERMINAL_BLOCKED"
    assert result.terminal_blocker is not None
    assert result.terminal_blocker.aggregate_trade_id == 410
    async with database.acquire() as connection:
        assert await connection.fetchval(
            "SELECT status FROM ingestion_outbox WHERE symbol='DURABLEQ' AND aggregate_trade_id=411"
        ) == "PENDING"


@pytest.mark.asyncio
async def test_restart_replay_excludes_pending_and_includes_acknowledged_work(database) -> None:
    store = DurableIngestionStore(database)
    item = trade("DURABLEE", 500)
    await store.ingest_trade(item)
    assert await store.processed_trades_since("DURABLEE", BASE) == []
    claimed = await store.claim("CANDLE_V1", limit=1)
    assert await store.acknowledge(claimed[0].outbox_id, "f" * 64)
    replay = await store.processed_trades_since("DURABLEE", BASE)
    assert [value.trade_id for value in replay] == [500]


@pytest.mark.asyncio
async def test_real_runtime_reader_commits_before_separate_worker_enriches(database, monkeypatch) -> None:
    assert DATABASE_URL is not None
    monkeypatch.setenv("TIM_DATABASE_SECRET_PROVIDER", "url-env")
    monkeypatch.setenv("TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS", "true")
    monkeypatch.setenv("TIM_RUNTIME_ENV", "test")
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", DATABASE_URL)
    import main

    monkeypatch.setattr(main, "settings", replace(main.settings, dashboard_port=0))
    app = main.TIMApplication()
    await app.database.connect()
    try:
        await app.restore_persisted_state()
        first = Trade("BTCUSDT", 100.0, 1.0, BASE, 1_000, False)
        second = Trade("BTCUSDT", 101.0, 1.0, BASE + timedelta(minutes=1), 1_001, False)
        await app.ingest_trade(first)
        async with app.database.acquire() as connection:
            assert await connection.fetchval(
                "SELECT status FROM ingestion_outbox WHERE symbol='BTCUSDT' AND aggregate_trade_id=1000"
            ) == "PENDING"
            assert await connection.fetchval("SELECT count(*) FROM candles WHERE symbol='BTCUSDT'") == 0
        assert (await app.enrichment_worker.run_once())["completed"] == 1
        await app.ingest_trade(second)
        assert (await app.enrichment_worker.run_once())["completed"] == 1
        async with app.database.acquire() as connection:
            assert await connection.fetchval(
                "SELECT count(*) FROM ingestion_outbox WHERE symbol='BTCUSDT' AND status='COMPLETED'"
            ) == 2
            assert await connection.fetchval(
                "SELECT count(*) FROM candles WHERE symbol='BTCUSDT' AND timeframe='1m'"
            ) == 1
    finally:
        await app.database.close()
        app.dashboard.server.server_close()
