"""Binance USD-M perpetual order book recorder (public, no API key, no orders).

There is no free history of the full order book, so heatmap, iceberg or spoofing rules can only be studied on a
book we record ourselves from now on. This records the public diff-depth stream ``<symbol>@depth@100ms`` (every
change of every level, 100 ms batches) plus a REST snapshot (``/fapi/v1/depth``, ``snapshot_limit`` levels per side)
on every connect and every ``snapshot_every`` seconds. :mod:`.book` rebuilds the book from these rows with the
update-id chain Binance documents (first event ``U <= lastUpdateId <= u``, then ``pu`` = previous ``u``); a broken
chain waits for the next snapshot instead of guessing.

Storage, safety and health are the Bitunix recorder's (PR #226): one gzip JSONL segment per UTC day, symbol and run
(``<root>/<symbol>/<YYYY-MM-DD>.<run_start_ms>.jsonl.gz``), symbol allowlist, paths inside ``root``, storage
errors fatal (``status: failed``, non-zero exit), ``status.json`` heartbeat, ``gap`` rows on reconnect and restart.
Rows: ``{"kind": "depth", "recv_ms", "msg"}`` (the stream's ``data``), ``{"kind": "snapshot", "recv_ms", "msg"}``
and ``{"kind": "gap", "from_ms", "to_ms"}``.

    python -m src.research_lab.orderbook record --root ~/Documents/TIM/orderbook/binance [--symbols BTCUSDT] [--seconds 600]
    python -m src.research_lab.orderbook check --root ~/Documents/TIM/orderbook/binance --symbol BTCUSDT
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import Path

from src.research_lab.bitunix.recorder import DayWriter, Status, StorageError, free_bytes, validate_symbols

WS_BASE = "wss://fstream.binance.com/stream?streams="
REST_DEPTH = "https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit={limit}"
SNAPSHOT_LIMITS = (5, 10, 20, 50, 100, 500, 1000)
SNAPSHOT_EVERY = 600.0   # seconds; weight 20 per 1000-level snapshot, far below the 2400/min limit
FLUSH_EVERY = 5.0
MIN_FREE_BYTES = 5 * 1024**3


def stream_url(symbols: Iterable[str]) -> str:
    return WS_BASE + "/".join(f"{s.lower()}@depth@100ms" for s in symbols)


def fetch_snapshot(symbol: str, limit: int = 1000, timeout: float = 10.0) -> dict:
    """REST depth snapshot (public). Network errors propagate to the caller, which retries later."""
    with urllib.request.urlopen(REST_DEPTH.format(symbol=symbol, limit=limit), timeout=timeout) as resp:  # noqa: S310 - fixed https host
        return json.loads(resp.read())


def handle(raw: str | bytes, writer: DayWriter, recv_ms: int) -> str | None:
    """Store one combined-stream message. ``"depth"``, ``"rejected"`` (foreign symbol) or None (anything else)."""
    try:
        msg = json.loads(raw)
    except (TypeError, ValueError):
        return None
    data = msg.get("data") if isinstance(msg, dict) else None
    if not isinstance(data, dict) or data.get("e") != "depthUpdate":
        return None
    symbol = data.get("s")
    if not isinstance(symbol, str) or symbol not in writer.allowed:
        return "rejected"
    writer.write(symbol, {"kind": "depth", "recv_ms": recv_ms, "msg": data}, recv_ms)
    return "depth"


async def record(
    root: Path, symbols: list[str], *, stop_after: float | None = None, connect: Callable | None = None,
    snapshot: Callable[[str, int], dict] = fetch_snapshot, snapshot_limit: int = 1000,
    snapshot_every: float = SNAPSHOT_EVERY, clock: Callable[[], float] = time.time,
    min_free_bytes: int = MIN_FREE_BYTES, disk_free: Callable[[Path], int] = free_bytes,
) -> dict[str, int]:
    """Record until cancelled (or ``stop_after`` seconds). Network errors reconnect; StorageError propagates."""
    if snapshot_limit not in SNAPSHOT_LIMITS:
        raise ValueError(f"snapshot_limit must be one of {SNAPSHOT_LIMITS}")
    if connect is None:
        import websockets

        connect = websockets.connect
    symbols = list(validate_symbols(symbols))
    root.mkdir(parents=True, exist_ok=True)
    status = Status(root)
    writer = DayWriter(root, symbols, run_id=int(clock() * 1000))
    counts = {"depth": 0, "snapshot": 0, "snapshot_errors": 0, "rejected": 0, "gaps": 0, "reconnects": 0}
    started = clock()
    backoff = 1.0
    last_ok_ms = status.load_last_recv_ms()

    def running() -> bool:
        return stop_after is None or clock() - started < stop_after

    def heartbeat(state: str) -> None:
        free = disk_free(root)
        status.write({"state": state, "pid": os.getpid(), "symbols": symbols, "feed": "binance-usdm-depth@100ms",
                      "updated_ms": int(clock() * 1000), "last_recv_ms": last_ok_ms, "free_bytes": free,
                      "counts": counts})
        if free < min_free_bytes:
            raise StorageError(f"free space {free} below {min_free_bytes}")

    async def take_snapshots() -> bool:
        ok = True
        for s in symbols:
            try:
                snap = await asyncio.to_thread(snapshot, s, snapshot_limit)
            except Exception as exc:  # noqa: BLE001 - network/HTTP; the book waits for the next snapshot
                counts["snapshot_errors"] += 1
                print(f"orderbook recorder: snapshot {s} failed: {type(exc).__name__}: {exc}", flush=True)
                ok = False
                continue
            if not isinstance(snap, dict) or "lastUpdateId" not in snap:
                counts["snapshot_errors"] += 1
                ok = False
                continue
            now_ms = int(clock() * 1000)
            writer.write(s, {"kind": "snapshot", "recv_ms": now_ms, "msg": snap}, now_ms)
            counts["snapshot"] += 1
        return ok

    try:
        heartbeat("starting")
        while running():
            try:
                async with connect(stream_url(symbols), max_size=2**24) as ws:
                    now_ms = int(clock() * 1000)
                    if last_ok_ms is not None:
                        for s in symbols:
                            writer.write(s, {"kind": "gap", "from_ms": last_ok_ms, "to_ms": now_ms}, now_ms)
                        counts["gaps"] += 1
                    backoff = 1.0
                    # first events must be on the wire before the snapshot so the chain can start (Binance docs)
                    next_snapshot = clock() + 1.0
                    next_flush = clock() + FLUSH_EVERY
                    while running():
                        timeout = max(0.1, min(next_flush, next_snapshot) - clock())
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                        except asyncio.TimeoutError:
                            raw = None
                        if raw is not None:
                            recv_ms = int(clock() * 1000)
                            ch = handle(raw, writer, recv_ms)
                            if ch:
                                counts[ch] += 1
                                if ch == "depth":
                                    last_ok_ms = recv_ms
                        if clock() >= next_snapshot:
                            ok = await take_snapshots()
                            next_snapshot = clock() + (snapshot_every if ok else 60.0)
                        if clock() >= next_flush:
                            writer.flush()
                            heartbeat("running")
                            next_flush = clock() + FLUSH_EVERY
            except StorageError:
                raise
            except Exception as exc:  # noqa: BLE001 - network side; storage re-raised above
                counts["reconnects"] += 1
                print(f"orderbook recorder: reconnect after {type(exc).__name__}: {exc}", flush=True)
            if not running():
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
