from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone

import websockets

from src.models.market_data import Trade

log = logging.getLogger(__name__)
TradeHandler = Callable[[Trade], Awaitable[None]]
StreamEventHandler = Callable[[str, Mapping[str, object]], Awaitable[None]]
RecoveryHandler = Callable[[Trade], Awaitable[None]]

MAX_BACKOFF_SECONDS = 30.0
EVENT_TIMEOUT_SECONDS = 10.0
SESSION_CLEANUP_SECONDS = 10.0


class StreamClosed(ConnectionError):
    """The server ended the stream cleanly (close code 1000/1001 or none).

    websockets ends iteration without raising in that case, so run() raises this
    to send a clean close through the same disconnect path as any other loss:
    backoff, DISCONNECTED telemetry and catch-up before the next live trade.
    """


class StreamStalled(ConnectionError):
    """The socket stayed open but delivered no market data (watchdog)."""


class StreamBackpressure(ConnectionError):
    """Processing fell so far behind that the local buffer reached its limit."""


class RecoveryTimeout(TimeoutError):
    """Catch-up before the first live trade did not finish in time.

    Progress is durable (the cursor advances per persisted trade), so the next
    connection continues where this one stopped.
    """


class HandlerTimeout(TimeoutError):
    """Persisting one live trade did not finish in time."""


class _End:
    """Queue sentinel: the reader stopped; carries the reason."""

    __slots__ = ("error",)

    def __init__(self, error: BaseException) -> None:
        self.error = error


