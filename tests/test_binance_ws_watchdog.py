"""Reconnect, timeouts, watchdog and prompt shutdown for the Binance stream.

Regression for the 2026-10-05 server incident: after a reconnect the catch-up
ran inside the socket read loop. websockets pauses the TCP transport once
``max_queue`` frames are unread, pongs stop arriving, and the connection ends
in "keepalive ping timeout" before catch-up finishes; SIGTERM was only seen on
the next message, so the process had to be killed.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
import websockets

from src.data_ingestion import binance_ws
from src.data_ingestion.binance_ws import BinanceTradeStream
from src.data_ingestion.catchup import CatchUpCoordinator


def raw(trade_id: int) -> str:
    return json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": trade_id, "p": "100", "q": "1",
                       "T": 1767225600000, "m": False})


class Socket:
    close_code = 1000

    def __init__(self, messages, *, then_hang: bool = False):
        self.messages = iter(messages)
        self.then_hang = then_hang

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            if self.then_hang:
                await asyncio.Event().wait()
            raise StopAsyncIteration from None


class Context:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *_args):
        return False


def fake_connect(monkeypatch, sockets):
    contexts = iter([Context(socket) for socket in sockets])
    monkeypatch.setattr(binance_ws.websockets, "connect", lambda *_a, **_k: next(contexts))


def record_events(events):
    async def on_event(name, fields):
        events.append((name, dict(fields)))
    return on_event


def fast_backoff(monkeypatch, delays):
    async def wait(_self, delay):
        delays.append(delay)
        await asyncio.sleep(0)
    monkeypatch.setattr(BinanceTradeStream, "_wait_for_stop", wait)


@pytest.mark.asyncio
async def test_slow_catch_up_does_not_starve_keepalive_on_real_socket() -> None:
    """Catch-up longer than the ping timeout while > max_queue frames arrive."""
    async def serve(ws):
        for trade_id in range(1, 3001):
            await ws.send(raw(trade_id))
        await ws.wait_closed()

    async with websockets.serve(serve, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        events, handled = [], []
        stream = None

        async def recover(_trade):
            await asyncio.sleep(2.5)  # > ping_interval + ping_timeout below

        async def handle(trade):
            handled.append(trade.trade_id)
            if trade.trade_id == 3000:
                stream.stop()

        stream = BinanceTradeStream(f"ws://127.0.0.1:{port}", "BTCUSDT", handle,
                                    stream_event_handler=record_events(events),
                                    recovery_handler=recover, recovery_on_connect=True)
        stream.ping_interval = 0.5
        stream.ping_timeout = 0.5
        await asyncio.wait_for(stream.run(), 30)

    assert [name for name, _ in events] == ["CONNECTED", "RECOVERY_COMPLETE"]
    assert handled == list(range(1, 3001))


@pytest.mark.asyncio
async def test_watchdog_reconnects_a_silent_socket_on_real_socket() -> None:
    connections = []

    async def serve(ws):
        connections.append(ws)
        await ws.send(raw(len(connections)))
        await ws.wait_closed()  # open, answers pings, sends nothing more

    async with websockets.serve(serve, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        events, handled, recovered = [], [], []
        stream = None

        async def recover(trade):
            recovered.append(trade.trade_id)

        async def handle(trade):
            handled.append(trade.trade_id)
            if trade.trade_id == 2:
                stream.stop()

        stream = BinanceTradeStream(f"ws://127.0.0.1:{port}", "BTCUSDT", handle,
                                    stream_event_handler=record_events(events),
                                    recovery_handler=recover, stale_after=0.4)
        await asyncio.wait_for(stream.run(), 30)

    assert handled == [1, 2]
    assert recovered == [2]
    disconnects = [fields for name, fields in events if name == "DISCONNECTED"]
    assert [fields["error_type"] for fields in disconnects] == ["StreamStalled"]


@pytest.mark.asyncio
async def test_hung_catch_up_times_out_and_next_connection_recovers(monkeypatch) -> None:
    fake_connect(monkeypatch, [Socket([raw(5)], then_hang=True), Socket([raw(9)], then_hang=True)])
    delays, events, order = [], [], []
    fast_backoff(monkeypatch, delays)
    calls = 0
    stream = None

    async def recover(trade):
        nonlocal calls
        calls += 1
        order.append(("recover", trade.trade_id))
        if calls == 1:
            await asyncio.Event().wait()  # e.g. a REST request or DB call that never returns

    async def handle(trade):
        order.append(("handle", trade.trade_id))
        stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle,
                                stream_event_handler=record_events(events), recovery_handler=recover,
                                recovery_on_connect=True, recovery_timeout=0.2)
    await asyncio.wait_for(stream.run(), 10)

    assert order == [("recover", 5), ("recover", 9), ("handle", 9)]
    disconnects = [fields for name, fields in events if name == "DISCONNECTED"]
    assert [fields["error_type"] for fields in disconnects] == ["RecoveryTimeout"]


@pytest.mark.asyncio
async def test_hung_handler_times_out_and_reconnects_with_recovery(monkeypatch) -> None:
    fake_connect(monkeypatch, [Socket([raw(1)], then_hang=True), Socket([raw(4)], then_hang=True)])
    delays, events, recovered = [], [], []
    fast_backoff(monkeypatch, delays)
    stream = None

    async def recover(trade):
        recovered.append(trade.trade_id)

    async def handle(trade):
        if trade.trade_id == 1:
            await asyncio.Event().wait()
        stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle,
                                stream_event_handler=record_events(events), recovery_handler=recover,
                                handler_timeout=0.2)
    await asyncio.wait_for(stream.run(), 10)

    assert recovered == [4]
    assert [f["error_type"] for n, f in events if n == "DISCONNECTED"] == ["HandlerTimeout"]


@pytest.mark.asyncio
async def test_stop_interrupts_a_hung_catch_up_promptly(monkeypatch) -> None:
    fake_connect(monkeypatch, [Socket([raw(5)], then_hang=True)])
    events = []
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def recover(_trade):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def handle(_trade):
        raise AssertionError("no live trade may pass an unfinished catch-up")

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle,
                                stream_event_handler=record_events(events), recovery_handler=recover,
                                recovery_on_connect=True)
    task = asyncio.create_task(stream.run())
    await asyncio.wait_for(started.wait(), 5)
    loop = asyncio.get_running_loop()
    began = loop.time()
    stream.stop()
    await asyncio.wait_for(task, 5)

    assert loop.time() - began < 1.0
    assert cancelled.is_set()
    assert [name for name, _ in events] == ["CONNECTED"]


@pytest.mark.asyncio
async def test_stop_interrupts_a_silent_socket_promptly(monkeypatch) -> None:
    fake_connect(monkeypatch, [Socket([], then_hang=True)])

    async def handle(_trade):
        raise AssertionError("no data expected")

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle)
    task = asyncio.create_task(stream.run())
    await asyncio.sleep(0.05)
    stream.stop()
    await asyncio.wait_for(task, 1)


@pytest.mark.asyncio
async def test_backoff_grows_in_a_reconnect_loop_and_resets_after_stable_live_data(monkeypatch) -> None:
    class Failing(Socket):
        async def __anext__(self):
            raise ConnectionError("keepalive ping timeout")

    sockets = [Failing([]), Failing([]), Failing([]), Socket([raw(1)]), Failing([]), Socket([raw(2)])]
    fake_connect(monkeypatch, sockets)
    delays, events = [], []
    fast_backoff(monkeypatch, delays)
    stream = None

    async def handle(trade):
        if trade.trade_id == 2:
            stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle,
                                stream_event_handler=record_events(events), stable_after=0.0)
    await asyncio.wait_for(stream.run(), 10)

    attempts = [f["attempt"] for n, f in events if n == "DISCONNECTED"]
    # A connection that drops right after connecting never resets the counter;
    # the one that delivered live data (trade 1, stable_after=0) does.
    assert attempts == [1, 2, 3, 1, 2]
    assert delays[0] >= 2.0 and delays[2] >= 8.0
    assert all(delay <= binance_ws.MAX_BACKOFF_SECONDS + 1 for delay in delays)


@pytest.mark.asyncio
async def test_buffer_limit_drops_the_connection_instead_of_growing_forever(monkeypatch) -> None:
    fake_connect(monkeypatch, [Socket([raw(i) for i in range(1, 50)], then_hang=True),
                               Socket([raw(100)], then_hang=True)])
    delays, events, recovered = [], [], []
    fast_backoff(monkeypatch, delays)
    gate = asyncio.Event()
    stream = None

    async def recover(trade):
        recovered.append(trade.trade_id)

    async def handle(trade):
        if trade.trade_id == 1:
            await gate.wait()  # released only by the cancellation of the session
        if trade.trade_id == 100:
            stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle,
                                stream_event_handler=record_events(events), recovery_handler=recover,
                                buffer_limit=10)
    await asyncio.wait_for(stream.run(), 10)

    assert [f["error_type"] for n, f in events if n == "DISCONNECTED"] == ["StreamBackpressure"]
    assert recovered == [100]


@pytest.mark.asyncio
async def test_hung_telemetry_does_not_block_reconnect(monkeypatch) -> None:
    monkeypatch.setattr(binance_ws, "EVENT_TIMEOUT_SECONDS", 0.05)
    fake_connect(monkeypatch, [Socket([]), Socket([raw(1)], then_hang=True)])
    delays, handled = [], []
    fast_backoff(monkeypatch, delays)
    stream = None

    async def hung_event(_name, _fields):
        await asyncio.Event().wait()

    async def handle(trade):
        handled.append(trade.trade_id)
        stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle, stream_event_handler=hung_event)
    await asyncio.wait_for(stream.run(), 5)
    assert handled == [1]
    assert len(delays) == 1


class GapStore:
    def __init__(self) -> None:
        self.gap_status: list[tuple[str, str, str | None]] = []
        self.recovery_states: list[str] = []
        self.metrics: list[str] = []

    async def get_cursor(self, _symbol):
        return SimpleNamespace(last_aggregate_trade_id=10)

    async def record_gap(self, **_kwargs):
        return "gap-1"

    async def set_gap_status(self, gap_id, status, *, error=None):
        self.gap_status.append((gap_id, status, error))

    async def set_recovery_state(self, _symbol, state):
        self.recovery_states.append(state)

    async def record_metric(self, name, *_args, **_kwargs):
        self.metrics.append(name)


class HangingClient:
    async def fetch(self, *_args, **_kwargs):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_cancelled_catch_up_leaves_gap_open_not_catching_up() -> None:
    store = GapStore()
    coordinator = CatchUpCoordinator(store, HangingClient())
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            await coordinator.recover_before("BTCUSDT", 20)

    assert store.gap_status[0][:2] == ("gap-1", "CATCHING_UP")
    assert store.gap_status[-1][:2] == ("gap-1", "OPEN")
    assert "cancelled" in store.gap_status[-1][2]
    assert store.recovery_states[-1] == "GAP_DETECTED"
    assert "catchup_failure_total" in store.metrics
