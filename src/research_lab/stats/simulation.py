"""Check of the guard itself on synthetic series (protocol section 7.4).

Noise series have no edge: the whole pipeline may pass at most 5 % of them.
Edge series carry about +0.2 R per trade after costs: the pipeline must pass
at least 80 % of them.

Deviations from a real run, recorded in the protocol change log: 99 instead of
10 000 random runs (runtime; the p floor of 0.01 stays below every Holm
threshold used here), m = 4 instead of 48, and no walk-forward or neighbourhood
rule because the synthetic variants have no parameter grid. The simulation
issues its own holdout permission per series instead of writing lock files.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.research_lab.data.store import _issue_permission
from src.research_lab.stats.guard import PASSED, GuardConfig, Periods, Variant, run_guard
from src.research_lab.synthetic import marker_strategy, synthetic_series

BAR_MS = 4 * 3_600_000  # 12 000 four-hour bars span about 5.5 years
SERIES_BARS = 12_000
VALIDATION_BAR = 6_000
HOLDOUT_BAR = 9_000
# Calibrated so that the marker strategy earns about +0.2 R per trade after base costs.
EDGE_02R = 0.28
REGISTER_SIZE = 4  # two tested variants plus two already discarded entries


@dataclass(frozen=True, slots=True)
class SimulationResult:
    series: int
    passed: int

    @property
    def rate(self) -> float:
        return self.passed / self.series


def simulate(series: int, *, edge: float, random_runs: int = 99, seed: int = 0) -> SimulationResult:
    start = 1_514_764_800_000
    periods = Periods(start + VALIDATION_BAR * BAR_MS, start + HOLDOUT_BAR * BAR_MS, start + SERIES_BARS * BAR_MS)
    config = GuardConfig(min_trades_train=100, min_trades_holdout=50, random_runs=random_runs, seed=seed)
    variants = [
        Variant("marker-t3", "marker", marker_strategy(time_stop_bars=3)),
        Variant("marker-t5", "marker", marker_strategy(time_stop_bars=5)),
    ]
    passed = 0
    for number in range(series):
        bars = synthetic_series(SERIES_BARS, seed=seed * 100_003 + number, start_ms=start, interval_ms=BAR_MS, edge=edge)
        report = run_guard(bars, variants, BAR_MS, m=REGISTER_SIZE, config=config, periods=periods)
        if report.candidates:
            permission = _issue_permission("simulation", tuple(sorted(report.candidates)), REGISTER_SIZE)
            report = run_guard(bars, variants, BAR_MS, m=REGISTER_SIZE, config=config, periods=periods, holdout=permission)
        passed += any(verdict == PASSED for verdict in report.verdicts.values())
    return SimulationResult(series, passed)
