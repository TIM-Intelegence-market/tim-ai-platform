"""One public stream per symbol, supervised in isolation.

Each symbol reuses the existing ``BinanceTradeStream`` (own socket, own
watchdog, own buffer limit, own catch-up before resume). Binance allows many
connections per IP; three sockets keep reconnect, recovery and backpressure of
one symbol independent from the others. A stream that fails fatally is
restarted with backoff up to ``max_restarts``; afterwards only that symbol is
marked FAILED and the remaining symbols keep running.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Protocol

from src.multi_symbol.backpressure import SymbolMetrics

log = logging.getLogger("tim.multi_symbol")

RUNNING = "RUNNING"
RESTARTING = "RESTARTING"
FAILED = "FAILED"
STOPPED = "STOPPED"


class StreamLike(Protocol):
    async def run(self) -> None: ...

    def stop(self) -> None: ...


StreamFactory = Callable[[str], StreamLike]


class MultiSymbolStreamSet:
    def __init__(
        self,
        symbols: Iterable[str],
        factory: StreamFactory,
        *,
        max_restarts: int = 5,
        backoff: Callable[[int], float] = lambda attempt: min(30.0, 2.0 ** attempt),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        metrics: SymbolMetrics | None = None,
    ) -> None:
        self.symbols = tuple(symbols)
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        self.factory = factory
        self.max_restarts = max_restarts
        self.backoff = backoff
        self.sleep = sleep
        self.metrics = metrics or SymbolMetrics()
        self.state: dict[str, str] = {symbol: STOPPED for symbol in self.symbols}
        self._streams: dict[str, StreamLike] = {}
        self._stopping = False

    async def _supervise(self, symbol: str) -> None:
        restarts = 0
        while not self._stopping:
            stream = self.factory(symbol)
            self._streams[symbol] = stream
            self.state[symbol] = RUNNING
            try:
                await stream.run()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # fatal for this symbol's stream only
                self.metrics.increment(symbol, "stream_fatal_total")
                if self._stopping:
                    break
                restarts += 1
                if restarts > self.max_restarts:
                    self.state[symbol] = FAILED
                    log.error("%s stream failed permanently: %s", symbol, type(error).__name__)
                    return
                self.state[symbol] = RESTARTING
                self.metrics.increment(symbol, "stream_restart_total")
                await self.sleep(self.backoff(restarts))
                continue
            break  # run() returned normally: stop was requested
        self.state[symbol] = STOPPED

    async def run(self) -> dict[str, str]:
        """Run all symbols until stop() or until every symbol has failed."""
        tasks = [asyncio.create_task(self._supervise(symbol), name=f"stream:{symbol}") for symbol in self.symbols]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
        return dict(self.state)

    def stop(self) -> None:
        self._stopping = True
        for stream in self._streams.values():
            stream.stop()
