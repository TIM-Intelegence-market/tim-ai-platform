from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from main import TIMApplication
from src.dashboard.app import DashboardState
from src.data_ingestion.durable import OutboxItem
from src.models.market_data import Trade


NOW = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_runtime_ingress_only_persists_and_updates_queue_health() -> None:
    app = TIMApplication.__new__(TIMApplication)
    app.dashboard_state = DashboardState()
    enrichment_called = False

    async def enrich(_trade):
        nonlocal enrichment_called
        enrichment_called = True

    async def ingress(_trade):
        return SimpleNamespace(
            queue_depth=7,
            cursor=SimpleNamespace(last_aggregate_trade_id=42, recovery_state="NORMAL", last_persisted_at=NOW),
        )

    app._enrich_trade = enrich
    app.durable_ingress = ingress
    await app.ingest_trade(Trade("BTCUSDT", 100, 1, NOW, 42, False))
    assert enrichment_called is False
    assert app.dashboard_state.system_health["queue_depth"] == 7
    assert app.dashboard_state.system_health["cursor_trade_id"] == 42
    assert app.dashboard_state.system_health["last_raw_persisted_at"] == NOW.isoformat()


@pytest.mark.asyncio
async def test_outbox_handler_runs_enrichment_with_explicit_idempotency_identity() -> None:
    app = TIMApplication.__new__(TIMApplication)
    seen = []

    async def enrich(trade):
        seen.append(trade.trade_id)
        return [{"timeframe": "1m", "open_time": NOW.isoformat()}]

    app._enrich_trade = enrich
    item = OutboxItem(
        outbox_id="a" * 64,
        worker_name="CANDLE_V1",
        idempotency_key="b" * 64,
        symbol="BTCUSDT",
        aggregate_trade_id=42,
        status="PROCESSING",
        attempts=1,
        max_attempts=5,
        input_hash="c" * 64,
        worker_version="1.0.0",
        created_at=NOW,
        started_at=NOW,
    )
    result = await app.process_persisted_trade(item, Trade("BTCUSDT", 100, 1, NOW, 42, False))
    assert seen == [42]
    assert result["idempotency_key"] == "b" * 64
    assert result["mode"] == "OBSERVE" and result["trading_actions"] == 0
