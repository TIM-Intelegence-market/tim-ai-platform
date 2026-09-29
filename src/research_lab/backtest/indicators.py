"""Causal indicators computed on a History view (only closed bars up to now)."""
from __future__ import annotations

from collections.abc import Sequence

from src.research_lab.data.parse import Kline


def sma_close(history: Sequence[Kline], n: int) -> float | None:
    if len(history) < n:
        return None
    return sum(bar.close for bar in history[len(history) - n:]) / n


def atr(history: Sequence[Kline], n: int = 14) -> float | None:
    """Simple average of the true range over the last n closed bars."""
    if len(history) < n + 1:
        return None
    bars = history[len(history) - n - 1:]
    ranges = [
        max(bar.high - bar.low, abs(bar.high - prev.close), abs(bar.low - prev.close))
        for prev, bar in zip(bars, bars[1:])
    ]
    return sum(ranges) / n
