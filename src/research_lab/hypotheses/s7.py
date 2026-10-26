"""Signal rules of study S7 (docs/research_lab/studien/S7_3_4R_TRENDFOLGE_AUSBRUCH_PRAEREGISTRIERUNG.md).

Donchian breakout in the direction of the SMA 200 on closed 4h bars of one USD-M
perpetual (section 4.1). Every rule reads only the History it is given. The
geometry is frozen: stop at max(1.5 x ATR14, 1 % of the signal close) below (above)
the signal close, fixed target T in R, time stop 30 bars; exits are the engine's
(protocol 4.2), the stop wins inside a bar.

Nothing here computes outcomes. `count_signals` is the outcome-blind count of the
feasibility gate (section 6.1).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.research_lab.backtest.engine import History, Signal, Strategy
from src.research_lab.backtest.indicators import atr, sma_close
from src.research_lab.data.parse import Kline

INTERVAL = "4h"
INTERVAL_MS = 14_400_000
SMA_PERIOD = 200
ATR_PERIOD = 14
ATR_FACTOR = 1.5
MIN_STOP_DISTANCE = 0.01  # cost gate, section 4.1
TIME_STOP_BARS = 30
CHANNELS = (20, 55)
TARGETS = (3.0, 4.0)
SEED = 20261101
HYPOTHESIS = "S7"


@dataclass(frozen=True, slots=True)
class S7Variant:
    variant_id: str
    channel: int
    target_r: float
    hypothesis: str = HYPOTHESIS

    @property
    def warmup(self) -> int:
        """Closed bars needed before the first signal; all of them must be contiguous."""
        return max(SMA_PERIOD, self.channel + 1, ATR_PERIOD + 1)

    @property
    def params(self) -> dict[str, float | int | str]:
        return {"interval": INTERVAL, "channel": self.channel, "target_r": self.target_r, "sma": SMA_PERIOD,
                "atr": ATR_PERIOD, "atr_factor": ATR_FACTOR, "min_stop": MIN_STOP_DISTANCE, "time_stop": TIME_STOP_BARS}


S7_VARIANTS: tuple[S7Variant, ...] = tuple(
    S7Variant(f"S7-D{n}-T{int(t)}", n, t) for n in CHANNELS for t in TARGETS
)


@dataclass(slots=True)
class Counts:
    """What a rule saw, for the report (section 4.1)."""

    emitted: int = 0
    skipped_gap: int = 0  # signal bar inside an incomplete indicator window
    emitted_times: list[int] = field(default_factory=list)


def channel(history: Sequence[Kline], n: int) -> tuple[float, float]:
    """(highest high, lowest low) of bars t-n .. t-1, without the current bar t."""
    window = history[len(history) - 1 - n: len(history) - 1]
    return max(b.high for b in window), min(b.low for b in window)


def contiguous(history: Sequence[Kline], span: int) -> bool:
    """True when the last `span` bars follow each other without a missing 4h bar."""
    bars = history[len(history) - span:]
    return all(b.open_time - a.open_time == INTERVAL_MS for a, b in zip(bars, bars[1:]))


def breakout(variant: S7Variant, counts: Counts | None = None) -> Strategy:
    counts = counts if counts is not None else Counts()
    n, need = variant.channel, variant.warmup

    def strategy(history: History) -> Signal | None:
        if len(history) < need:
            return None
        bar = history[-1]
        sma = sma_close(history, SMA_PERIOD)
        width = atr(history, ATR_PERIOD)
        if sma is None or width is None:
            return None
        high, low = channel(history, n)
        long = bar.close > high and bar.close > sma
        short = bar.close < low and bar.close < sma
        if not (long or short):
            return None
        if not contiguous(history, need):
            counts.skipped_gap += 1
            return None
        side = 1 if long else -1
        risk = max(ATR_FACTOR * width, MIN_STOP_DISTANCE * bar.close)
        counts.emitted += 1
        counts.emitted_times.append(bar.open_time)
        return Signal(side, bar.close - side * risk, target_r=variant.target_r, time_stop_bars=TIME_STOP_BARS)

    return strategy


def iso_week(ms: int) -> str:
    stamp = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isocalendar()
    return f"{stamp.year}-W{stamp.week:02d}"


def year_of(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year


@dataclass(frozen=True, slots=True)
class SignalCount:
    upper: int  # every emitted signal
    lower: int  # signals at least 30 bars after the last counted one (every trade assumed to run to the time stop)
    skipped_gap: int
    lower_times: tuple[int, ...]  # open times of the lower-bound signals (for weeks and years)


def count_signals(bars: Sequence[Kline], variant: S7Variant, start_ms: int, end_ms: int) -> SignalCount:
    """Outcome-blind count for the feasibility gate (section 6.1). No exits, no R, no prices after the signal."""
    counts = Counts()
    strategy = breakout(variant, counts)
    upper = lower = 0
    last: int | None = None
    times: list[int] = []
    for t, bar in enumerate(bars):
        if bar.open_time < start_ms:
            continue
        if bar.open_time >= end_ms:
            break
        if strategy(History(bars, t)) is None:
            continue
        upper += 1
        if last is None or t - last >= TIME_STOP_BARS:
            # entry at t+1, the time stop closes at the end of bar t+30 (entry bar = 1), and the
            # engine evaluates the strategy on that bar after the exit, so the next signal may fall on t+30
            lower += 1
            last = t
            times.append(bar.open_time)
    return SignalCount(upper, lower, counts.skipped_gap, tuple(times))
