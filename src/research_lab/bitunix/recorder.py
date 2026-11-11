"""Public Bitunix recorder (shadow, no API key): trades + top-of-book for BTCUSDT and friends.

Bitunix has no public REST endpoint for historic trades, so a Bitunix footprint can only come from recording the
public WebSocket ``trade`` channel ourselves. Each message is stored unchanged with the local receive time
(processing time) next to the exchange time (event time), one gzip JSONL file per UTC day and symbol:
``<root>/<symbol>/<YYYY-MM-DD>.jsonl.gz``. Reconnect gaps are written as ``{"kind": "gap", ...}`` rows so that a
later study can drop the affected minutes instead of treating them as quiet.

Known limits (docs 11.11.2026): trade ``t`` has second resolution only; side ``s`` is the taker side; at most
5 messages per second may be sent to the server (pings + subscriptions), 300 channels per connection.

    python -m src.research_lab.bitunix record --root ~/TIM-research/bitunix [--symbols BTCUSDT,ETHUSDT,SOLUSDT]
"""
from __future__ import annotations

import asyncio
import gzip
import json
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_WS = "wss://fapi.bitunix.com/public/"
CHANNELS = ("trade", "depth_book1")
PING_SECONDS = 20.0


def subscribe_message(symbols: Iterable[str], channels: Iterable[str] = CHANNELS) -> dict:
    return {"op": "subscribe", "args": [{"symbol": s, "ch": c} for s in symbols for c in channels]}


def day_path(root: Path, symbol: str, ts_ms: int) -> Path:
    day = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return root / symbol / f"{day}.jsonl.gz"


class DayWriter:
    """Append-only gzip writer, one open file per symbol, rolled at UTC midnight."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._open: dict[str, tuple[Path, gzip.GzipFile]] = {}

    def write(self, symbol: str, row: dict, recv_ms: int) -> None:
        path = day_path(self.root, symbol, recv_ms)
        current = self._open.get(symbol)
        if current is None or current[0] != path:
            if current is not None:
                current[1].close()
            path.parent.mkdir(parents=True, exist_ok=True)
            current = (path, gzip.open(path, "ab"))
            self._open[symbol] = current
        current[1].write((json.dumps(row, separators=(",", ":")) + "\n").encode())

    def flush(self) -> None:
        for _, fh in self._open.values():
            fh.flush()

    def close(self) -> None:
        for _, fh in self._open.values():
            fh.close()
        self._open.clear()


def handle(raw: str | bytes, writer: DayWriter, recv_ms: int) -> str | None:
    """Store one server message. Returns the channel name or None for control messages."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    ch = msg.get("ch")
    symbol = msg.get("symbol")
    if ch not in CHANNELS or not isinstance(symbol, str):
        return None
    writer.write(symbol, {"kind": ch, "recv_ms": recv_ms, "msg": msg}, recv_ms)
    return ch


async def record(
    root: Path, symbols: list[str], *, stop_after: float | None = None, connect: Callable | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, int]:
    """Record until cancelled (or ``stop_after`` seconds). Reconnects with backoff; logs gaps."""
    if connect is None:
        import websockets

        connect = websockets.connect
    writer = DayWriter(root)
    counts = {c: 0 for c in CHANNELS}
    started = clock()
    backoff = 1.0
    last_ok_ms: int | None = None
    try:
        while stop_after is None or clock() - started < stop_after:
            try:
                async with connect(PUBLIC_WS, ping_interval=None, max_size=2**22) as ws:
                    await ws.send(json.dumps(subscribe_message(symbols)))
                    now_ms = int(clock() * 1000)
                    if last_ok_ms is not None:
                        for s in symbols:
                            writer.write(s, {"kind": "gap", "from_ms": last_ok_ms, "to_ms": now_ms}, now_ms)
                    backoff = 1.0
                    next_ping = clock() + PING_SECONDS
                    while stop_after is None or clock() - started < stop_after:
                        timeout = max(0.1, next_ping - clock())
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"op": "ping", "ping": int(clock())}))
                            next_ping = clock() + PING_SECONDS
                            writer.flush()
                            continue
                        last_ok_ms = int(clock() * 1000)
                        ch = handle(raw, writer, last_ok_ms)
                        if ch:
                            counts[ch] += 1
            except (OSError, asyncio.TimeoutError, ConnectionError) as exc:  # network: reconnect
                print(f"bitunix recorder: reconnect after {type(exc).__name__}: {exc}", flush=True)
            except Exception as exc:  # websockets.ConnectionClosed and friends
                print(f"bitunix recorder: reconnect after {type(exc).__name__}: {exc}", flush=True)
            if stop_after is not None and clock() - started >= stop_after:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
    finally:
        writer.close()
    return counts
