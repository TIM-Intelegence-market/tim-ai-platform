"""Footprint of one candle from the S8 day profile (aggressive buy/sell volume per minute and price bin).

The S8 profile has one bin width per UTC day (about 0.05-0.1 % of the first price of the day). To keep 2020 and
2024 comparable, bins are merged to a target width relative to price (``fp_step_pct``) before anything is read.
Everything here is past-only: a footprint is built from the minutes of a *closed* candle.

Building blocks (names from the knowledge file, regime R01/R02/R05/R13):
- diagonal imbalance: buy at bin b against sell at bin b-1 (and sell at b against buy at b+1), ratio >= r,
  both sides > 0 ("ohne Null"; zeros are a separate signal, see ``zeros_at``)
- stacked imbalances: >= n consecutive bins with an imbalance on the same side
- absorption at an edge: the k outermost bins show aggressive volume into the edge that did not move price
  (sell >= a x buy at the low for a long; mirror for a short)
- zeros / finished auction at an extreme: the opposite side prints nothing on the outermost bins
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from src.research_lab.orderflow_ml.bars import E8, DayProfile


@dataclass(frozen=True, slots=True)
class Footprint:
    start: int
    minutes: int
    step: float                                  # merged bin width, USDT
    bins: tuple[tuple[int, int, int], ...]        # (merged bin index, buy_sats, sell_sats), ascending by bin, no gaps

    @property
    def empty(self) -> bool:
        return not self.bins

    @property
    def n_bins(self) -> int:
        return len(self.bins)

    def price_of(self, index: int) -> float:
        """Lower edge of a merged bin."""
        return index * self.step

    def imbalances(self, ratio: float) -> tuple[list[int], list[int]]:
        """(buy imbalance bins, sell imbalance bins): diagonal comparison, both sides > 0."""
        buys, sells = [], []
        for i, (b, buy, sell) in enumerate(self.bins):
            if i > 0:
                below_sell = self.bins[i - 1][2]
                if buy > 0 and below_sell > 0 and buy >= ratio * below_sell:
                    buys.append(b)
            if i + 1 < len(self.bins):
                above_buy = self.bins[i + 1][1]
                if sell > 0 and above_buy > 0 and sell >= ratio * above_buy:
                    sells.append(b)
        return buys, sells

    def stacks(self, ratio: float, min_len: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        """Runs of >= ``min_len`` consecutive imbalance bins per side, as (lowest bin, highest bin)."""
        buys, sells = self.imbalances(ratio)
        return _runs(buys, min_len), _runs(sells, min_len)

    def absorption(self, direction: int, levels: int, ratio: float) -> bool:
        """Long (+1): the ``levels`` lowest bins each show sell >= ratio x buy (sellers hitting bids that held).
        Short (-1): the highest bins show buy >= ratio x sell. Both sides must have printed: a one-sided edge is
        the zeros pattern (``zeros_at``), not absorption."""
        if len(self.bins) < levels:
            return False
        edge = self.bins[:levels] if direction > 0 else self.bins[-levels:]
        for _, buy, sell in edge:
            attacker, defender = (sell, buy) if direction > 0 else (buy, sell)
            if attacker <= 0 or defender <= 0 or attacker < ratio * defender:
                return False
        return True

    def zeros_at(self, direction: int, levels: int) -> bool:
        """Finished auction / zeros: for a short (-1) the ``levels`` highest bins print no aggressive sells
        (only buyers chased the top); for a long (+1) the lowest bins print no aggressive buys."""
        if len(self.bins) < levels:
            return False
        edge = self.bins[-levels:] if direction < 0 else self.bins[:levels]
        return all((sell == 0 and buy > 0) if direction < 0 else (buy == 0 and sell > 0) for _, buy, sell in edge)

    def unfinished(self, direction: int) -> bool:
        """Unfinished auction at the top (-1) or bottom (+1): both sides printed on the outermost bin."""
        if not self.bins:
            return False
        _, buy, sell = self.bins[-1] if direction < 0 else self.bins[0]
        return buy > 0 and sell > 0


def _runs(bins: list[int], min_len: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if not bins:
        return out
    start = prev = bins[0]
    for b in bins[1:]:
        if b != prev + 1:
            if prev - start + 1 >= min_len:
                out.append((start, prev))
            start = b
        prev = b
    if prev - start + 1 >= min_len:
        out.append((start, prev))
    return out


def merge_factor(width_e8: int, price: float, step_pct: float) -> int:
    """How many S8 bins make one merged bin of about ``step_pct`` of ``price`` (at least 1)."""
    if width_e8 <= 0 or price <= 0:
        return 1
    return max(1, round(step_pct * price * E8 / width_e8))


class DayFootprints:
    """Index of one day's profile by minute; builds the footprint of any closed candle of that day."""

    def __init__(self, profile: DayProfile, step_pct: float, reference_price: float) -> None:
        self.profile = profile
        self.factor = merge_factor(profile.width_e8, reference_price, step_pct)
        self.step = profile.width_e8 * self.factor / E8
        self.by_minute: dict[int, list[tuple[int, int, int]]] = {}
        for minute, bin_, buy, sell in profile.entries:
            self.by_minute.setdefault(minute, []).append((bin_, buy, sell))

    def candle(self, start_ms: int, minutes: int) -> Footprint:
        first = (start_ms - self.profile.day_start_ms) // 60_000
        return self.build(start_ms, minutes, range(first, first + minutes))

    def build(self, start_ms: int, minutes: int, minute_range: Iterable[int]) -> Footprint:
        acc: dict[int, list[int]] = {}
        for m in minute_range:
            for bin_, buy, sell in self.by_minute.get(m, ()):
                merged = bin_ // self.factor
                cell = acc.setdefault(merged, [0, 0])
                cell[0] += buy
                cell[1] += sell
        if not acc:
            return Footprint(start_ms, minutes, self.step, ())
        lo, hi = min(acc), max(acc)
        bins = tuple((b, *acc.get(b, [0, 0])) for b in range(lo, hi + 1))  # gaps inside the range count as zero
        return Footprint(start_ms, minutes, self.step, bins)
