"""Candles of a fixed time frame built from S8 minute bars, and the UTC session map.

Prices in USDT (float), volumes in sats (int). A candle is "closed" once the minute bar of its
last minute has been consumed; nothing here looks at later minutes.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.research_lab.of2.config import DAY_MS, HOUR_MS, MINUTE_MS, Config
from src.research_lab.orderflow_ml.bars import E8, MinuteBar


@dataclass(frozen=True, slots=True)
class Candle:
    start: int
    minutes: int
    trades: int
    open: float
    high: float
    low: float
    close: float
    volume: int   # buy + sell, sats
    delta: int    # buy - sell, sats (aggressor side)

    @property
    def has_trades(self) -> bool:
        return self.trades > 0

    @property
    def end(self) -> int:
        return self.start + self.minutes * MINUTE_MS

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


def candle_from_bars(bars: Sequence[MinuteBar], start: int, minutes: int) -> Candle:
    """Aggregate ``minutes`` consecutive minute bars starting at ``start``."""
    if len(bars) != minutes or bars[0].window_start_ms != start:
        raise ValueError("bars do not cover the candle window")
    traded = [b for b in bars if b.has_trades]
    if not traded:
        return Candle(start, minutes, 0, 0.0, 0.0, 0.0, 0.0, 0, 0)
    return Candle(
        start, minutes, sum(b.trade_count for b in traded),
        traded[0].first_price_e8 / E8, max(b.high_price_e8 for b in traded) / E8,
        min(b.low_price_e8 for b in traded) / E8, traded[-1].last_price_e8 / E8,
        sum(b.buy_sats + b.sell_sats for b in traded), sum(b.buy_sats - b.sell_sats for b in traded),
    )


class CandleBuilder:
    """Collects minute bars and emits a closed candle every ``minutes`` minutes (aligned to the UTC day)."""

    def __init__(self, minutes: int) -> None:
        if minutes <= 0 or (DAY_MS // MINUTE_MS) % minutes:
            raise ValueError("time frame must divide the day")
        self.minutes = minutes
        self._pending: list[MinuteBar] = []

    def push(self, bar: MinuteBar) -> Candle | None:
        self._pending.append(bar)
        if (bar.window_start_ms // MINUTE_MS + 1) % self.minutes == 0:
            start = self._pending[0].window_start_ms
            if len(self._pending) != self.minutes:
                # A stream that starts mid-candle: discard the partial candle rather than invent one.
                self._pending = []
                return None
            candle = candle_from_bars(self._pending, start, self.minutes)
            self._pending = []
            return candle
        return None


def relative_volume(history: Sequence[Candle], candle: Candle, bars: int) -> float | None:
    """R18: candle volume divided by the mean volume of the previous ``bars`` candles (None if too few)."""
    past = [c.volume for c in history[-bars:] if c.has_trades]
    if len(past) < bars:
        return None
    mean = sum(past) / len(past)
    return candle.volume / mean if mean > 0 else None


def session_of(time_ms: int, cfg: Config) -> str:
    hour = (time_ms % DAY_MS) // HOUR_MS
    for name, lo, hi in cfg.sessions:
        if lo <= hour < hi:
            return name
    raise ValueError("sessions do not cover the day")


def session_start(time_ms: int, cfg: Config) -> int:
    day = time_ms - time_ms % DAY_MS
    hour = (time_ms % DAY_MS) // HOUR_MS
    for _, lo, hi in cfg.sessions:
        if lo <= hour < hi:
            return day + lo * HOUR_MS
    raise ValueError("sessions do not cover the day")
