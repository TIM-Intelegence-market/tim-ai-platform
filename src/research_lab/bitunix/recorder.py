"""Public Bitunix recorder (shadow, no API key): trades + top-of-book for BTCUSDT and friends.

Bitunix has no public REST endpoint for historic trades, so a Bitunix footprint can only come from recording the
public WebSocket ``trade`` channel ourselves. Each message is stored unchanged with the local receive time
(processing time) next to the exchange time (event time), one gzip JSONL file per UTC day and symbol:
``<root>/<symbol>/<YYYY-MM-DD>.jsonl.gz``.

Safety and health (review PR #226):
- Only symbols from the subscribed allowlist are written, and every target path must resolve inside ``root``.
  A message with any other symbol is dropped and counted (``rejected``).
- Network errors reconnect with backoff. Storage errors (disk full, permissions, a broken file) are fatal: the
  recorder writes ``status: "failed"`` if it still can and exits non-zero, so a supervisor (launchd) restarts it
  and the gap is visible instead of silently losing data. Below ``min_free_bytes`` free space it stops the same way.
- ``<root>/status.json`` is rewritten at every flush: last receive time, counts, gaps, free bytes. On start the
  recorder reads it and writes a ``gap`` row from the last receive time, so restarts leave a marked hole.

Known limits (docs 11.11.2026): trade ``t`` has second resolution only, no trade id; side ``s`` is the taker side;
at most 5 messages per second may be sent to the server (pings + subscriptions), 300 channels per connection.

    python -m src.research_lab.bitunix record --root ~/TIM-research/bitunix [--symbols BTCUSDT,ETHUSDT,SOLUSDT]
"""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
import shutil
import time
import zlib
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

PUBLIC_WS = "wss://fapi.bitunix.com/public/"
CHANNELS = ("trade", "depth_book1")
PING_SECONDS = 20.0
MIN_FREE_BYTES = 2 * 1024**3
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}$")


class StorageError(RuntimeError):
    """Local write problem. Never retried as if it were a network error."""


def validate_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    out = tuple(symbols)
    if not out:
        raise ValueError("at least one symbol")
    for s in out:
        if not _SYMBOL_RE.fullmatch(s):
            raise ValueError(f"invalid symbol {s!r}")
    return out


def subscribe_message(symbols: Iterable[str], channels: Iterable[str] = CHANNELS) -> dict:
    return {"op": "subscribe", "args": [{"symbol": s, "ch": c} for s in symbols for c in channels]}


def day_path(root: Path, symbol: str, ts_ms: int) -> Path:
    day = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return root / symbol / f"{day}.jsonl.gz"


class DayWriter:
    """Append-only gzip writer, one open file per allowed symbol, rolled at UTC midnight."""

    def __init__(self, root: Path, symbols: Iterable[str]) -> None:
        self.root = root.resolve()
        self.allowed = frozenset(validate_symbols(symbols))
        self._open: dict[str, tuple[Path, gzip.GzipFile]] = {}

    def write(self, symbol: str, row: dict, recv_ms: int) -> None:
        if symbol not in self.allowed:
            raise ValueError(f"symbol {symbol!r} not in allowlist")
        path = day_path(self.root, symbol, recv_ms)
        if not path.resolve().is_relative_to(self.root):
            raise ValueError(f"path {path} leaves {self.root}")
        try:
            current = self._open.get(symbol)
            if current is None or current[0] != path:
                if current is not None:
                    current[1].close()
                path.parent.mkdir(parents=True, exist_ok=True)
                current = (path, gzip.open(path, "ab"))  # noqa: SIM115 - long-lived, closed in close()
                self._open[symbol] = current
            current[1].write((json.dumps(row, separators=(",", ":")) + "\n").encode())
        except (OSError, zlib.error, EOFError) as exc:
            raise StorageError(f"write {path}: {exc}") from exc

    def flush(self) -> None:
        try:
            for _, fh in self._open.values():
                fh.flush()
        except (OSError, zlib.error) as exc:
            raise StorageError(f"flush: {exc}") from exc

    def close(self) -> None:
        errors = []
        for _, fh in self._open.values():
            try:
                fh.close()
            except (OSError, zlib.error) as exc:
                errors.append(str(exc))
        self._open.clear()
        if errors:
            raise StorageError("close: " + "; ".join(errors))


