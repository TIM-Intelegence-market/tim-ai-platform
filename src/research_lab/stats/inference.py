"""Multiple-testing correction, bootstrap and robustness rules (protocol 5, 7, 9)."""
from __future__ import annotations

import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from src.research_lab.backtest.engine import Trade
from src.research_lab.protocol import FAMILY_ALPHA


def holm(pvalues: Mapping[str, float], m: int, alpha: float = FAMILY_ALPHA) -> set[str]:
    """Holm-Bonferroni. m counts every register entry; untested ones count as p = 1."""
    if m < len(pvalues):
        raise ValueError("m cannot be smaller than the number of tested variants")
    rejected: set[str] = set()
    for rank, (variant, p) in enumerate(sorted(pvalues.items(), key=lambda item: (item[1], item[0]))):
        if p > alpha / (m - rank):
            break
        rejected.add(variant)
    return rejected


def _month(trade: Trade) -> tuple[int, int]:
    stamp = datetime.fromtimestamp(trade.entry_time / 1000, tz=timezone.utc)
    return stamp.year, stamp.month


def month_block_bootstrap_ci(trades: Sequence[Trade], *, draws: int = 10_000, seed: int, level: float = 0.95) -> tuple[float, float]:
    """Confidence interval of the mean R, resampling whole calendar months."""
    blocks: dict[tuple[int, int], list[float]] = {}
    for trade in trades:
        blocks.setdefault(_month(trade), []).append(trade.r)
    if not blocks:
        raise ValueError("no trades")
    groups = list(blocks.values())
    rng = random.Random(seed)
    means = []
    for _ in range(draws):
        sample = [r for _ in groups for r in rng.choice(groups)]
        means.append(statistics.fmean(sample))
    return _quantiles(means, level)


def iid_band(results: Sequence[float], n: int, *, draws: int = 10_000, seed: int, level: float = 0.90) -> tuple[float, float]:
    """Expected band of the mean over n trades (paper phase, 5th to 95th percentile)."""
    if not results or n < 1:
        raise ValueError("need results and n >= 1")
    rng = random.Random(seed)
    means = [statistics.fmean(rng.choices(results, k=n)) for _ in range(draws)]
    return _quantiles(means, level)


def _quantiles(values: list[float], level: float) -> tuple[float, float]:
    values.sort()
    tail = (1 - level) / 2
    low = values[int(tail * (len(values) - 1))]
    high = values[int((1 - tail) * (len(values) - 1))]
    return low, high


def year_stability(by_year: Mapping[int, tuple[int, float]], *, min_trades: int = 5, share: float = 0.6) -> bool:
    """Expectancy > 0 in at least `share` of the years with at least `min_trades` trades."""
    years = [mean for count, mean in by_year.values() if count >= min_trades]
    return bool(years) and sum(mean > 0 for mean in years) >= share * len(years)


def neighbours_positive(grid: Mapping[str, Sequence], expectancy: Mapping[tuple, float], point: tuple) -> bool:
    """Direct neighbours along each ordered numeric parameter must also be > 0.

    `grid` maps parameter name to its values in order; categorical parameters
    (direction, weekday, session, interval) must not be listed here."""
    names = list(grid)
    for axis, name in enumerate(names):
        values = list(grid[name])
        position = values.index(point[axis])
        for step in (-1, 1):
            if 0 <= position + step < len(values):
                neighbour = point[:axis] + (values[position + step],) + point[axis + 1:]
                if expectancy.get(neighbour, float("-inf")) <= 0:
                    return False
    return True


@dataclass(frozen=True, slots=True)
class Window:
    fit_start: int
    fit_end: int
    test_end: int


def walk_forward_windows(start_ms: int, end_ms: int, *, fit_months: int = 24, test_months: int = 6) -> list[Window]:
    def add(ms: int, count: int) -> int:
        stamp = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        month = stamp.month - 1 + count
        return int(stamp.replace(year=stamp.year + month // 12, month=month % 12 + 1).timestamp() * 1000)

    windows = []
    fit_start = start_ms
    while add(fit_start, fit_months + test_months) <= end_ms:
        fit_end = add(fit_start, fit_months)
        windows.append(Window(fit_start, fit_end, add(fit_end, test_months)))
        fit_start = add(fit_start, test_months)
    return windows


def walk_forward(variant_trades: Mapping[str, Sequence[Trade]], windows: Sequence[Window]) -> tuple[float, list[str]]:
    """Choose the best variant of one hypothesis per fit window, measure it only in
    the following test window. Returns (chained mean R, chosen variant per window)."""
    chained: list[float] = []
    chosen = []
    for window in windows:
        def fit_mean(variant: str) -> float:
            rs = [t.r for t in variant_trades[variant] if window.fit_start <= t.entry_time < window.fit_end]
            return statistics.fmean(rs) if rs else float("-inf")

        best = max(sorted(variant_trades), key=fit_mean)
        chosen.append(best)
        chained.extend(t.r for t in variant_trades[best] if window.fit_end <= t.entry_time < window.test_end)
    return (statistics.fmean(chained) if chained else 0.0), chosen

