"""Strategy builders for the registered hypotheses (protocol section 6).

Every strategy reads only the History it is given (closed bars up to now) and,
where needed, data that was public at that moment (funding rates up to the
bar's close). Parameters are fixed by the protocol grid.
"""
from __future__ import annotations

import bisect
from collections.abc import Sequence
from datetime import datetime, timezone

from src.analysis.bos_detector import BOSDetector
from src.analysis.bronxc_rules import BroncxRules
from src.models.market_data import Candle, ObservationKind
from src.research_lab.backtest.engine import History, Signal, Strategy
from src.research_lab.backtest.indicators import atr, sma_close
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses.calendars import session_bounds

DAY_MS = 86_400_000


def _weekday(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).weekday()


# --- Long -------------------------------------------------------------------

def l1_trend(n: int, long_short: bool) -> Strategy:
    """Enter on a close crossing SMA(n); leave when the close crosses back."""

    def strategy(history: History) -> Signal | None:
        if len(history) < n + 21:
            return None
        now = sma_close(history, n)
        before = sma_close(history[: len(history) - 1], n)
        close, previous = history[-1].close, history[-2].close
        width = atr(history, 20)
        if previous <= before and close > now:
            return Signal(1, close - 3 * width, exit_rule=lambda h, p: h[-1].close < sma_close(h, n))
        if long_short and previous >= before and close < now:
            return Signal(-1, close + 3 * width, exit_rule=lambda h, p: h[-1].close > sma_close(h, n))
        return None

    return strategy


def l2_momentum(lookback: int, long_short: bool) -> Strategy:
    """Every Sunday close decide the position for the coming week (Monday to Sunday)."""

    def strategy(history: History) -> Signal | None:
        if len(history) < lookback + 21 or _weekday(history[-1].open_time) != 6:
            return None
        change = history[-1].close / history[-1 - lookback].close - 1
        width = atr(history, 20)
        close = history[-1].close
        if change > 0:
            return Signal(1, close - 3 * width, time_stop_bars=7)
        if change < 0 and long_short:
            return Signal(-1, close + 3 * width, time_stop_bars=7)
        return None

    return strategy


# --- Mid --------------------------------------------------------------------

def m1_donchian(n: int, k: float) -> Strategy:
    half = n // 2

    def strategy(history: History) -> Signal | None:
        if len(history) < n + 15:
            return None
        window = history[len(history) - 1 - n: len(history) - 1]
        close = history[-1].close
        width = atr(history, 14)
        if close > max(b.high for b in window):
            return Signal(1, close - k * width, time_stop_bars=20,
                          exit_rule=lambda h, p: h[-1].close < min(b.low for b in h[len(h) - 1 - half: len(h) - 1]))
        if close < min(b.low for b in window):
            return Signal(-1, close + k * width, time_stop_bars=20,
                          exit_rule=lambda h, p: h[-1].close > max(b.high for b in h[len(h) - 1 - half: len(h) - 1]))
        return None

    return strategy


