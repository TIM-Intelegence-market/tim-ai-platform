"""Signal rules of study S9 (docs/research_lab/studien/S9_CHOCH_RETEST_PRAEREGISTRIERUNG.md).

CHoCH by close, retest band around the broken level, reaction close beyond the band,
stop at the origin extreme, entry only with R:R >= 2 (GoatHub lesson "How to identify
direction", model A on 15m). Rebuilt here on its own, independent of the chart's
``market_structure``; every rule only reads closed bars up to the current one.

``Detector.step`` consumes one bar at a time. The strategy catches up on every bar it
has not seen yet, so the engine may call it only inside the signal range. A missing
15m bar resets all state (no structure across a data gap).

Nothing here computes outcomes. ``count_signals`` is the outcome-blind count of the
feasibility gate (section 6).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from src.research_lab.backtest.engine import History, Signal, Strategy
from src.research_lab.data.archive import Market
from src.research_lab.data.parse import Kline

HYPOTHESIS = "S9"
INTERVAL = "15m"
INTERVAL_MS = 900_000
PIVOT = 2  # bars left and right (lesson p. 4)
ATR_PERIOD = 14
STOP_BUFFER_ATR = 0.1
MIN_RR = 2.0
EXPIRY_BARS = 48  # 12 h from the CHoCH bar to the reaction close
TIME_STOP_BARS = 96  # 24 h after entry
ZONE_ATR_DAILY = 0.5  # variant Z: origin within 0.5 x ATR(14, 1d) of a previous day/week level
DAILY_ATR_PERIOD = 14
VALUE_AREA_SHARE = 0.70
PROFILE_BINS = 60
BANDS = (0.25, 0.50)
ZONES = (False, True)
SEED = 20261028
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS


# ----------------------------------------------------------------------------- variants


@dataclass(frozen=True, slots=True)
class S9Variant:
    variant_id: str
    band: float
    zone: bool
    hypothesis: str = HYPOTHESIS

    @property
    def params(self) -> dict[str, float | int | str | bool]:
        return {"interval": INTERVAL, "b": self.band, "zone": self.zone, "pivot": PIVOT, "atr": ATR_PERIOD,
                "stop_buffer_atr": STOP_BUFFER_ATR, "min_rr": MIN_RR, "expiry": EXPIRY_BARS, "time_stop": TIME_STOP_BARS,
                "zone_atr_1d": ZONE_ATR_DAILY}


S9_VARIANTS: tuple[S9Variant, ...] = tuple(
    S9Variant(f"S9-B{int(b * 100)}-{'Z' if z else 'I'}", b, z) for z in ZONES for b in BANDS
)


# ----------------------------------------------------------------------------- higher-timeframe levels (variant Z)


def volume_profile(bars: Sequence[Kline]) -> tuple[float, float, float] | None:
    """(POC, VAH, VAL) of closed bars; each bar's volume spread evenly over its high-low range,
    60 equal bins over the period's range, value area 70 % grown from the POC towards the fuller side."""
    usable = [b for b in bars if b.volume > 0]
    if len(usable) < 2:
        return None
    low, high = min(b.low for b in usable), max(b.high for b in usable)
    if high <= low:
        return None
    step = (high - low) / PROFILE_BINS
    bins = [0.0] * PROFILE_BINS
    for b in usable:
        first = min(PROFILE_BINS - 1, int((b.low - low) / step))
        last = min(PROFILE_BINS - 1, int((b.high - low) / step))
        if b.high <= b.low or first == last:
            bins[first] += b.volume
            continue
        for i in range(first, last + 1):
            lo, hi = max(b.low, low + i * step), min(b.high, low + (i + 1) * step)
            if hi > lo:
                bins[i] += b.volume * (hi - lo) / (b.high - b.low)
    total = sum(bins)
    poc = max(range(PROFILE_BINS), key=lambda i: (bins[i], -i))
    lo_i = hi_i = poc
    covered = bins[poc]
    while covered < total * VALUE_AREA_SHARE and (lo_i > 0 or hi_i < PROFILE_BINS - 1):
        below = bins[lo_i - 1] if lo_i > 0 else -1.0
        above = bins[hi_i + 1] if hi_i < PROFILE_BINS - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += bins[hi_i]
        else:
            lo_i -= 1
            covered += bins[lo_i]
    return low + (poc + 0.5) * step, low + (hi_i + 1) * step, low + lo_i * step


def period_levels(bars: Sequence[Kline]) -> tuple[float, ...]:
    """High, low, POC, VAH, VAL of one finished period."""
    profile = volume_profile(bars)
    extremes = (max(b.high for b in bars), min(b.low for b in bars))
    return extremes + (profile if profile else ())


def week_start(ms: int) -> int:
    day = datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()
    monday = day - timedelta(days=day.weekday())
    return int(datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc).timestamp() * 1000)


