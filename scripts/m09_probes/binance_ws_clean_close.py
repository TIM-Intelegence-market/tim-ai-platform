"""Runtime probe for the Binance clean-close defect (Issue #12 P1.10/P1.14).

Starts a websockets server on 127.0.0.1 that closes cleanly (1000) after two
trades, runs BinanceTradeStream from the current checkout against it and
prints one JSON object. ``defect_present`` is true when the clean close is not
handled as a disconnect (no DISCONNECTED event, no backoff, no catch-up).
Loopback only; no Binance, database or trading access.
"""
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path.cwd()))

import websockets  # noqa: E402

from src.data_ingestion.binance_ws import BinanceTradeStream  # noqa: E402


def raw(trade_id):
    return json.dumps({"e": "aggTrade", "s": "BTCUSDT", "a": trade_id, "p": "100", "q": "1",
                       "T": 1767225600000, "m": False})


async def main():
    loop = asyncio.get_running_loop()
    connections = []

    async def serve(ws):
        connections.append(loop.time())
        if len(connections) == 1:
            await ws.send(raw(1))
            await ws.send(raw(2))
            await ws.close(code=1000, reason="rotation")
        else:
            await ws.send(raw(5))
            await asyncio.sleep(0.2)
            await ws.close(code=1000)

    async with websockets.serve(serve, "127.0.0.1", 0) as server:
        url = "ws://127.0.0.1:%d" % server.sockets[0].getsockname()[1]
        events, recovered, handled = [], [], []
        stream = None

        async def on_event(name, fields):
            events.append({"name": name, **{k: v for k, v in fields.items() if k != "delay_seconds"}})

        async def recover(trade):
            recovered.append(trade.trade_id)

        async def handle(trade):
            handled.append(trade.trade_id)
            if trade.trade_id == 5:
                stream.stop()

        stream = BinanceTradeStream(url, "BTCUSDT", handle, stream_event_handler=on_event, recovery_handler=recover)
        await asyncio.wait_for(stream.run(), 30)
    gap = round(connections[1] - connections[0], 3)
    disconnects = [e for e in events if e["name"] == "DISCONNECTED"]
    checks = {
        "disconnect_event_emitted": len(disconnects) == 1,
        "backoff_before_reconnect_ge_2s": gap >= 2.0,
        "catchup_before_next_live_trade": recovered == [5],
        "all_live_trades_handled": handled == [1, 2, 5],
    }
    print(json.dumps({"probe": "binance_ws_clean_close", "network": "127.0.0.1", "defect_present": not all(checks.values()),
                      "checks": checks, "events": events, "reconnect_gap_seconds": gap,
                      "websockets_version": websockets.__version__}, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
