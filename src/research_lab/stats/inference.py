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


def known_at(trades: Sequence[Trade], start_ms: int, end_ms: int) -> list[Trade]:
    """Trades whose signal fired in [start_ms, end_ms) and whose result was already
    known at end_ms (exit_time <= end_ms). Only these may inform a decision taken
    at end_ms; a trade still open at the cut-off carries its future outcome."""
    return [t for t in trades if start_ms <= t.signal_time < end_ms and t.exit_time <= end_ms]


def signalled_in(trades: Sequence[Trade], start_ms: int, end_ms: int) -> list[Trade]:
    """Trades whose signal fired in [start_ms, end_ms) (attribution by signal time)."""
    return [t for t in trades if start_ms <= t.signal_time < end_ms]


FORCED_CLOSE = "end"  # engine reason for a position closed on the last bar of the data


def section_trades(trades: Sequence[Trade], start_ms: int | None, end_ms: int | None) -> list[Trade]:
    """Trades that count for the section [start_ms, end_ms) under protocol 3.2 (version 1.2).

    A trade belongs to the section in which its signal fired, but only if its exit was
    fixed by the exit rules (4.2) no later than the section end. A trade still open at the
    section end would carry prices from the next section into this one (train results
    from validation prices, validation results from holdout prices), so it counts for no
    section. A position the engine force-closed on the last bar (reason "end") is open in
    this sense too: its exit was not a rule exit. None means an open-ended boundary."""
    kept = []
    for t in trades:
        if start_ms is not None and t.signal_time < start_ms:
            continue
        if end_ms is not None and (t.signal_time >= end_ms or t.exit_time > end_ms):
            continue
        if t.reason == FORCED_CLOSE:
            continue
        kept.append(t)
    return kept


def open_at_section_end(trades: Sequence[Trade], start_ms: int | None, end_ms: int | None) -> int:
    """How many trades signalled in the section were dropped by section_trades (3.2 embargo)."""
    signalled = [t for t in trades if (start_ms is None or t.signal_time >= start_ms)
                 and (end_ms is None or t.signal_time < end_ms)]
    return len(signalled) - len(section_trades(trades, start_ms, end_ms))


def walk_forward(variant_trades: Mapping[str, Sequence[Trade]], windows: Sequence[Window]) -> tuple[float, list[str]]:
    """Choose the best variant of one hypothesis per fit window, measure it only in
    the following test window. Returns (chained mean R, chosen variant per window).

    The choice at fit_end uses only trades that were closed by then (known_at).
    A trade signalled inside the fit window but still open at fit_end is neither
    part of the fit (its result lies in the future) nor of the test window (its
    signal predates it); it is skipped, so the test window holds only trades a
    forward-looking operator would have taken after the choice (protocol 7.3,
    method version 1.1)."""
    chained: list[float] = []
    chosen = []
    for window in windows:
        def fit_mean(variant: str) -> float:
            rs = [t.r for t in known_at(variant_trades[variant], window.fit_start, window.fit_end)]
            return statistics.fmean(rs) if rs else float("-inf")

        best = max(sorted(variant_trades), key=fit_mean)
        chosen.append(best)
        chained.extend(t.r for t in signalled_in(variant_trades[best], window.fit_end, window.test_end))
    return (statistics.fmean(chained) if chained else 0.0), chosen

