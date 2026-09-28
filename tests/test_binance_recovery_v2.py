from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.data_ingestion.binance_ws import BinanceTradeStream
from src.data_ingestion.catchup import CatchUpResult
from src.data_ingestion.durable import DurableIngestionError
from src.data_ingestion.ingress import DurableIngress


def raw(trade_id: int, symbol: str = "BTCUSDT") -> str:
    return json.dumps({"e": "aggTrade", "s": symbol, "a": trade_id, "p": "100", "q": "1", "T": 1767225600000, "m": False})


class Socket:
    def __init__(self, events):
        self.events = iter(events)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = next(self.events, StopAsyncIteration)
        if value is StopAsyncIteration:
            raise StopAsyncIteration
        if isinstance(value, BaseException):
            raise value
        return value


class Context:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *_args):
        return False


class CursorStore:
    def __init__(self, order: list[tuple]) -> None:
        self.order = order
        self.last_trade_id = None
        self.ingested: list[int] = []
        self.metrics: list[str] = []

    async def get_cursor(self, _symbol: str):
        if self.last_trade_id is None:
            return None
        return SimpleNamespace(last_aggregate_trade_id=self.last_trade_id)

    async def approved_live_cutover(self, _symbol: str, _cursor_id, _first_live_id) -> bool:
        # No documented cutover receipt in tests: always take the fail-closed
        # catch-up path. Required by DurableIngress since live-cutover support
        # was added; without it the same-connection gap path raises
        # AttributeError and the mocked stream reconnects forever.
        return False

    async def ingest_trade(self, trade):
        self.order.append(("ingest", trade.trade_id))
        self.ingested.append(trade.trade_id)
        if self.last_trade_id is None or trade.trade_id > self.last_trade_id:
            self.last_trade_id = trade.trade_id
        return SimpleNamespace(
            cursor=SimpleNamespace(last_aggregate_trade_id=self.last_trade_id),
            queue_depth=len(self.ingested),
        )

    async def record_metric(self, name: str, *_args, **_kwargs) -> None:
        self.metrics.append(name)


class CompletingCatchUp:
    def __init__(self, store: CursorStore) -> None:
        self.store = store

    async def recover_before(
        self,
        symbol: str,
        next_live_trade_id: int,
        *,
        reason: str,
    ) -> CatchUpResult:
        assert self.store.last_trade_id is not None
        start_id = self.store.last_trade_id + 1
        end_id = next_live_trade_id - 1
        self.store.order.append(("catchup", start_id, end_id, reason))
        for trade_id in range(start_id, end_id + 1):
            await self.store.ingest_trade(BinanceTradeStream.parse_message(raw(trade_id)))
        return CatchUpResult(
            "COMPLETE",
            symbol,
            start_id,
            end_id,
            end_id - start_id + 1,
            0,
            1,
        )


class IncompleteCatchUp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, str]] = []

    async def recover_before(
        self,
        symbol: str,
        next_live_trade_id: int,
        *,
        reason: str,
    ) -> CatchUpResult:
        self.calls.append((symbol, next_live_trade_id, reason))
        return CatchUpResult(
            "OPEN",
            symbol,
            next_live_trade_id - 1,
            next_live_trade_id - 1,
            0,
            0,
            1,
            "TEST_ONLY incomplete catch-up",
        )


@pytest.mark.asyncio
async def test_disconnect_runs_catchup_before_first_resumed_live_event(monkeypatch) -> None:
    contexts = iter([Context(Socket([ConnectionError("TEST_ONLY disconnect")])), Context(Socket([raw(12)]))])
    monkeypatch.setattr("src.data_ingestion.binance_ws.websockets.connect", lambda *_args, **_kwargs: next(contexts))

    async def immediate_timeout(_awaitable, *, timeout):
        del timeout
        _awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("src.data_ingestion.binance_ws.asyncio.wait_for", immediate_timeout)
    order = []
    stream = None

    async def recover(trade):
        order.append(("recover", trade.trade_id))

    async def handle(trade):
        order.append(("handle", trade.trade_id))
        stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle, recovery_handler=recover)
    await stream.run()
    assert order == [("recover", 12), ("handle", 12)]


