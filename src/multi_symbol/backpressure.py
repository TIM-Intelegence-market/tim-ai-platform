"""Bounded per-symbol buffers with per-symbol metrics.

A full buffer of one symbol raises for that symbol only; the other symbols keep
accepting. Nothing is dropped silently: the caller must treat the error like a
stream backpressure failure (reconnect plus catch-up for that symbol).
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable


class SymbolBackpressure(ConnectionError):
    def __init__(self, symbol: str, limit: int) -> None:
        super().__init__(f"{symbol}: buffer limit {limit} reached")
        self.symbol = symbol
        self.limit = limit


class SymbolMetrics:
    """Counters and gauges labelled by symbol (``ingestion_metrics`` has no symbol column)."""

    def __init__(self) -> None:
        self.counters: Counter[tuple[str, str]] = Counter()
        self.gauges: dict[tuple[str, str], float] = {}

    def increment(self, symbol: str, name: str, value: int = 1) -> None:
        self.counters[(symbol, name)] += value

    def gauge(self, symbol: str, name: str, value: float) -> None:
        self.gauges[(symbol, name)] = value

    def as_rows(self) -> list[dict[str, object]]:
        """Rows in the shape of ``ingestion_metrics`` with the symbol in metadata."""
        rows: list[dict[str, object]] = [
            {"metric_name": name, "metric_value": float(value), "metadata": {"symbol": symbol}}
            for (symbol, name), value in sorted(self.counters.items())
        ]
        rows.extend(
            {"metric_name": name, "metric_value": float(value), "metadata": {"symbol": symbol}}
            for (symbol, name), value in sorted(self.gauges.items())
        )
        return rows


class SymbolBuffers:
    def __init__(self, symbols: Iterable[str], limit: int, metrics: SymbolMetrics | None = None) -> None:
        if limit < 1:
            raise ValueError("limit must be positive")
        self.limit = limit
        self.metrics = metrics or SymbolMetrics()
        self._queues: dict[str, deque[object]] = {symbol: deque() for symbol in symbols}

    def put(self, symbol: str, item: object) -> None:
        queue = self._queue(symbol)
        if len(queue) >= self.limit:
            self.metrics.increment(symbol, "backpressure_total")
            raise SymbolBackpressure(symbol, self.limit)
        queue.append(item)
        self.metrics.gauge(symbol, "buffer_depth", len(queue))

    def take(self, symbol: str) -> object | None:
        queue = self._queue(symbol)
        item = queue.popleft() if queue else None
        self.metrics.gauge(symbol, "buffer_depth", len(queue))
        return item

    def depth(self, symbol: str) -> int:
        return len(self._queue(symbol))

    def reset(self, symbol: str) -> int:
        """Drop one symbol's buffer after backpressure; recovery refills it from the exchange."""
        queue = self._queue(symbol)
        dropped = len(queue)
        queue.clear()
        self.metrics.gauge(symbol, "buffer_depth", 0)
        return dropped

    def _queue(self, symbol: str) -> deque[object]:
        try:
            return self._queues[symbol]
        except KeyError as error:
            raise ValueError(f"symbol not configured: {symbol}") from error
