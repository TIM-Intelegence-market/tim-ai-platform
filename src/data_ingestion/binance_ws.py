from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

import websockets

from src.models.market_data import Trade

log = logging.getLogger(__name__)
TradeHandler = Callable[[Trade], Awaitable[None]]


class BinanceTradeStream:
    """Public Binance aggregate-trade stream. It has no authenticated endpoints."""

    def __init__(self, base_url: str, symbol: str, handler: TradeHandler) -> None:
        self.url = f"{base_url.rstrip('/')}/{symbol.lower()}@aggTrade"
        self.symbol = symbol.upper()
        self.handler = handler
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def parse_message(raw: str) -> Trade:
        payload = json.loads(raw)
        if payload.get("e") != "aggTrade":
            raise ValueError("Unexpected Binance event type")
        return Trade(symbol=str(payload["s"]).upper(), price=float(payload["p"]), quantity=float(payload["q"]), event_time=datetime.fromtimestamp(int(payload["T"]) / 1000, tz=timezone.utc), trade_id=int(payload["a"]), buyer_is_maker=bool(payload["m"]))

    async def run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20, close_timeout=5, max_queue=2048) as socket:
                    attempt = 0
                    async for raw in socket:
                        if self._stop.is_set():
                            break
                        try:
                            await self.handler(self.parse_message(raw))
                        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                            log.warning("Malformed Binance message skipped: %s", exc)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempt += 1
                delay = min(30.0, 2 ** min(attempt, 5)) + random.random()
                log.warning("Binance public stream disconnected (%s); retrying in %.1fs", exc, delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except TimeoutError:
                    pass
