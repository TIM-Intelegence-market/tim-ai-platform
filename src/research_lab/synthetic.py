"""Synthetic bar series for testing the engine and the statistical guard.

A marker bar has an unusually high taker-buy share. With edge > 0 the bars
after a marker drift upwards, which a marker strategy should find; with
edge = 0 the series is a pure random walk and nothing should be found.
"""
from __future__ import annotations

import math
import random

from src.research_lab.data.parse import Kline

MARKER_SHARE = 0.95


def synthetic_series(
    n: int,
    *,
    seed: int,
    start_ms: int = 1_514_764_800_000,  # 2018-01-01
    interval_ms: int = 3_600_000,
    volatility: float = 0.01,
    marker_rate: float = 0.05,
    edge: float = 0.0,
    edge_bars: int = 3,
) -> list[Kline]:
    rng = random.Random(seed)
    price = 10_000.0
    drift_left = 0
    bars = []
    for i in range(n):
        mean = edge * volatility if drift_left > 0 else 0.0
        drift_left = max(drift_left - 1, 0)
        open_ = price
        close = open_ * math.exp(rng.gauss(mean, volatility))
        high = max(open_, close) * (1 + abs(rng.gauss(0, volatility / 2)))
        low = min(open_, close) * (1 - abs(rng.gauss(0, volatility / 2)))
        volume = 100.0
        marker = rng.random() < marker_rate
        share = MARKER_SHARE if marker else rng.uniform(0.3, 0.7)
        if marker:
            drift_left = edge_bars
        open_time = start_ms + i * interval_ms
        bars.append(Kline(open_time, open_, high, low, close, volume, open_time + interval_ms - 1, share * volume))
        price = close
    return bars


def marker_strategy(stop_atr: float = 1.0, target_r: float = 1.0, time_stop_bars: int = 3):
    """Long after a marker bar; the reference strategy for synthetic tests."""
    from src.research_lab.backtest.engine import Signal
    from src.research_lab.backtest.indicators import atr

    def strategy(history):
        bar = history[-1]
        if bar.volume <= 0 or bar.taker_buy_volume / bar.volume < 0.9:
            return None
        width = atr(history, 14)
        if width is None:
            return None
        return Signal(1, bar.close - stop_atr * width, target_r=target_r, time_stop_bars=time_stop_bars)

    return strategy
