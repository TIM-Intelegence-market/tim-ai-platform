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
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/{symbol.lower()}@aggTrade"
        self.symbol = symbol.upper()
        self.handler = handler
        self.stream_event_handler = stream_event_handler
        self.recovery_handler = recovery_handler
        self.recovery_on_connect = recovery_on_connect
        self._stop = asyncio.Event()

    def stop(self) -> None:
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
                await self.stream_event_handler(name, fields)
            except Exception as error:
                log.warning("Stream event metric handler unavailable (%s): %s", name, type(error).__name__)

    async def run(self) -> None:
        attempt = 0
        needs_recovery = self.recovery_on_connect
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20, close_timeout=5, max_queue=2048) as socket:
                    attempt = 0
                    await self._event("CONNECTED", recovery_required=needs_recovery)
                    async for raw in socket:
                        if self._stop.is_set():
                            break
                        try:
                            trade = self.parse_message(raw)
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                            log.warning("Malformed Binance message skipped: %s", exc)
                            await self._event("PARSE_ERROR", error_type=type(exc).__name__)
                            continue
                        if trade.symbol != self.symbol:
                            log.warning("Mismatched Binance symbol skipped: %s", trade.symbol)
                            await self._event("PARSE_ERROR", error_type="SYMBOL_MISMATCH")
                            continue
                        if needs_recovery and self.recovery_handler is not None:
                            await self.recovery_handler(trade)
                            needs_recovery = False
                            await self._event("RECOVERY_COMPLETE", next_live_trade_id=trade.trade_id)
                        await self.handler(trade)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                needs_recovery = True
                delay = min(30.0, 2 ** min(attempt, 5)) + random.random()
                log.warning("Binance public stream disconnected (%s); retrying in %.1fs", exc, delay)
                await self._event(
                    "DISCONNECTED", attempt=attempt, delay_seconds=delay, error_type=type(exc).__name__
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
