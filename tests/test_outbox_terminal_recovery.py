from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import main
from src.data_ingestion.aggregator import CandleAggregator
from src.data_ingestion.durable import (
    ClaimResult,
    DurableOutboxWorker,
    OutboxItem,
    TerminalBlocker,
)
from src.models.market_data import Trade


NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def outbox_item(*, status: str = "PROCESSING", last_error: str | None = None) -> OutboxItem:
    return OutboxItem(
        outbox_id="a" * 64,
        worker_name="CANDLE_V1",
        idempotency_key="b" * 64,
        symbol="BTCUSDT",
        aggregate_trade_id=10,
        status=status,
        attempts=5,
        max_attempts=5,
        input_hash="c" * 64,
        worker_version="1.0.0",
        created_at=NOW,
        started_at=NOW,
        last_error=last_error,
    )


class TerminalStore:
    async def claim_detailed(self, *_args, **_kwargs):
        return ClaimResult(
            "TERMINAL_BLOCKED",
            terminal_blocker=TerminalBlocker(
                "a" * 64, "CANDLE_V1", 10, "QUARANTINED", "poison", 5, 5,
                NOW, NOW + timedelta(minutes=1), NOW + timedelta(minutes=1),
            ),
        )


@pytest.mark.asyncio
async def test_strict_order_quarantine_is_explicit_terminal_blocker() -> None:
    worker = DurableOutboxWorker(TerminalStore(), "CANDLE_V1", None, strict_order=True)
    result = await worker.run_once()
    assert result["status"] == "TERMINAL_BLOCKED"
    assert result["claimed"] == 0
    assert result["terminal_blocker"]["trade_id"] == 10
    assert result["terminal_blocker"]["strict_order_position"] == 1


class IdleStore:
    async def claim_detailed(self, *_args, **_kwargs):
        return ClaimResult("IDLE")


@pytest.mark.asyncio
async def test_idle_queue_is_not_reported_as_terminal_blocked() -> None:
    result = await DurableOutboxWorker(IdleStore(), "CANDLE_V1", None, strict_order=True).run_once()
    assert result == {"claimed": 0, "completed": 0, "retried": 0, "quarantined": 0}


class ReplayStore:
    def __init__(self, trades):
        self.trades = trades

    async def replay_input(self, _item, _since):
        return self.trades


class CandleRepository:
    def __init__(self):
        self.rows = {}

    async def upsert_candle(self, candle):
        self.rows[(candle.symbol, candle.timeframe, candle.open_time)] = candle


def trades() -> list[Trade]:
    return [
        Trade("BTCUSDT", 100.0 + index, 1.0, NOW + timedelta(seconds=30 * index), index, False)
        for index in range(6)
    ]


@pytest.mark.asyncio
async def test_out_of_order_replay_is_independent_of_newer_live_state(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", type("S", (), {"timeframes": ("1m",)})())
    app = main.TIMApplication.__new__(main.TIMApplication)
    app.durable_store = ReplayStore(trades())
    app.repository = CandleRepository()
    app.aggregator = CandleAggregator(("1m",))
    app.aggregator.add_trade(trades()[-1])

    await app._replay_persisted_trade(outbox_item(), trades()[1])

    expected = CandleRepository()
    chronological = CandleAggregator(("1m",))
    for value in trades():
        for candle in chronological.add_trade(value):
            await expected.upsert_candle(candle)
    assert app.repository.rows == expected.rows


@pytest.mark.asyncio
async def test_replay_is_deterministic_and_candle_upserts_are_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(main, "settings", type("S", (), {"timeframes": ("1m",)})())
    app = main.TIMApplication.__new__(main.TIMApplication)
    app.durable_store = ReplayStore(trades())
    app.repository = CandleRepository()
    item = outbox_item()
    await app._replay_persisted_trade(item, trades()[1])
    first = dict(app.repository.rows)
    await app._replay_persisted_trade(item, trades()[1])
    assert app.repository.rows == first


def test_candle_upsert_repairs_every_deterministic_price_field() -> None:
    source = __import__("inspect").getsource(__import__("src.database.repository", fromlist=["MarketRepository"]).MarketRepository.upsert_candle)
    for assignment in (
        "open=EXCLUDED.open",
        "high=EXCLUDED.high",
        "low=EXCLUDED.low",
        "close=EXCLUDED.close",
        "volume=EXCLUDED.volume",
        "trade_count=EXCLUDED.trade_count",
    ):
        assert assignment in source


@pytest.mark.asyncio
async def test_worker_routes_only_explicit_out_of_order_failure_to_replay() -> None:
    app = main.TIMApplication.__new__(main.TIMApplication)
    seen = []

    async def fail(_trade):
        raise ValueError("Out-of-order trade rejected")

    async def replay(_item, _trade):
        seen.append("replay")
        return []

    app._enrich_trade = fail
    app._replay_persisted_trade = replay
    result = await app.process_persisted_trade(outbox_item(), trades()[0])
    assert seen == ["replay"]
    assert result["completed_candles"] == []


class RecoveryStore:
    def __init__(self, *, fail_handler: bool = False):
        self.item = outbox_item(status="PROCESSING", last_error="original poison")
        self.state = "QUARANTINED"
        self.fail_handler = fail_handler
        self.previous = None
        self.acks = 0

    async def claim_quarantined(self, _outbox_id, **_kwargs):
        if self.state != "QUARANTINED":
            return None
        self.state = "PROCESSING"
        return self.item

    async def load_trade(self, *_args):
        return trades()[0]

    async def acknowledge(self, *_args):
        self.state = "COMPLETED"
        self.acks += 1
        return True

    async def requarantine(self, _outbox_id, _error, previous_error):
        self.previous = previous_error
        self.state = "QUARANTINED"
        return True


@pytest.mark.asyncio
async def test_targeted_quarantine_recovery_completes_once() -> None:
    store = RecoveryStore()

    async def handler(_item, _trade):
        return {"replayed": True}

    worker = DurableOutboxWorker(store, "CANDLE_V1", handler)
    assert (await worker.recover_one("a" * 64))["status"] == "COMPLETED"
    assert (await worker.recover_one("a" * 64))["status"] == "NOT_QUARANTINED"
    assert store.acks == 1


@pytest.mark.asyncio
async def test_failed_quarantine_recovery_preserves_auditable_error() -> None:
    store = RecoveryStore()

    async def handler(_item, _trade):
        raise RuntimeError("still poison")

    result = await DurableOutboxWorker(store, "CANDLE_V1", handler).recover_one("a" * 64)
    assert result["status"] == "QUARANTINED"
    assert store.state == "QUARANTINED"
    assert store.previous == "original poison"


@pytest.mark.asyncio
async def test_unrelated_value_error_is_not_silently_replayed() -> None:
    app = main.TIMApplication.__new__(main.TIMApplication)

    async def fail(_trade):
        raise ValueError("unrelated validation failure")

    async def restore(**_kwargs):
        return None

    app._enrich_trade = fail
    app.restore_persisted_state = restore
    with pytest.raises(ValueError, match="unrelated"):
        await app.process_persisted_trade(outbox_item(), trades()[0])