@dataclass(slots=True)
class HigherTimeframe:
    """Previous UTC day and previous ISO week (Monday 00:00 UTC), known once they have closed."""

    day_key: int | None = None
    week_key: int | None = None
    day_bars: list[Kline] = field(default_factory=list)
    week_bars: list[Kline] = field(default_factory=list)
    daily: list[tuple[float, float, float]] = field(default_factory=list)  # (high, low, close) of finished days
    day_levels: tuple[float, ...] = ()
    week_levels: tuple[float, ...] = ()

    def add(self, bar: Kline) -> None:
        day, week = bar.open_time // DAY_MS * DAY_MS, week_start(bar.open_time)
        if self.day_key is not None and day != self.day_key:
            if self.day_bars:
                self.day_levels = period_levels(self.day_bars)
                self.daily.append((max(b.high for b in self.day_bars), min(b.low for b in self.day_bars), self.day_bars[-1].close))
                del self.daily[:-(DAILY_ATR_PERIOD + 1)]
            self.day_bars = []
        if self.week_key is not None and week != self.week_key:
            if self.week_bars:
                self.week_levels = period_levels(self.week_bars)
            self.week_bars = []
        self.day_key, self.week_key = day, week
        self.day_bars.append(bar)
        self.week_bars.append(bar)

    def daily_atr(self) -> float | None:
        if len(self.daily) < DAILY_ATR_PERIOD + 1:
            return None
        rows = self.daily[-(DAILY_ATR_PERIOD + 1):]
        ranges = [max(h - l, abs(h - prev[2]), abs(l - prev[2])) for prev, (h, l, _) in zip(rows, rows[1:])]
        return sum(ranges) / DAILY_ATR_PERIOD

    def near_level(self, price: float) -> bool:
        width = self.daily_atr()
        if width is None or not self.day_levels or not self.week_levels:
            return False
        return any(abs(price - level) <= ZONE_ATR_DAILY * width for level in self.day_levels + self.week_levels)


# ----------------------------------------------------------------------------- structure and setups


@dataclass(slots=True)
class Swing:
    index: int
    price: float


@dataclass(slots=True)
class Reference:
    """The level a CHoCH must close through: the newest confirmed lower high (long) or higher low (short).

    It becomes active once price has printed beyond the last opposite swing before it (a lower low
    after the LH, a higher high after the HL), so a close through it ends a LH -> LL sequence."""

    side: int
    price: float
    index: int  # bar of the reference swing
    beyond: float  # the swing low (long) or high (short) that a new extreme must exceed
    active: bool = False


@dataclass(slots=True)
class Setup:
    side: int
    choch_index: int
    level: float
    band_low: float
    band_high: float
    origin: float
    atr: float
    impulse: float  # most extreme price since the CHoCH bar, before the reaction bar
    touched: bool = False


@dataclass(slots=True)
class Counts:
    """What the rules saw, for the report."""

    choch: int = 0
    zone_rejected: int = 0
    expired: int = 0
    invalidated: int = 0
    replaced: int = 0
    rr_rejected: int = 0
    emitted: int = 0
    resets: int = 0
    rr_taken: list[float] = field(default_factory=list)


