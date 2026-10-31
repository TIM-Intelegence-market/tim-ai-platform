"""Websocket loops that only record public liquidation messages (S12, package L1).

No account, no key, no orders. Every message is stored unchanged (``store``); parsing happens
later. A ``connect`` record opens each session. Every 60 s the collector sends a websocket ping
and writes ``alive`` only after the pong arrived (within 10 s); a missing pong ends the session.
Every end (error, clean close, stop) writes a ``disconnect`` record, a failed attempt writes
``connect_failed``. A failing disk never ends a feed for good: the venue loop logs and retries.

Endpoints as documented on 31.10.2026 (re-check before version 1.0, pre-registration section 9):

- Binance USD-M: ``wss://fstream.binance.com/market/ws/btcusdt@forceOrder`` (1000 ms snapshot).
- Bybit V5 linear: ``wss://stream.bybit.com/v5/public/linear``, topic ``allLiquidation.BTCUSDT``;
  Bybit expects a client ``{"op": "ping"}`` about every 20 s.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import events, store

log = logging.getLogger(__name__)

SYMBOL = "BTCUSDT"
MAX_BACKOFF_SECONDS = 60.0
MAX_MESSAGE_BYTES = 1 << 20
PONG_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class Venue:
    name: str
    url: str
    subscribe: dict[str, Any] | None = None
    client_ping: dict[str, Any] | None = None
    client_ping_seconds: float = 20.0


VENUES = {
    events.BINANCE: Venue(events.BINANCE, f"wss://fstream.binance.com/market/ws/{SYMBOL.lower()}@forceOrder"),
    events.BYBIT: Venue(events.BYBIT, "wss://stream.bybit.com/v5/public/linear",
                        subscribe={"op": "subscribe", "args": [f"allLiquidation.{SYMBOL}"]},
                        client_ping={"op": "ping"}),
}

Connect = Callable[[str], Any]  # returns an async context manager yielding a websocket


def _default_connect(url: str) -> Any:
    from websockets.asyncio.client import connect

    return connect(url, ping_interval=20, ping_timeout=20, open_timeout=15, close_timeout=5,
                   max_size=MAX_MESSAGE_BYTES)


class Recorder:
    """Writes the records of one venue; the clock is injectable for tests."""

    def __init__(self, root: Path, venue: str, now_ns: Callable[[], int] = time.time_ns,
                 mono_ns: Callable[[], int] = time.monotonic_ns) -> None:
        self.root, self.venue, self.now_ns, self.mono_ns = root, venue, now_ns, mono_ns
        self.parse_errors = 0

    def write(self, kind: str, session_id: str, payload: str | None = None, note: str | None = None) -> None:
        store.append(self.root, store.make_record(kind, self.venue, session_id, self.now_ns(), self.mono_ns(),
                                                  payload=payload, note=note))

    def message(self, session_id: str, text: str) -> None:
        """Store the raw text first, then only check that it parses (never drop a message).

        A rejected Bybit subscription (``"success": false``) ends the session, so that a socket
        without data is not counted as a covered feed.
        """
        self.write("message", session_id, payload=text)
        try:
            data = json.loads(text)
            if isinstance(data, dict) and data.get("success") is False:
                raise SubscriptionRejected(str(data.get("ret_msg") or data)[:200])
            events.PARSERS[self.venue](data)
        except (ValueError, events.EventFormatError) as exc:
            self.parse_errors += 1
            log.warning("%s: message does not parse: %s", self.venue, exc)


class SubscriptionRejected(ConnectionError):
    """The venue refused the subscription."""


async def _every(seconds: float, action: Callable[[], Awaitable[None] | None]) -> None:
    while True:
        await asyncio.sleep(seconds)
        result = action()
        if asyncio.iscoroutine(result):
            await result


async def _alive(ws: Any, recorder: Recorder, session_id: str, seconds: float) -> None:
    """Ping, wait for the pong, then write ``alive``; a missing pong closes the socket."""
    while True:
        await asyncio.sleep(seconds)
        try:
            waiter = await ws.ping()
            await asyncio.wait_for(waiter, timeout=PONG_TIMEOUT_SECONDS)
        except Exception:  # noqa: BLE001 - no pong: no proof of life, end the session
            await ws.close()
            return
        recorder.write("alive", session_id)


async def run_session(venue: Venue, recorder: Recorder, connect: Connect = _default_connect,
                      alive_seconds: float = store.ALIVE_SECONDS) -> None:
    """One connection: record until the socket ends. Always writes connect and disconnect."""
    session_id = str(uuid.uuid4())
    opened = False
    note = "closed by server"
    try:
        async with connect(venue.url) as ws:
            opened = True
            recorder.write("connect", session_id, note=venue.url)
            helpers = [asyncio.create_task(_alive(ws, recorder, session_id, alive_seconds))]
            if venue.client_ping:
                ping = json.dumps(venue.client_ping)
                helpers.append(asyncio.create_task(_every(venue.client_ping_seconds, lambda: ws.send(ping))))
            try:
                if venue.subscribe:
                    await ws.send(json.dumps(venue.subscribe))
                async for text in ws:
                    if isinstance(text, bytes):
                        text = text.decode("utf-8")
                    recorder.message(session_id, text)
            finally:
                for task in helpers:
                    task.cancel()
                await asyncio.gather(*helpers, return_exceptions=True)
    except asyncio.CancelledError:
        note = "stopped"
        raise
    except Exception as exc:  # noqa: BLE001 - every loss ends in a disconnect record
        note = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        try:
            recorder.write("disconnect" if opened else "connect_failed", session_id, note=note)
        except OSError as exc:
            log.error("%s: could not write the end of session %s: %s", venue.name, session_id, exc)
        if not opened:
            log.warning("%s: connection failed: %s", venue.name, note)


async def run_venue(venue: Venue, root: Path, connect: Connect = _default_connect,
                    stop: asyncio.Event | None = None) -> None:
    """Reconnect forever with growing backoff (reset after a session that lasted a minute)."""
    stop = stop or asyncio.Event()
    recorder = Recorder(root, venue.name)
    backoff = 1.0
    while not stop.is_set():
        started = time.monotonic()
        try:
            await run_session(venue, recorder, connect)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - e.g. disk full: log, back off, try again
            log.error("%s: session failed: %s", venue.name, exc)
        if time.monotonic() - started > 60:
            backoff = 1.0
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
