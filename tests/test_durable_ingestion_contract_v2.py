from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.data_ingestion.durable import (
    DurableOutboxWorker,
    OutboxItem,
    cursor_hash,
    outbox_identity,
)
from src.models.market_data import Trade


NOW = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


def test_cursor_and_worker_identities_are_deterministic_and_domain_separated() -> None:
    first = cursor_hash(
        symbol="BTCUSDT",
        last_aggregate_trade_id=42,
        last_event_time=NOW,
        last_trade_time=NOW,
        last_persisted_at=NOW,
        recovery_state="NORMAL",
    )
    assert first == cursor_hash(
        symbol="BTCUSDT",
        last_aggregate_trade_id=42,
        last_event_time=NOW,
        last_trade_time=NOW,
        last_persisted_at=NOW,
        recovery_state="NORMAL",
    )
    assert first != cursor_hash(
        symbol="BTCUSDT",
        last_aggregate_trade_id=42,
        last_event_time=NOW,
        last_trade_time=NOW,
        last_persisted_at=NOW,
        recovery_state="GAP_DETECTED",
    )
    candle_id, event_key = outbox_identity("BTCUSDT", 42, "CANDLE_V1")
    research_id, same_event_key = outbox_identity("BTCUSDT", 42, "RESEARCH_V1")
    assert event_key == same_event_key
    assert candle_id != research_id
    assert all(len(value) == 64 for value in (first, candle_id, event_key))


def test_schema_contract_is_transactional_bounded_retryable_and_quarantinable() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (root / "src/database/migrations/004_durable_ingestion.sql").read_text()
    assert migration.startswith("BEGIN;") and migration.rstrip().endswith("COMMIT;")
    for table in ("ingestion_cursors", "ingestion_outbox", "ingestion_gap_incidents", "ingestion_metrics"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
    assert "UNIQUE (worker_name, idempotency_key)" in migration
    assert "'QUARANTINED'" in migration
    assert "max_attempts" in migration
    assert "lease_expires_at" in migration
    assert "cursor_hash" in migration


class WorkerStore:
    def __init__(self, *, max_attempts: int = 2) -> None:
        self.item = OutboxItem(
            outbox_id="a" * 64,
            worker_name="CANDLE_V1",
            idempotency_key="b" * 64,
            symbol="BTCUSDT",
            aggregate_trade_id=7,
            status="PROCESSING",
            attempts=1,
            max_attempts=max_attempts,
            input_hash="c" * 64,
            worker_version="1.0.0",
            created_at=NOW,
            started_at=NOW,
        )
        self.claimed = False
        self.acknowledged: list[str] = []
        self.failures = 0
        self.metrics = []

    async def claim(self, *_args, **_kwargs):
        if self.claimed:
            return []
        self.claimed = True
        return [self.item]

    async def load_trade(self, *_args):
        return Trade("BTCUSDT", 100.0, 1.0, NOW, 7, False)

    async def acknowledge(self, _outbox_id, output_hash):
        self.acknowledged.append(output_hash)
        return True

    async def fail(self, _outbox_id, _error):
        self.failures += 1
        return "QUARANTINED" if self.item.attempts >= self.item.max_attempts else "RETRY"

    async def record_metric(self, *args, **kwargs):
        self.metrics.append((args, kwargs))


@pytest.mark.asyncio
async def test_worker_acknowledges_with_output_hash_and_exposes_idempotency_key() -> None:
    store = WorkerStore()
    seen = []

    async def handler(item, trade):
        seen.append((item.idempotency_key, trade.trade_id))
        return {"candle": "persisted", "idempotency_key": item.idempotency_key}

    result = await DurableOutboxWorker(store, "CANDLE_V1", handler).run_once()
    assert result == {"claimed": 1, "completed": 1, "retried": 0, "quarantined": 0}
    assert seen == [("b" * 64, 7)]
    assert len(store.acknowledged) == 1
    assert store.acknowledged[0] == hashlib.sha256(
        ('{"result":{"candle":"persisted","idempotency_key":"' + "b" * 64 + '"},"worker":"CANDLE_V1"}').encode()
    ).hexdigest()


@pytest.mark.asyncio
async def test_worker_crash_is_retryable_then_quarantined_at_attempt_limit() -> None:
    async def crash(_item, _trade):
        raise RuntimeError("TEST_ONLY worker crash")

    retry_store = WorkerStore(max_attempts=2)
    retry = await DurableOutboxWorker(retry_store, "CANDLE_V1", crash).run_once()
    assert retry["retried"] == 1 and retry_store.failures == 1

    quarantine_store = WorkerStore(max_attempts=1)
    quarantine = await DurableOutboxWorker(quarantine_store, "CANDLE_V1", crash).run_once()
    assert quarantine["quarantined"] == 1 and quarantine_store.failures == 1