def _daily_atr_from_hours(history: History, days: int = 14) -> float | None:
    """ATR over the last `days` completed UTC days, built from hourly bars."""
    cutoff = (history[-1].close_time + 1) // DAY_MS * DAY_MS  # end of the last completed day
    first = cutoff - (days + 1) * DAY_MS
    daily: dict[int, list[Kline]] = {}
    index = len(history) - 1
    while index >= 0 and history[index].open_time >= first:
        bar = history[index]
        if bar.open_time < cutoff:
            daily.setdefault(bar.open_time // DAY_MS, []).append(bar)
        index -= 1
    if len(daily) < days + 1:
        return None
    summary = []
    for key in sorted(daily):
        bars = sorted(daily[key], key=lambda b: b.open_time)
        summary.append((max(b.high for b in bars), min(b.low for b in bars), bars[-1].close))
    ranges = [max(h - l, abs(h - prev[2]), abs(l - prev[2])) for prev, (h, l, _) in zip(summary, summary[1:])]
    return sum(ranges) / days


def m2_funding(funding: Sequence[FundingRate], q: float, hold_days: int) -> Strategy:
    """Fade extreme funding. Uses only funding values published before the signal."""
    times = [f.time for f in funding]
    year_ms = 365 * DAY_MS

    def strategy(history: History) -> Signal | None:
        moment = history[-1].close_time + 1
        at = bisect.bisect_left(times, moment)
        if at >= len(times) or times[at] != moment:
            return None
        current = funding[at].rate
        if not times or times[0] > moment - year_ms:
            return None  # fewer than 365 days of funding history
        past = sorted(f.rate for f in funding[bisect.bisect_left(times, moment - year_ms): at])
        low = past[int(q * (len(past) - 1))]
        high = past[int((1 - q) * (len(past) - 1))]
        width = _daily_atr_from_hours(history)
        if width is None:
            return None
        close = history[-1].close
        if current > high:
            return Signal(-1, close + 2 * width, time_stop_bars=hold_days * 24)
        if current < low:
            return Signal(1, close - 2 * width, time_stop_bars=hold_days * 24)
        return None

    return strategy


def m3_weekday(weekday: int, side: int) -> Strategy:
    """Hold from 00:00 to 24:00 UTC on the given weekday (0 = Monday)."""

    def strategy(history: History) -> Signal | None:
        if len(history) < 15 or _weekday(history[-1].open_time + DAY_MS) != weekday:
            return None
        width = atr(history, 14)
        close = history[-1].close
        return Signal(side, close - side * width, time_stop_bars=1)

    return strategy


# --- Short ------------------------------------------------------------------

def s1_cvd_divergence(n: int, interval_ms: int) -> Strategy:
    time_stop = 4 * 3_600_000 // interval_ms

    def strategy(history: History) -> Signal | None:
        if len(history) < max(n, 15) + 1:
            return None
        window = history[len(history) - n:]
        cvd, running = [], 0.0
        for bar in window:
            running += bar.delta
            cvd.append(running)
        bar, width = window[-1], atr(history, 14)
        if bar.high > max(b.high for b in window[:-1]) and cvd[-1] <= max(cvd[:-1]):
            return Signal(-1, bar.high + 0.5 * width, target_r=2.0, time_stop_bars=time_stop)
        if bar.low < min(b.low for b in window[:-1]) and cvd[-1] >= min(cvd[:-1]):
            return Signal(1, bar.low - 0.5 * width, target_r=2.0, time_stop_bars=time_stop)
        return None

    return strategy


def s2_opening_range(session: str, minutes: int, interval_ms: int = 300_000) -> Strategy:
    """Breakout of the first `minutes` of a session; one trade per session."""

    def strategy(history: History) -> Signal | None:
        bar = history[-1]
        day = datetime.fromtimestamp(bar.open_time / 1000, tz=timezone.utc).date()
        bounds = session_bounds(session, day)
        if bounds is None:
            return None
        opens, closes = bounds
        range_end = opens + minutes * 60_000
        if not range_end <= bar.open_time < closes - interval_ms:
            return None
        start = len(history) - 1 - (bar.open_time - opens) // interval_ms
        if start < 0 or history[start].open_time != opens:
            return None  # missing data inside the session
        in_range = history[start: start + minutes * 60_000 // interval_ms]
        high, low = max(b.high for b in in_range), min(b.low for b in in_range)
        for earlier in history[start + len(in_range): len(history) - 1]:
            if earlier.close > high or earlier.close < low:
                return None  # the first breakout of this session has already happened
        remaining = (closes - bar.close_time - 1) // interval_ms  # bars left after the signal bar
        if bar.close > high:
            return Signal(1, low, target_r=2.0, time_stop_bars=remaining)
        if bar.close < low:
            return Signal(-1, high, target_r=2.0, time_stop_bars=remaining)
        return None

    return strategy


# --- TIM's own rules (R5) ---------------------------------------------------

BOS_WINDOW = 300


def _candles(history: History, count: int, timeframe: str, cache: dict[int, Candle]) -> list[Candle]:
    result = []
    for bar in history[max(0, len(history) - count):]:
        candle = cache.get(bar.open_time)
        if candle is None:
            candle = Candle("BTCUSDT", timeframe,
                            datetime.fromtimestamp(bar.open_time / 1000, tz=timezone.utc),
                            datetime.fromtimestamp((bar.close_time + 1) / 1000, tz=timezone.utc),
                            bar.open, bar.high, bar.low, bar.close, bar.volume, 0)
            cache[bar.open_time] = candle
        result.append(candle)
    if len(cache) > 4 * count:
        for key in sorted(cache)[: len(cache) - 2 * count]:
            del cache[key]
    return result


def t1_bos(timeframe: str) -> Strategy:
    """BOSDetector with default parameters, called only with bars up to now (last BOS_WINDOW)."""
    detector, cache = BOSDetector(), {}

    def strategy(history: History) -> Signal | None:
        if len(history) < 15:
            return None
        observation = detector.detect(_candles(history, BOS_WINDOW, timeframe, cache))
        if observation is None:
            return None
        side = 1 if observation.kind is ObservationKind.BOS_BULLISH else -1
        close = history[-1].close
        return Signal(side, close - side * atr(history, 14), target_r=2.0, time_stop_bars=24)

    return strategy


def t2_rejection(timeframe: str) -> Strategy:
    rules, cache = BroncxRules(), {}

    def strategy(history: History) -> Signal | None:
        if len(history) < 15:
            return None
        kinds = {o.kind for o in rules.evaluate(_candles(history, 6, timeframe, cache))}
        if ObservationKind.REJECTION not in kinds:
            return None
        bar, width = history[-1], atr(history, 14)
        upper = bar.high - max(bar.open, bar.close)
        lower = min(bar.open, bar.close) - bar.low
        if upper > lower:
            return Signal(-1, bar.high + 0.1 * width, target_r=2.0, time_stop_bars=24)
        if lower > upper:
            return Signal(1, bar.low - 0.1 * width, target_r=2.0, time_stop_bars=24)
        return None

    return strategy


def t3_failed_continuation(timeframe: str) -> Strategy:
    rules, cache = BroncxRules(), {}

    def strategy(history: History) -> Signal | None:
        if len(history) < 15:
            return None
        kinds = {o.kind for o in rules.evaluate(_candles(history, 6, timeframe, cache))}
        if ObservationKind.FAILED_CONTINUATION not in kinds:
            return None
        previous, width = history[-2], atr(history, 14)
        reference = history[len(history) - 6: len(history) - 2]
        broke_high = previous.high > max(b.high for b in reference)
        broke_low = previous.low < min(b.low for b in reference)
        if broke_high and not broke_low:
            return Signal(-1, previous.high + 0.1 * width, target_r=2.0, time_stop_bars=24)
        if broke_low and not broke_high:
            return Signal(1, previous.low - 0.1 * width, target_r=2.0, time_stop_bars=24)
        return None

    return strategy
