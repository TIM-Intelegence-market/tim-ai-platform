"""Regression: a clean server close (1000/1001) must be handled as a disconnect.

websockets ends iteration without raising on a clean close. BinanceTradeStream
used to fall straight back into its loop: no backoff, no DISCONNECTED
telemetry and no catch-up before the next live trade (#12 P1.10).
"""
from __future__ import annotations

import asyncio
import json

import pytest
import websockets

from src.data_ingestion.binance_ws import BinanceTradeStream


def raw(trade_id: int) -> str:
    return json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": trade_id, "p": "100", "q": "1",
                       "T": 1767225600000, "m": False})


class Socket:
    close_code = 1000

    def __init__(self, messages):
        self.messages = iter(messages)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise StopAsyncIteration from None


class Context:
    def __init__(self, socket):
        self.socket = socket

    async def __aenter__(self):
        return self.socket

    async def __aexit__(self, *_args):
        return False


@pytest.mark.asyncio
async def test_clean_close_is_handled_as_disconnect(monkeypatch) -> None:
    contexts = iter([Context(Socket([raw(1), raw(2)])), Context(Socket([raw(5)]))])
    monkeypatch.setattr("src.data_ingestion.binance_ws.websockets.connect", lambda *_a, **_k: next(contexts))
    waits = []

    async def no_sleep(awaitable, *, timeout):
        awaitable.close()
        waits.append(timeout)
        raise TimeoutError

    monkeypatch.setattr("src.data_ingestion.binance_ws.asyncio.wait_for", no_sleep)
    events, order = [], []
    stream = None

    async def on_event(name, fields):
        events.append((name, dict(fields)))

    async def recover(trade):
        order.append(("recover", trade.trade_id))

    async def handle(trade):
        order.append(("handle", trade.trade_id))
        if trade.trade_id == 5:
            stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle,
                                stream_event_handler=on_event, recovery_handler=recover)
    await stream.run()

    assert order == [("handle", 1), ("handle", 2), ("recover", 5), ("handle", 5)]
    disconnects = [fields for name, fields in events if name == "DISCONNECTED"]
    assert len(disconnects) == 1 and disconnects[0]["error_type"] == "StreamClosed"
    assert len(waits) == 1 and waits[0] >= 2.0


@pytest.mark.asyncio
async def test_stop_request_does_not_count_as_disconnect(monkeypatch) -> None:
    monkeypatch.setattr("src.data_ingestion.binance_ws.websockets.connect",
                        lambda *_a, **_k: Context(Socket([raw(1)])))
    events = []
    stream = None

    async def on_event(name, fields):
        events.append(name)

    async def handle(_trade):
        stream.stop()

    stream = BinanceTradeStream("wss://stream.binance.com/ws", "BTCUSDT", handle, stream_event_handler=on_event)
    await stream.run()
    assert events == ["CONNECTED"]


@pytest.mark.asyncio
async def test_runtime_clean_close_on_loopback_server_triggers_backoff_and_recovery() -> None:
    """Real websockets server on 127.0.0.1 closes with 1000 after two trades."""
    connections: list[float] = []
    loop = asyncio.get_running_loop()

    async def serve(ws):
        connections.append(loop.time())
        if len(connections) == 1:
            await ws.send(raw(1))
            await ws.send(raw(2))
            await ws.close(code=1000, reason="rotation")
        else:
            await ws.send(raw(5))
            await asyncio.sleep(0.2)  # stop() is requested by now; this close must not count
            await ws.close(code=1000)

    async with websockets.serve(serve, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        events, recovered, handled = [], [], []
        stream = None

        async def on_event(name, fields):
            events.append((name, dict(fields)))

        async def recover(trade):
            recovered.append(trade.trade_id)

        async def handle(trade):
            handled.append(trade.trade_id)
            if trade.trade_id == 5:
                stream.stop()

        stream = BinanceTradeStream(f"ws://127.0.0.1:{port}", "BTCUSDT", handle,
                                    stream_event_handler=on_event, recovery_handler=recover)
        await asyncio.wait_for(stream.run(), 30)

    assert handled == [1, 2, 5]
    assert recovered == [5]
    assert [name for name, _ in events] == ["CONNECTED", "DISCONNECTED", "CONNECTED", "RECOVERY_COMPLETE"]
    assert events[1][1]["error_type"] == "StreamClosed"
    assert connections[1] - connections[0] >= 2.0