class Detector:
    def __init__(self, variant: S9Variant, counts: Counts | None = None) -> None:
        self.variant = variant
        self.counts = counts if counts is not None else Counts()
        self._reset()

    def _reset(self) -> None:
        self.bars: list[Kline] = []  # contiguous bars since the last reset
        self.highs: list[Swing] = []
        self.lows: list[Swing] = []
        self.refs: dict[int, Reference | None] = {1: None, -1: None}
        self.setup: Setup | None = None
        self.htf = HigherTimeframe()
        self.trs: list[float] = []

    def _atr(self) -> float | None:
        return sum(self.trs[-ATR_PERIOD:]) / ATR_PERIOD if len(self.trs) >= ATR_PERIOD else None

    def step(self, bar: Kline) -> Signal | None:
        if self.bars and bar.open_time - self.bars[-1].open_time != INTERVAL_MS:
            self.counts.resets += 1
            self._reset()
        if self.bars:
            prev = self.bars[-1].close
            self.trs.append(max(bar.high - bar.low, abs(bar.high - prev), abs(bar.low - prev)))
            del self.trs[:-ATR_PERIOD]
        self.bars.append(bar)
        self.htf.add(bar)  # a finished day/week becomes known at the first bar after it
        t = len(self.bars) - 1
        self._confirm_pivot(t)
        signal = self._advance_setup(t, bar)
        self._check_choch(t, bar)
        return signal

    # -- swings (confirmed at the close of the PIVOT-th bar on the right)

    def _confirm_pivot(self, t: int) -> None:
        i = t - PIVOT
        if i < PIVOT:
            return
        c = self.bars[i]
        others = self.bars[i - PIVOT: i] + self.bars[i + 1: t + 1]
        if all(c.high > b.high for b in others):
            self._swing(1, Swing(i, c.high), t)
        if all(c.low < b.low for b in others):
            self._swing(-1, Swing(i, c.low), t)

    def _swing(self, kind: int, swing: Swing, t: int) -> None:
        """kind +1: a confirmed swing high, the candidate long reference if it is a lower high;
        kind -1: a confirmed swing low, the candidate short reference if it is a higher low."""
        same, opposite = (self.highs, self.lows) if kind == 1 else (self.lows, self.highs)
        side = kind  # a swing high is broken upwards (long), a swing low downwards (short)
        lower_high_or_higher_low = bool(same) and (swing.price - same[-1].price) * kind < 0
        before = [s for s in opposite if s.index < swing.index]
        self.refs[side] = None
        if lower_high_or_higher_low and before:
            ref = Reference(side, swing.price, swing.index, before[-1].price)
            # the run after the swing may already have printed the new extreme while the swing was being confirmed
            ref.active = any((b.low < ref.beyond) if side == 1 else (b.high > ref.beyond) for b in self.bars[swing.index + 1: t + 1])
            if not any((b.close - ref.price) * side > 0 for b in self.bars[swing.index + 1: t + 1]):
                self.refs[side] = ref
        same.append(swing)
        del same[:-3]

    def _check_choch(self, t: int, bar: Kline) -> None:
        for side in (1, -1):
            ref = self.refs[side]
            if ref is None:
                continue
            if not ref.active and ((bar.low < ref.beyond) if side == 1 else (bar.high > ref.beyond)):
                ref.active = True  # LL after the LH (long) or HH after the HL (short): the structure is in place
            if (bar.close - ref.price) * side <= 0:  # equality is no break
                continue
            self.refs[side] = None  # one label per impulse; a close through it without the new extreme only spends it
            if not ref.active:
                continue
            self.counts.choch += 1
            width = self._atr()
            if width is None:
                continue
            span = self.bars[ref.index: t + 1]
            origin = min(b.low for b in span) if side == 1 else max(b.high for b in span)
            if self.variant.zone and not self.htf.near_level(origin):
                self.counts.zone_rejected += 1
                continue
            if self.setup is not None:
                self.counts.replaced += 1
            band = self.variant.band * width
            impulse = bar.high if side == 1 else bar.low
            self.setup = Setup(side, t, ref.price, ref.price - band, ref.price + band, origin, width, impulse)

    def _advance_setup(self, t: int, bar: Kline) -> Signal | None:
        s = self.setup
        if s is None or t <= s.choch_index:
            return None
        side = s.side
        if (bar.low <= s.origin) if side == 1 else (bar.high >= s.origin):  # intrabar counts
            self.counts.invalidated += 1
            self.setup = None
            return None
        if t - s.choch_index > EXPIRY_BARS:
            self.counts.expired += 1
            self.setup = None
            return None
        if not s.touched:
            s.touched = bar.low <= s.band_high if side == 1 else bar.high >= s.band_low
        if s.touched and ((bar.close > s.band_high) if side == 1 else (bar.close < s.band_low)):
            self.setup = None
            stop = s.origin - side * STOP_BUFFER_ATR * s.atr
            risk = (bar.close - stop) * side
            reward = (s.impulse - bar.close) * side
            rr = reward / risk if risk > 0 else -math.inf
            if rr < MIN_RR:
                self.counts.rr_rejected += 1
                return None
            self.counts.emitted += 1
            self.counts.rr_taken.append(rr)
            return Signal(side, stop, target_r=rr, time_stop_bars=TIME_STOP_BARS)
        s.impulse = max(s.impulse, bar.high) if side == 1 else min(s.impulse, bar.low)
        return None


def choch_retest(variant: S9Variant, counts: Counts | None = None) -> Strategy:
    detector = Detector(variant, counts)
    seen = {"t": -1}

    def strategy(history: History) -> Signal | None:
        last = len(history) - 1
        signal = None
        for t in range(seen["t"] + 1, last + 1):
            signal = detector.step(history[t])
        seen["t"] = last
        return signal

    return strategy


# ----------------------------------------------------------------------------- generic runner and gate


def specs() -> list:
    from src.research_lab.hypotheses.registry import VariantSpec

    return [VariantSpec(v.variant_id, HYPOTHESIS, "short", Market.USDM, INTERVAL, v.params,
                        lambda funding, v=v: choch_retest(v), ("b",)) for v in S9_VARIANTS]


@dataclass(frozen=True, slots=True)
class SignalCount:
    upper: int  # every emitted signal
    lower: int  # signals at least TIME_STOP_BARS after the last counted one (each trade assumed to run to the time stop)
    counts: Counts


def count_signals(bars: Sequence[Kline], variant: S9Variant, start_ms: int, end_ms: int) -> SignalCount:
    """Outcome-blind count for the feasibility gate. No exits, no R after the signal."""
    counts = Counts()
    detector = Detector(variant, counts)
    upper = lower = 0
    last: int | None = None
    for t, bar in enumerate(bars):
        if bar.open_time >= end_ms:
            break
        signal = detector.step(bar)
        if signal is None or bar.open_time < start_ms:
            continue
        upper += 1
        if last is None or t - last >= TIME_STOP_BARS:
            lower += 1
            last = t
    return SignalCount(upper, lower, counts)