@pytest.mark.asyncio
async def test_parse_and_symbol_errors_are_counted_without_reaching_handler(monkeypatch) -> None:
    handled, events = [], []
    stream = None

    async def handle(trade):
        handled.append(trade.trade_id)
        stream.stop()

    async def event(name, fields):
        events.append((name, fields))

    context = Context(Socket(["not-json", raw(1, "ETHUSDT"), raw(2)]))
    monkeypatch.setattr("src.data_ingestion.binance_ws.websockets.connect", lambda *_args, **_kwargs: context)
    stream = BinanceTradeStream(
        "wss://stream.binance.com/ws", "BTCUSDT", handle, stream_event_handler=event
    )
    await stream.run()
    assert handled == [2]
    assert [name for name, _ in events].count("PARSE_ERROR") == 2


@pytest.mark.asyncio
async def test_same_connection_gap_is_caught_up_before_jump_trade(monkeypatch) -> None:
    order: list[tuple] = []
    store = CursorStore(order)
    ingress = DurableIngress(store, catchup=CompletingCatchUp(store))
    context = Context(Socket([raw(10), raw(12)]))
    connect_calls = 0

    def connect(*_args, **_kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return context

    monkeypatch.setattr("src.data_ingestion.binance_ws.websockets.connect", connect)
    stream = None

    async def handle(trade):
        await ingress(trade)
        if trade.trade_id == 12:
            stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle)
    await stream.run()

    assert connect_calls == 1
    assert order == [
        ("ingest", 10),
        ("catchup", 11, 11, "SAME_CONNECTION_TRADE_ID_GAP"),
        ("ingest", 11),
        ("ingest", 12),
    ]


@pytest.mark.asyncio
async def test_incomplete_same_connection_catchup_rejects_jump_and_reconnects(
    monkeypatch,
) -> None:
    order: list[tuple] = []
    store = CursorStore(order)
    catchup = IncompleteCatchUp()
    ingress = DurableIngress(store, catchup=catchup)
    context = Context(Socket([raw(10), raw(12)]))
    connect_calls = 0
    stream = None
    events = []

    def connect(*_args, **_kwargs):
        nonlocal connect_calls
        connect_calls += 1
        return context

    async def event(name, fields):
        events.append((name, fields))
        if name == "DISCONNECTED":
            stream.stop()

    monkeypatch.setattr("src.data_ingestion.binance_ws.websockets.connect", connect)
    stream = BinanceTradeStream(
        "wss://stream.binance.com/ws",
        "BTCUSDT",
        ingress,
        stream_event_handler=event,
    )
    await stream.run()

    assert connect_calls == 1
    assert store.ingested == [10]
    assert catchup.calls == [("BTCUSDT", 12, "SAME_CONNECTION_TRADE_ID_GAP")]
    assert any(
        name == "DISCONNECTED"
        and fields["error_type"] == DurableIngestionError.__name__
        for name, fields in events
    )


@pytest.mark.asyncio
async def test_ingress_store_interface_prevents_reconnect_hang(monkeypatch) -> None:
    """Regression: a store fake missing DurableIngress-required methods used to
    raise inside the trade handler, so stream.stop() was never reached and the
    mocked stream reconnected to an exhausted socket forever (hang at
    binance_ws run loop). The interface assertion fails fast on future drift;
    the functional run below proves termination with the intended final state."""
    order: list[tuple] = []
    store = CursorStore(order)
    for method in ("get_cursor", "approved_live_cutover", "ingest_trade", "record_metric"):
        assert callable(getattr(store, method, None)), "store fake must implement %s" % method
    ingress = DurableIngress(store, catchup=CompletingCatchUp(store))
    context = Context(Socket([raw(20), raw(22)]))
    connect_calls = 0

    def connect(*_args, **_kwargs):
        nonlocal connect_calls
        connect_calls += 1
        if connect_calls > 1:
            # Fail fast instead of hanging: CancelledError propagates through
            # BinanceTradeStream.run() (it only catches Exception), so an
            # unexpected reconnect ends the test immediately with a clear error
            # rather than looping on an exhausted mock socket forever.
            raise asyncio.CancelledError("unexpected reconnect: run loop did not terminate")
        return context

    monkeypatch.setattr("src.data_ingestion.binance_ws.websockets.connect", connect)
    stream = None

    async def handle(trade):
        await ingress(trade)
        if trade.trade_id == 22:
            stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle)
    await stream.run()

    assert connect_calls == 1
    assert order == [
        ("ingest", 20),
        ("catchup", 21, 21, "SAME_CONNECTION_TRADE_ID_GAP"),
        ("ingest", 21),
        ("ingest", 22),
    ]
    assert store.last_trade_id == 22
