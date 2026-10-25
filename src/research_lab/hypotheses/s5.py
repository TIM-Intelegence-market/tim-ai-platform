"""Study S5 (docs/research_lab/studien/S5_WINRATE_95_FUNDING_CARRY_PRAEREGISTRIERUNG.md): funding-carry episodes.

This module holds the frozen episode rules (section 4.1) and the outcome-blind episode
count for the feasibility gate (section 6.1). Funding rates are compared in integer
units of 1e-8, never as floats. Episode boundaries depend only on funding, the
minimum and maximum holding time, hourly gaps and section ends; prices are never
read here. The forced close (perp high >= 1.8 x entry) is a price rule and belongs to
the carry engine (package P4), not to the count.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from src.research_lab.data.parse import FundingRate, Kline

HOUR_MS = 3_600_000
DAY_MS = 86_400_000
RATE_UNIT = 100_000_000  # rates in 1e-8 units
MAX_HOLD_MS = 90 * DAY_MS
REENTRY_AFTER_EXIT = 2  # earliest entry: second funding time after the exit fill
REENTRY_AFTER_FORCED = 4  # after a forced close: fourth funding time (>= 24 h)
FORCED_CLOSE_FACTOR = 1.8
ENTRY_LAG_MS = HOUR_MS  # signal at funding time t, fill at the open of the bar starting at t + 1 h


def rate_units(rate: float) -> int:
    return round(rate * RATE_UNIT)


@dataclass(frozen=True, slots=True)
class S5Variant:
    variant_id: str
    theta_units: int  # entry when the funding rate is strictly above this (1e-8 units)
    hold_ms: int  # no regular exit before entry fill + hold


S5_VARIANTS: tuple[S5Variant, ...] = (
    S5Variant("S5-t01-h7", 10_000, 7 * DAY_MS),
    S5Variant("S5-t01-h21", 10_000, 21 * DAY_MS),
    S5Variant("S5-t03-h7", 30_000, 7 * DAY_MS),
    S5Variant("S5-t03-h21", 30_000, 21 * DAY_MS),
)


@dataclass(frozen=True, slots=True)
class Episode:
    signal_time: int  # funding time t whose rate triggered the entry
    entry_fill: int  # open time of the entry bar (t + 1 h)
    exit_fill: int  # open time of the exit bar, or the close of the last bar for gap/section_end
    reason: str  # regular, max_hold, gap, section_end

    @property
    def duration_ms(self) -> int:
        return self.exit_fill - self.entry_fill


@dataclass(slots=True)
class EpisodeCount:
    episodes: list[Episode] = field(default_factory=list)
    invalid_signals: int = 0  # entry bar missing (gap at t + 1 h) or beyond the section end
    skipped_locked: int = 0  # qualifying funding times inside the re-entry lock

    @property
    def by_reason(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for episode in self.episodes:
            out[episode.reason] = out.get(episode.reason, 0) + 1
        return dict(sorted(out.items()))


def common_hours(perp: Sequence[Kline], spot: Sequence[Kline]) -> list[int]:
    """Open times present in both series (section 3: an hour missing on one side is a gap for both)."""
    present = {b.open_time for b in perp} & {b.open_time for b in spot}
    return sorted(present)


def _gap_starts(hours: Sequence[int]) -> list[int]:
    """First missing hour after each present hour that is not followed by the next hour."""
    return [h + HOUR_MS for i, h in enumerate(hours) if i + 1 == len(hours) or hours[i + 1] != h + HOUR_MS]


def episodes(funding: Sequence[FundingRate], hours: Sequence[int], variant: S5Variant, start_ms: int, end_ms: int,
             *, forced_exits: Iterable[int] = ()) -> EpisodeCount:
    """Outcome-blind episodes of one instrument and one section [start_ms, end_ms).

    Entries need a signal time inside the section; no episode runs past end_ms (section_end).
    `forced_exits` (open times of bars where the engine forced a close) are only used by the
    engine-side replay to apply the longer re-entry lock; the gate passes nothing here."""
    hour_set = set(hours)
    hour_list = list(hours)
    gaps = _gap_starts(hour_list)
    times = [f.time for f in funding]
    units = [rate_units(f.rate) for f in funding]
    forced = set(forced_exits)
    count = EpisodeCount()
    allowed_from = 0  # index into funding times
    i = bisect_left(times, start_ms)
    while i < len(times) and times[i] < end_ms:
        t = times[i]
        if units[i] <= variant.theta_units:
            i += 1
            continue
        if i < allowed_from:
            count.skipped_locked += 1
            i += 1
            continue
        entry = t + ENTRY_LAG_MS
        if entry >= end_ms or entry not in hour_set:
            count.invalid_signals += 1
            i += 1
            continue
        exit_fill, reason = _exit(entry, variant, times, units, hour_list, hour_set, gaps, end_ms)
        count.episodes.append(Episode(t, entry, exit_fill, reason))
        lock = REENTRY_AFTER_FORCED if exit_fill in forced else REENTRY_AFTER_EXIT
        # first funding time strictly after the exit fill, then the lock counted from there
        allowed_from = bisect_right(times, exit_fill) + (lock - 1)
        i = max(i + 1, bisect_right(times, exit_fill))
    return count


def _exit(entry: int, variant: S5Variant, times: Sequence[int], units: Sequence[int], hours: Sequence[int],
          hour_set: set[int], gaps: Sequence[int], end_ms: int) -> tuple[int, str]:
    candidates: list[tuple[int, str]] = []
    # regular: first funding time >= entry + hold with rate <= 0, fill at the next hour
    j = bisect_left(times, entry + variant.hold_ms)
    while j < len(times):
        if units[j] <= 0:
            candidates.append((times[j] + ENTRY_LAG_MS, "regular"))
            break
        j += 1
    candidates.append((entry + MAX_HOLD_MS, "max_hold"))
    # gap: first missing hour after the entry bar; the episode closes on the last present bar
    g = bisect_right(gaps, entry)
    if g < len(gaps) and gaps[g] < end_ms:
        candidates.append((gaps[g], "gap"))
    candidates.append((end_ms, "section_end"))
    when, reason = min(candidates, key=lambda c: c[0])
    if reason in ("regular", "max_hold"):
        # the fill bar must exist; otherwise the gap rule applies at that hour
        if when >= end_ms:
            return end_ms, "section_end"
        if when not in hour_set:
            return when, "gap"
        return when, reason
    return when, reason


def monthly_counts(episodes_: Iterable[Episode]) -> dict[str, int]:
    """Episodes per calendar month of the entry fill (UTC), for the cluster-size estimate."""
    from datetime import datetime, timezone

    out: dict[str, int] = {}
    for episode in episodes_:
        key = datetime.fromtimestamp(episode.entry_fill / 1000, tz=timezone.utc).strftime("%Y-%m")
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
