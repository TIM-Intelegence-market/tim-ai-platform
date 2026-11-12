"""Public order book recorder for Binance USDⓈ-M BTCUSDT (shadow, no API key, no orders).

Two WebSocket connections, as Binance routes them since 2026 (Important WebSocket Change Notice, read 12.11.2026):

- ``/public``: ``btcusdt@depth@100ms`` (diff depth), plus a REST snapshot ``/fapi/v1/depth?limit=1000`` after
  connecting and after every sequence gap (never periodically, at most once per ``SNAPSHOT_MIN_SECONDS``);
- ``/market``: ``btcusdt@aggTrade`` (aggressor side).

Every message is stored unchanged with the local receive time, one gzip JSONL segment per UTC day and run (same
writer, status file and failure rules as the Bitunix recorder, review PR #226). The recorder also runs
:class:`DepthSync` live and writes, for every exchange second with depth events, a ``second`` row with the book
checksum. The replay (:mod:`replay`) must reproduce these checksums from the raw rows: that is the acceptance test
of the data contract (S8 Depth-Datenvertrag, Abschnitt 5).

Binance closes a connection after 24 h; the recorder reconnects earlier (``ROTATE_SECONDS``). Every reconnect and
restart leaves a ``gap`` row, so a hole is visible instead of silent.

    python -m src.research_lab.depth record --root ~/TIM-research/depth [--seconds 600]
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from src.research_lab.bitunix.recorder import (
    DayWriter,
    Status,
    StorageError,
    free_bytes,
)
from src.research_lab.depth.sync import DepthSync

SYMBOL = "BTCUSDT"
DEPTH_URL = "wss://fstream.binance.com/public/stream?streams=btcusdt@depth@100ms"
TRADE_URL = "wss://fstream.binance.com/market/stream?streams=btcusdt@aggTrade"
SNAPSHOT_URL = "https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=1000"
SNAPSHOT_MIN_SECONDS = 30.0
ROTATE_SECONDS = 23.5 * 3600
HEARTBEAT_SECONDS = 10.0
MIN_FREE_BYTES = 2 * 1024**3


def fetch_snapshot_http(url: str = SNAPSHOT_URL, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "tim-research-depth/1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def unwrap(raw: str | bytes) -> dict | None:
    """Combined-stream wrapper ``{"stream": ..., "data": {...}}`` to the payload; None for anything else."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None
    data = msg.get("data", msg)
    return data if isinstance(data, dict) else None


