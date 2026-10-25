"""Signal rules of study S4 (docs/research_lab/studien/S4_TREFFERQUOTE_75_PRAEREGISTRIERUNG.md, version 1.0).

All rules run on closed 1h bars of one USD-M perpetual and read only the
History they are given plus daily bars that closed no later than the current
hourly bar. Every signal has the frozen geometry of section 4.1: target 0.75 R,
time stop 24 bars (H5: until the close of the 19:00 UTC bar), and passes the
cost gate (stop at least 1.0 % from the signal close).

Nothing here computes outcomes. `count_signals` is the outcome-blind count of
the feasibility gate (section 6.1).
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from src.research_lab.backtest.engine import History, Signal, Strategy
from src.research_lab.backtest.indicators import atr
from src.research_lab.data.parse import Kline

TARGET_R = 0.75
TIME_STOP_BARS = 24
MIN_STOP_DISTANCE = 0.01  # cost gate, section 4.1
ATR_PERIOD = 14
REGIME_DAYS = 20
REGIME_THRESHOLD = 0.05
DELTA_LOOKBACK = 720
SEED = 20261025

UP, DOWN, SIDEWAYS = "up", "down", "sideways"
SESSIONS = {"london": range(7, 11), "newyork": range(13, 17)}  # opening hours (UTC) of signal bars
ASIA_HOURS = range(0, 7)
H5_LAST_BAR_HOUR = 19


@dataclass(slots=True)
class Counts:
    """Signals a rule saw but did not emit, for the report (section 4.1)."""

    skipped_cost: int = 0
    contradictory: int = 0
    regime_unknown: int = 0
    emitted: int = 0
    skipped_cost_times: list[int] = field(default_factory=list)


def _hour(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).hour


def _day(ms: int) -> int:
    return ms // 86_400_000


class DailyRegime:
    """Regime from daily closes that closed no later than the hourly bar (section 4.1)."""

    def __init__(self, daily: Sequence[Kline]) -> None:
        self._closes = [bar.close for bar in daily]
        self._close_times = [bar.close_time for bar in daily]

    def at(self, hourly_close_time: int) -> str | None:
        count = bisect.bisect_right(self._close_times, hourly_close_time)
        if count < REGIME_DAYS + 1:
            return None
        change = self._closes[count - 1] / self._closes[count - 1 - REGIME_DAYS] - 1
        if change >= REGIME_THRESHOLD:
            return UP
        if change <= -REGIME_THRESHOLD:
            return DOWN
        return SIDEWAYS


def _gate(side: int, close: float, stop: float, counts: Counts, time: int, time_stop: int = TIME_STOP_BARS) -> Signal | None:
    if (close - stop) * side <= 0:
        return None
    if abs(close - stop) / close < MIN_STOP_DISTANCE:
        counts.skipped_cost += 1
        counts.skipped_cost_times.append(time)
        return None
    counts.emitted += 1
    return Signal(side, stop, target_r=TARGET_R, time_stop_bars=time_stop)


def _pick(long: Signal | None, short: Signal | None, counts: Counts) -> Signal | None:
    if long is not None and short is not None:
        counts.contradictory += 1
        counts.emitted -= 2
        return None
    return long or short


def _sweep(history: History, n: int) -> tuple[bool, bool, float]:
    """(long sweep, short sweep, atr) per H1: wick beyond the N-bar extreme, close back inside and in the right half."""
    bar = history[-1]
    window = history[len(history) - 1 - n: len(history) - 1]
    low, high = min(b.low for b in window), max(b.high for b in window)
    mid = (bar.high + bar.low) / 2
    long = bar.low < low and bar.close > low and bar.close >= mid
    short = bar.high > high and bar.close < high and bar.close <= mid
    return long, short, atr(history, ATR_PERIOD)


def h1_sweep(n: int, counts: Counts | None = None) -> Strategy:
    counts = counts if counts is not None else Counts()

    def strategy(history: History) -> Signal | None:
        if len(history) < n + ATR_PERIOD + 1:
            return None
        long, short, width = _sweep(history, n)
        if width is None or not (long or short):
            return None
        bar = history[-1]
        return _pick(_gate(1, bar.close, bar.low - 0.25 * width, counts, bar.open_time) if long else None,
                     _gate(-1, bar.close, bar.high + 0.25 * width, counts, bar.open_time) if short else None, counts)

    return strategy


def nearest_rank(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def h2_sweep_delta(strength: str, counts: Counts | None = None) -> Strategy:
    if strength not in ("sign", "p80"):
        raise ValueError("strength must be 'sign' or 'p80'")
    counts = counts if counts is not None else Counts()
    n = 24

    def strategy(history: History) -> Signal | None:
        if len(history) < DELTA_LOOKBACK + 1:
            return None
        long, short, width = _sweep(history, n)
        if width is None or not (long or short):
            return None
        bar = history[-1]
        delta = bar.delta
        if strength == "p80":
            past = [abs(b.delta) for b in history[len(history) - 1 - DELTA_LOOKBACK: len(history) - 1]]
            if abs(delta) < nearest_rank(past, 0.8):
                return None
        long = long and delta < 0  # sellers aggressive, still reclaimed
        short = short and delta > 0
        return _pick(_gate(1, bar.close, bar.low - 0.25 * width, counts, bar.open_time) if long else None,
                     _gate(-1, bar.close, bar.high + 0.25 * width, counts, bar.open_time) if short else None, counts)

    return strategy


def h3_mean_reversion(k: float, regime: DailyRegime, counts: Counts | None = None) -> Strategy:
    counts = counts if counts is not None else Counts()

    def strategy(history: History) -> Signal | None:
        if len(history) < 24 + ATR_PERIOD:
            return None
        bar = history[-1]
        width = atr(history, ATR_PERIOD)
        if width is None:
            return None
        mean = sum(b.close for b in history[len(history) - 24:]) / 24  # closes t-23 .. t
        long, short = bar.close <= mean - k * width, bar.close >= mean + k * width
        if not (long or short):
            return None
        state = regime.at(bar.close_time)
        if state is None:
            counts.regime_unknown += 1
            return None
        if state != SIDEWAYS:
            return None
        return _gate(1, bar.close, bar.low - width, counts, bar.open_time) if long else \
            _gate(-1, bar.close, bar.high + width, counts, bar.open_time)

    return strategy


def h4_trend_pullback(d: float, regime: DailyRegime, counts: Counts | None = None) -> Strategy:
    counts = counts if counts is not None else Counts()

    def strategy(history: History) -> Signal | None:
        if len(history) < 25 + ATR_PERIOD:
            return None
        bar, size = history[-1], len(history)
        highs = [history[size - 1 - i].high for i in range(4, 0, -1)]  # t-4 .. t-1
        lows = [history[size - 1 - i].low for i in range(4, 0, -1)]
        width = atr(history, ATR_PERIOD)
        if width is None:
            return None
        recent = history[size - 7: size - 1]  # t-6 .. t-1
        longer = history[size - 25: size - 1]  # t-24 .. t-1
        long_shape = highs[0] > highs[1] > highs[2] > highs[3] and bar.close > highs[3]
        short_shape = lows[0] < lows[1] < lows[2] < lows[3] and bar.close < lows[3]
        if not (long_shape or short_shape):
            return None
        state = regime.at(bar.close_time)
        if state is None:
            counts.regime_unknown += 1
            return None
        if state == UP and long_shape:
            peak = max(range(len(longer)), key=lambda i: (longer[i].high, -i))  # earliest highest high
            trough = min(range(len(recent)), key=lambda i: (recent[i].low, -i))  # latest lowest low
            peak_time, trough_time = longer[peak].open_time, recent[trough].open_time
            if peak_time < trough_time and longer[peak].high - recent[trough].low >= d * width:
                stop = min(b.low for b in history[size - 7:]) - 0.25 * width  # t-6 .. t
                return _gate(1, bar.close, stop, counts, bar.open_time)
        if state == DOWN and short_shape:
            trough = min(range(len(longer)), key=lambda i: (longer[i].low, i))  # earliest lowest low
            peak = max(range(len(recent)), key=lambda i: (recent[i].high, i))  # latest highest high
            if longer[trough].open_time < recent[peak].open_time and recent[peak].high - longer[trough].low >= d * width:
                stop = max(b.high for b in history[size - 7:]) + 0.25 * width
                return _gate(-1, bar.close, stop, counts, bar.open_time)
        return None

    return strategy


def h5_session_sweep(session: str, counts: Counts | None = None) -> Strategy:
    if session not in SESSIONS:
        raise ValueError(f"session must be one of {sorted(SESSIONS)}")
    counts = counts if counts is not None else Counts()
    hours = SESSIONS[session]
    last_day: list[int] = [-1]

    def strategy(history: History) -> Signal | None:
        bar = history[-1]
        hour, day = _hour(bar.open_time), _day(bar.open_time)
        if hour not in hours or day == last_day[0] or len(history) < hour + ATR_PERIOD + 1:
            return None
        asia = [b for b in history[len(history) - 1 - hour: len(history) - 1]
                if _day(b.open_time) == day and _hour(b.open_time) in ASIA_HOURS]
        if len(asia) != len(ASIA_HOURS):
            return None
        width = atr(history, ATR_PERIOD)
        if width is None:
            return None
        top, bottom = max(b.high for b in asia), min(b.low for b in asia)
        short = bar.high > top and bar.close <= top
        long = bar.low < bottom and bar.close >= bottom
        if not (long or short):
            return None
        bars_left = H5_LAST_BAR_HOUR - hour  # entry bar opens at hour+1, last bar opens at 19:00
        signal = _pick(_gate(1, bar.close, bar.low - 0.25 * width, counts, bar.open_time, bars_left) if long else None,
                       _gate(-1, bar.close, bar.high + 0.25 * width, counts, bar.open_time, bars_left) if short else None,
                       counts)
        if signal is not None:
            last_day[0] = day  # at most one trade per day and instrument
        return signal

    return strategy


@dataclass(frozen=True, slots=True)
class S4Variant:
    variant_id: str
    hypothesis: str
    build: Callable[[DailyRegime, Counts], Strategy]
    spacing: str = "bars"  # lower-bound spacing for the count: "bars" (24) or "day" (H5)


S4_VARIANTS: tuple[S4Variant, ...] = (
    S4Variant("S4-H1-N24", "H1", lambda r, c: h1_sweep(24, c)),
    S4Variant("S4-H1-N72", "H1", lambda r, c: h1_sweep(72, c)),
    S4Variant("S4-H2-sign", "H2", lambda r, c: h2_sweep_delta("sign", c)),
    S4Variant("S4-H2-p80", "H2", lambda r, c: h2_sweep_delta("p80", c)),
    S4Variant("S4-H3-k2", "H3", lambda r, c: h3_mean_reversion(2, r, c)),
    S4Variant("S4-H3-k3", "H3", lambda r, c: h3_mean_reversion(3, r, c)),
    S4Variant("S4-H4-d1.5", "H4", lambda r, c: h4_trend_pullback(1.5, r, c)),
    S4Variant("S4-H4-d2.5", "H4", lambda r, c: h4_trend_pullback(2.5, r, c)),
    S4Variant("S4-H5-london", "H5", lambda r, c: h5_session_sweep("london", c), "day"),
    S4Variant("S4-H5-newyork", "H5", lambda r, c: h5_session_sweep("newyork", c), "day"),
)


@dataclass(frozen=True, slots=True)
class SignalCount:
    upper: int  # every emitted signal
    lower: int  # signals at least 24 bars (H5: one day) after the last counted one
    skipped_cost: int
    contradictory: int
    regime_unknown: int


def count_signals(bars: Sequence[Kline], variant: S4Variant, daily: Sequence[Kline], start_ms: int, end_ms: int) -> SignalCount:
    """Outcome-blind count for the feasibility gate (section 6.1). No exits, no R."""
    counts = Counts()
    strategy = variant.build(DailyRegime(daily), counts)
    upper = lower = 0
    last: int | None = None
    for t, bar in enumerate(bars):
        if not start_ms <= bar.open_time < end_ms:
            if bar.open_time < start_ms:
                continue
            break
        signal = strategy(History(bars, t))
        if signal is None:
            continue
        upper += 1
        if variant.spacing == "day":
            key = _day(bar.open_time)
            if key != last:
                lower += 1
                last = key
        elif last is None or t - last >= TIME_STOP_BARS:
            lower += 1
            last = t
    return SignalCount(upper, lower, counts.skipped_cost, counts.contradictory, counts.regime_unknown)