class BinanceTradeStream:
    """Public Binance aggregate-trade stream. It has no authenticated endpoints."""

    def __init__(
        self,
        base_url: str,
        symbol: str,
        handler: TradeHandler,
        *,
        stream_event_handler: StreamEventHandler | None = None,
        recovery_handler: RecoveryHandler | None = None,
        recovery_on_connect: bool = False,
        recovery_timeout: float = 300.0,
        handler_timeout: float = 120.0,
        stale_after: float = 60.0,
        stable_after: float = 60.0,
        buffer_limit: int = 100_000,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/{symbol.lower()}@aggTrade"
        self.symbol = symbol.upper()
        self.handler = handler
        self.stream_event_handler = stream_event_handler
        self.recovery_handler = recovery_handler
        self.recovery_on_connect = recovery_on_connect
        self.recovery_timeout = recovery_timeout
        self.handler_timeout = handler_timeout
        self.stale_after = stale_after
        self.stable_after = stable_after
        self.buffer_limit = buffer_limit
        self.ping_interval = 20.0
        self.ping_timeout = 20.0
        self._stop = asyncio.Event()
        self._needs_recovery = recovery_on_connect
        self._healthy_since: float | None = None
        self._last_message_at = 0.0

    def stop(self) -> None:
        """Request shutdown; run() returns promptly even mid-catch-up."""
        self._stop.set()

    @staticmethod
    def parse_message(raw: str) -> Trade:
        payload = json.loads(raw)
        if payload.get("e") != "aggTrade":
            raise ValueError("Unexpected Binance event type")
        if not isinstance(payload.get("m"), bool):
            raise ValueError("buyer_is_maker must be a boolean")
        if isinstance(payload.get("a"), bool) or isinstance(payload.get("T"), bool):
            raise ValueError("aggregate identity and event time must be integers")
        symbol = payload.get("s")
        if not isinstance(symbol, str) or not symbol.isalnum() or not 3 <= len(symbol) <= 20:
            raise ValueError("Invalid Binance symbol")
        return Trade(symbol=symbol.upper(), price=float(payload["p"]), quantity=float(payload["q"]), event_time=datetime.fromtimestamp(int(payload["T"]) / 1000, tz=timezone.utc), trade_id=int(payload["a"]), buyer_is_maker=payload["m"])

    async def _event(self, name: str, **fields: object) -> None:
        if self.stream_event_handler is not None:
            try:
                # Telemetry writes to the database; a hung pool must never
                # freeze the reconnect path that emits DISCONNECTED.
                async with asyncio.timeout(EVENT_TIMEOUT_SECONDS):
                    await self.stream_event_handler(name, fields)
            except Exception as error:
                log.warning("Stream event metric handler unavailable (%s): %s", name, type(error).__name__)

    async def _wait_for_stop(self, delay: float) -> None:
        """Backoff sleep that returns early when stop() is requested."""
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except TimeoutError:
            pass

    async def _read(self, socket, queue: asyncio.Queue) -> None:
        """Drain the socket into the local buffer and never await processing.

        websockets pauses the TCP transport once ``max_queue`` frames are
        unread, which also stops pong frames: a reader blocked behind a long
        catch-up therefore ends in "keepalive ping timeout". Reading here
        keeps the connection alive while recovery runs.
        """
        loop = asyncio.get_running_loop()
        try:
            async for raw in socket:
                self._last_message_at = loop.time()
                if queue.qsize() >= self.buffer_limit:
                    raise StreamBackpressure(
                        f"{queue.qsize()} unprocessed messages buffered; dropping the connection"
                    )
                queue.put_nowait(raw)
            end: BaseException = StreamClosed(
                f"server closed the stream (code {getattr(socket, 'close_code', None)})"
            )
        except StreamBackpressure:
            raise
        except Exception as exc:
            end = exc
        # Messages already received are still processed before the session ends.
        queue.put_nowait(_End(end))

    async def _process(self, queue: asyncio.Queue) -> None:
        loop = asyncio.get_running_loop()
        while True:
            item = await queue.get()
            if self._stop.is_set():
                return
            if isinstance(item, _End):
                raise item.error
            try:
                trade = self.parse_message(item)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                log.warning("Malformed Binance message skipped: %s", exc)
                await self._event("PARSE_ERROR", error_type=type(exc).__name__)
                continue
            if trade.symbol != self.symbol:
                log.warning("Mismatched Binance symbol skipped: %s", trade.symbol)
                await self._event("PARSE_ERROR", error_type="SYMBOL_MISMATCH")
                continue
            if self._needs_recovery and self.recovery_handler is not None:
                try:
                    async with asyncio.timeout(self.recovery_timeout):
                        await self.recovery_handler(trade)
                except TimeoutError:
                    raise RecoveryTimeout(
                        f"catch-up before trade {trade.trade_id} exceeded {self.recovery_timeout:.0f}s"
                    ) from None
                self._needs_recovery = False
                await self._event("RECOVERY_COMPLETE", next_live_trade_id=trade.trade_id)
            try:
                async with asyncio.timeout(self.handler_timeout):
                    await self.handler(trade)
            except TimeoutError:
                raise HandlerTimeout(
                    f"trade handler for {trade.trade_id} exceeded {self.handler_timeout:.0f}s"
                ) from None
            if self._healthy_since is None:
                self._healthy_since = loop.time()

    async def _watchdog(self) -> None:
        """End the session when the socket delivers no market data at all."""
        loop = asyncio.get_running_loop()
        interval = max(0.05, min(5.0, self.stale_after / 4))
        while True:
            await asyncio.sleep(interval)
            silent = loop.time() - self._last_message_at
            if silent > self.stale_after:
                raise StreamStalled(f"no market data for {silent:.0f}s")

    async def _session(self, socket) -> None:
        """Run one connection until it fails, stalls or stop() is requested."""
        loop = asyncio.get_running_loop()
        self._last_message_at = loop.time()
        queue: asyncio.Queue = asyncio.Queue()
        reader = asyncio.create_task(self._read(socket, queue), name="binance-ws-reader")
        processor = asyncio.create_task(self._process(queue), name="binance-ws-processor")
        watchdog = asyncio.create_task(self._watchdog(), name="binance-ws-watchdog")
        stopper = asyncio.create_task(self._stop.wait(), name="binance-ws-stop")
        tasks = {reader, processor, watchdog, stopper}
        pending = set(tasks)
        failure: BaseException | None = None
        try:
            while failure is None and not self._stop.is_set():
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task is stopper or task.cancelled():
                        continue
                    error = task.exception()
                    if error is not None and failure is None:
                        failure = error
                if processor in done and failure is None and not self._stop.is_set():
                    failure = StreamClosed("trade processor ended unexpectedly")
        finally:
            for task in tasks:
                task.cancel()
            # Bounded: a cancelled catch-up may still record its gap as OPEN,
            # but shutdown must stay inside systemd's TimeoutStopSec.
            await asyncio.wait(tasks, timeout=SESSION_CLEANUP_SECONDS)
            for task in tasks:
                if task.done() and not task.cancelled():
                    task.exception()  # mark retrieved
        if failure is not None and not self._stop.is_set():
            raise failure

    async def run(self) -> None:
        attempt = 0
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            self._healthy_since = None
            try:
                async with websockets.connect(
                    self.url, ping_interval=self.ping_interval, ping_timeout=self.ping_timeout, close_timeout=5,
                    open_timeout=10, max_queue=2048,
                ) as socket:
                    await self._event("CONNECTED", recovery_required=self._needs_recovery)
                    await self._session(socket)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop.is_set():
                    break
                # Only a connection that delivered live trades for a while
                # resets the backoff; a reconnect loop keeps growing it.
                if (
                    self._healthy_since is not None
                    and loop.time() - self._healthy_since >= self.stable_after
                ):
                    attempt = 0
                attempt += 1
                self._needs_recovery = True
                delay = min(MAX_BACKOFF_SECONDS, 2 ** min(attempt, 5)) + random.random()
                log.warning("Binance public stream disconnected (%s); retrying in %.1fs", exc, delay)
                await self._event(
                    "DISCONNECTED", attempt=attempt, delay_seconds=delay, error_type=type(exc).__name__
                )
                await self._wait_for_stop(delay)