class Recorder:
    def __init__(self, root: Path, *, clock: Callable[[], float] = time.time,
                 fetch_snapshot: Callable[[], dict] = fetch_snapshot_http) -> None:
        self.root = root
        self.clock = clock
        self.fetch_snapshot = fetch_snapshot
        self.writer = DayWriter(root, [SYMBOL], run_id=int(clock() * 1000))
        self.sync = DepthSync()
        self.counts = {"depth": 0, "aggTrade": 0, "snapshots": 0, "snapshot_errors": 0, "seq_gaps": 0,
                       "gaps": 0, "reconnects": 0, "seconds": 0, "valid_seconds": 0, "foreign": 0}
        self.last_recv_ms: dict[str, int | None] = {"depth": None, "trades": None}
        self._sec: int | None = None
        self._last_snapshot_at = -1e18

    def now_ms(self) -> int:
        return int(self.clock() * 1000)

    def write(self, row: dict) -> None:
        self.writer.write(SYMBOL, row, row.get("recv_ms") or self.now_ms())

    def _close_seconds(self, upto_sec: int) -> None:
        """Checkpoint the book for the open exchange second before an event of a later second is applied."""
        if self._sec is not None and upto_sec > self._sec:
            valid = self.sync.valid
            self.write({"kind": "second", "recv_ms": self.now_ms(), "sec": self._sec, "valid": valid,
                        "sum": self.sync.book.checksum() if valid else None})
            self.counts["seconds"] += 1
            self.counts["valid_seconds"] += int(valid)
        if self._sec is None or upto_sec > self._sec:
            self._sec = upto_sec

    def on_depth(self, data: dict, recv_ms: int) -> None:
        if data.get("e") != "depthUpdate" or data.get("s") != SYMBOL:
            self.counts["foreign"] += 1
            return
        self._close_seconds(int(data["E"]) // 1000)
        self.write({"kind": "depth", "recv_ms": recv_ms, "msg": data})
        self.counts["depth"] += 1
        if self.sync.on_event(data) == "gap":
            self.counts["seq_gaps"] += 1
            self.write({"kind": "seq_gap", "recv_ms": recv_ms, "pu": data.get("pu"), "u": data.get("u")})

    def on_trade(self, data: dict, recv_ms: int) -> None:
        if data.get("e") != "aggTrade" or data.get("s") != SYMBOL:
            self.counts["foreign"] += 1
            return
        self.write({"kind": "aggTrade", "recv_ms": recv_ms, "msg": data})
        self.counts["aggTrade"] += 1

    async def maybe_snapshot(self) -> None:
        if not self.sync.needs_snapshot or self.clock() - self._last_snapshot_at < SNAPSHOT_MIN_SECONDS:
            return
        self._last_snapshot_at = self.clock()
        try:
            snap = await asyncio.to_thread(self.fetch_snapshot)
            int(snap["lastUpdateId"])
        except Exception as exc:  # noqa: BLE001 - network or malformed answer: retry after the minimum interval
            self.counts["snapshot_errors"] += 1
            print(f"depth recorder: snapshot failed: {type(exc).__name__}: {exc}", flush=True)
            return
        recv_ms = self.now_ms()
        self.write({"kind": "snapshot", "recv_ms": recv_ms, "msg": snap})
        self.counts["snapshots"] += 1
        self.sync.on_snapshot(snap)

    def mark_gap(self, stream: str) -> None:
        last = self.last_recv_ms[stream]
        if last is not None:
            self.write({"kind": "gap", "stream": stream, "from_ms": last, "to_ms": self.now_ms(),
                        "recv_ms": self.now_ms()})
            self.counts["gaps"] += 1
        if stream == "depth":
            self.sync.invalidate()


async def _stream(rec: Recorder, stream: str, url: str, connect: Callable, until: Callable[[], bool],
                  sleep: Callable) -> None:
    backoff = 1.0
    while not until():
        try:
            async with connect(url, max_size=2**23) as ws:
                opened = rec.clock()
                rec.mark_gap(stream)
                rec.write({"kind": "session", "stream": stream, "url": url, "recv_ms": rec.now_ms()})
                backoff = 1.0
                while not until() and rec.clock() - opened < ROTATE_SECONDS:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        raw = None
                    if raw is not None:
                        data = unwrap(raw)
                        recv_ms = rec.now_ms()
                        if data is not None:
                            if stream == "depth":
                                rec.on_depth(data, recv_ms)
                            else:
                                rec.on_trade(data, recv_ms)
                            rec.last_recv_ms[stream] = recv_ms
                    if stream == "depth":
                        await rec.maybe_snapshot()
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 - network side; storage errors re-raised above
            rec.counts["reconnects"] += 1
            print(f"depth recorder: {stream} reconnect after {type(exc).__name__}: {exc}", flush=True)
        if until():
            break
        await sleep(backoff)
        backoff = min(backoff * 2, 60.0)


async def record(root: Path, *, stop_after: float | None = None, connect: Callable | None = None,
                 clock: Callable[[], float] = time.time, fetch_snapshot: Callable[[], dict] = fetch_snapshot_http,
                 sleep: Callable = asyncio.sleep, min_free_bytes: int = MIN_FREE_BYTES,
                 disk_free: Callable[[Path], int] = free_bytes) -> dict[str, int]:
    """Record until cancelled (or ``stop_after`` seconds). Network errors reconnect; StorageError propagates."""
    if connect is None:
        import websockets

        connect = websockets.connect
    root.mkdir(parents=True, exist_ok=True)
    status = Status(root)
    previous = status.load_last_recv_ms()
    rec = Recorder(root, clock=clock, fetch_snapshot=fetch_snapshot)
    rec.last_recv_ms = {"depth": previous, "trades": previous}  # restart gap from the previous run
    started = clock()

    def until() -> bool:
        return stop_after is not None and clock() - started >= stop_after

    def heartbeat(state: str) -> None:
        free = disk_free(root)
        last = max((v for v in rec.last_recv_ms.values() if v is not None), default=previous)
        status.write({"state": state, "pid": os.getpid(), "symbol": SYMBOL, "updated_ms": int(clock() * 1000),
                      "last_recv_ms": last, "book_valid": rec.sync.valid, "free_bytes": free,
                      "counts": rec.counts})
        if free < min_free_bytes:
            raise StorageError(f"free space {free} below {min_free_bytes}")

    async def beat() -> None:
        while not until():
            await sleep(HEARTBEAT_SECONDS)
            rec.writer.flush()
            heartbeat("running")

    try:
        heartbeat("starting")
        tasks = [asyncio.create_task(_stream(rec, "depth", DEPTH_URL, connect, until, sleep)),
                 asyncio.create_task(_stream(rec, "trades", TRADE_URL, connect, until, sleep)),
                 asyncio.create_task(beat())]
        try:
            await asyncio.gather(*tasks)
        finally:
            for t in tasks:
                t.cancel()
        rec.writer.close()
        heartbeat("stopped")
    except StorageError as exc:
        try:
            status.write({"state": "failed", "error": str(exc), "updated_ms": int(clock() * 1000),
                          "counts": rec.counts})
        except StorageError:
            pass
        raise
    finally:
        try:
            rec.writer.close()
        except StorageError:
            pass
    return rec.counts
