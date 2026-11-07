"""Locations an orderflow trader marks before the session: previous-day value (trade volume profile),
previous-day high/low, naked POCs, previous-session high/low and the initial balance.

All of it is computed from completed days or completed sessions only.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.research_lab.of2.config import Config
from src.research_lab.orderflow_ml.bars import E8, DayProfile, MinuteBar
from src.research_lab.orderflow_ml.profile import value_area, volume_histogram


@dataclass(frozen=True, slots=True)
class DaySummary:
    day_start: int
    high: float
    low: float
    close: float
    poc: float   # centre of the POC bin, USDT
    val: float   # lower edge of the value area
    vah: float   # upper edge of the value area

    @property
    def va_width(self) -> float:
        return self.vah - self.val


def day_summary(bars: Sequence[MinuteBar], profile: DayProfile) -> DaySummary | None:
    """Value area (70 %, single-row rule as in S8) and extremes of one completed UTC day; None without trades."""
    traded = [b for b in bars if b.has_trades]
    if not traded or not profile.width_e8:
        return None
    va = value_area(volume_histogram(profile.entries))
    if va is None:
        return None
    poc_bin, lo_bin, hi_bin = va
    width = profile.width_e8
    return DaySummary(
        profile.day_start_ms, max(b.high_price_e8 for b in traded) / E8, min(b.low_price_e8 for b in traded) / E8,
        traded[-1].last_price_e8 / E8, (poc_bin * width + width // 2) / E8, lo_bin * width / E8, (hi_bin + 1) * width / E8,
    )


def naked_pocs(history: Sequence[DaySummary], days: int) -> list[float]:
    """POCs of the last ``days`` completed days before the most recent one that no later completed day traded through.

    ``history[-1]`` is yesterday; its own POC is a level anyway (DaySummary.poc) and is not repeated here.
    """
    naked: list[float] = []
    older = history[:-1][-days:]
    for i, day in enumerate(older):
        later = list(older[i + 1:]) + list(history[-1:])
        if all(not (d.low <= day.poc <= d.high) for d in later):
            naked.append(day.poc)
    return naked


@dataclass
class SessionState:
    """Running extremes and initial balance of the current session; frozen into ``prev`` when the session ends."""

    name: str
    start: int
    high: float = 0.0
    low: float = 0.0
    seen: bool = False
    ib_high: float = 0.0
    ib_low: float = 0.0
    ib_seen: bool = False
    ib_done: bool = False

    def push(self, bar: MinuteBar, cfg: Config) -> None:
        if not bar.has_trades:
            if bar.window_start_ms >= self.start + cfg.ib_minutes * 60_000:
                self.ib_done = True
            return
        high, low = bar.high_price_e8 / E8, bar.low_price_e8 / E8
        if not self.seen:
            self.high, self.low, self.seen = high, low, True
        else:
            self.high, self.low = max(self.high, high), min(self.low, low)
        if bar.window_start_ms < self.start + cfg.ib_minutes * 60_000:
            if not self.ib_seen:
                self.ib_high, self.ib_low, self.ib_seen = high, low, True
            else:
                self.ib_high, self.ib_low = max(self.ib_high, high), min(self.ib_low, low)
        else:
            self.ib_done = True

    @property
    def ib_range(self) -> float | None:
        return self.ib_high - self.ib_low if self.ib_done and self.ib_seen else None


def regime(ib_range: float | None, past_ranges: Sequence[float], cfg: Config) -> str:
    """TREND (small IB), RANGE (wide IB), NEUTRAL, or UNBEKANNT without a complete IB or history (R36)."""
    if ib_range is None or len(past_ranges) < cfg.ib_history:
        return "UNBEKANNT"
    mean = sum(past_ranges[-cfg.ib_history:]) / cfg.ib_history
    if mean <= 0:
        return "UNBEKANNT"
    ratio = ib_range / mean
    if ratio < cfg.ib_trend_below:
        return "TREND"
    if ratio > cfg.ib_range_above:
        return "RANGE"
    return "NEUTRAL"


@dataclass(frozen=True, slots=True)
class Levels:
    """Everything a detector may look at: yesterday, naked POCs, the previous session's extremes."""

    prev_day: DaySummary
    npocs: tuple[float, ...] = ()
    prev_session_high: float | None = None
    prev_session_low: float | None = None

    def sweep_levels(self, direction: int) -> list[tuple[str, float]]:
        """Levels a long (+1) sweeps below / a short (-1) sweeps above, named."""
        d = self.prev_day
        if direction > 0:
            out = [("VAL", d.val), ("TAG_TIEF", d.low), ("POC", d.poc)]
            if self.prev_session_low is not None:
                out.append(("SESSION_TIEF", self.prev_session_low))
        else:
            out = [("VAH", d.vah), ("TAG_HOCH", d.high), ("POC", d.poc)]
            if self.prev_session_high is not None:
                out.append(("SESSION_HOCH", self.prev_session_high))
        out += [("NPOC", p) for p in self.npocs]
        return out

    def targets(self, direction: int, price: float) -> list[tuple[str, float]]:
        """Opposing levels beyond ``price`` in trade direction, nearest first (first obstacle = target, R72)."""
        d = self.prev_day
        pool = [("POC", d.poc), ("VAH", d.vah), ("VAL", d.val), ("TAG_HOCH", d.high), ("TAG_TIEF", d.low)]
        pool += [("NPOC", p) for p in self.npocs]
        if self.prev_session_high is not None:
            pool.append(("SESSION_HOCH", self.prev_session_high))
        if self.prev_session_low is not None:
            pool.append(("SESSION_TIEF", self.prev_session_low))
        ahead = [(n, p) for n, p in pool if (p > price if direction > 0 else p < price)]
        return sorted(ahead, key=lambda item: abs(item[1] - price))