def handle(raw: str | bytes, writer: DayWriter, recv_ms: int) -> str | None:
    """Store one server message. Returns the channel, ``"rejected"`` for a foreign symbol, None for control."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None
    ch = msg.get("ch")
    symbol = msg.get("symbol")
    if ch not in CHANNELS:
        return None
    if not isinstance(symbol, str) or symbol not in writer.allowed:
        return "rejected"
    writer.write(symbol, {"kind": ch, "recv_ms": recv_ms, "msg": msg}, recv_ms)
    return ch


class Status:
    """``<root>/status.json``: heartbeat for a supervisor and the restart-gap anchor."""

    def __init__(self, root: Path) -> None:
        self.path = root / "status.json"

    def load_last_recv_ms(self) -> int | None:
        try:
            value = json.loads(self.path.read_text()).get("last_recv_ms")
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise StorageError(f"status unreadable: {exc}") from exc
        return int(value) if isinstance(value, int) else None

    def write(self, state: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(state, separators=(",", ":")))
            os.replace(tmp, self.path)
        except OSError as exc:
            raise StorageError(f"status write: {exc}") from exc


def free_bytes(root: Path) -> int:
    return shutil.disk_usage(root).free


async def record(
    root: Path, symbols: list[str], *, stop_after: float | None = None, connect: Callable | None = None,
    clock: Callable[[], float] = time.time, min_free_bytes: int = MIN_FREE_BYTES,
    disk_free: Callable[[Path], int] = free_bytes,
) -> dict[str, int]:
    """Record until cancelled (or ``stop_after`` seconds). Network errors reconnect; StorageError propagates."""
    if connect is None:
        import websockets

        connect = websockets.connect
    symbols = list(validate_symbols(symbols))
    root.mkdir(parents=True, exist_ok=True)
    writer = DayWriter(root, symbols)
    status = Status(root)
    counts = {c: 0 for c in CHANNELS} | {"rejected": 0, "gaps": 0, "reconnects": 0}
    started = clock()
    backoff = 1.0
    last_ok_ms = status.load_last_recv_ms()  # restart gap from the previous run

    def heartbeat(state: str) -> None:
        free = disk_free(root)
        status.write({"state": state, "pid": os.getpid(), "symbols": symbols, "updated_ms": int(clock() * 1000),
                      "last_recv_ms": last_ok_ms, "free_bytes": free, "counts": counts})
        if free < min_free_bytes:
            raise StorageError(f"free space {free} below {min_free_bytes}")

    try:
        heartbeat("starting")
        while stop_after is None or clock() - started < stop_after:
            try:
                async with connect(PUBLIC_WS, ping_interval=None, max_size=2**22) as ws:
                    await ws.send(json.dumps(subscribe_message(symbols)))
                    now_ms = int(clock() * 1000)
                    if last_ok_ms is not None:
                        for s in symbols:
                            writer.write(s, {"kind": "gap", "from_ms": last_ok_ms, "to_ms": now_ms}, now_ms)
                        counts["gaps"] += 1
                    backoff = 1.0
                    next_ping = clock() + PING_SECONDS
                    while stop_after is None or clock() - started < stop_after:
                        timeout = max(0.1, next_ping - clock())
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        except asyncio.TimeoutError:
                            raw = None
                        if raw is not None:
                            recv_ms = int(clock() * 1000)
                            ch = handle(raw, writer, recv_ms)
                            if ch:
                                counts[ch] += 1
                                if ch != "rejected":
                                    last_ok_ms = recv_ms
                        if clock() >= next_ping:
                            await ws.send(json.dumps({"op": "ping", "ping": int(clock())}))
                            next_ping = clock() + PING_SECONDS
                            writer.flush()
                            heartbeat("running")
            except StorageError:
                raise
            except Exception as exc:  # noqa: BLE001 - network side (ConnectionClosed, handshake, OSError); storage re-raised above
                counts["reconnects"] += 1
                print(f"bitunix recorder: reconnect after {type(exc).__name__}: {exc}", flush=True)
            if stop_after is not None and clock() - started >= stop_after:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
        writer.close()
        heartbeat("stopped")
    except StorageError as exc:
        try:
            status.write({"state": "failed", "error": str(exc), "updated_ms": int(clock() * 1000),
                          "last_recv_ms": last_ok_ms, "counts": counts})
        except StorageError:
            pass
        raise
    finally:
        try:
            writer.close()
        except StorageError:
            pass
    return counts
