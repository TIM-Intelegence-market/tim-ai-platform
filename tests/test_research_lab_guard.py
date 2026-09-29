from __future__ import annotations

import statistics

from src.research_lab.backtest.engine import Signal, run_backtest
from src.research_lab.backtest.metrics import summarize
from src.research_lab.stats.guard import (
    FAILED_TRAIN,
    NO_VERDICT,
    NOT_SELECTED,
    PASSED,
    GuardConfig,
    Periods,
    Variant,
    run_guard,
)
from src.research_lab.stats.random_entry import atr_at_signal
from src.research_lab.stats.simulation import BAR_MS, EDGE_02R, simulate
from src.research_lab.synthetic import marker_strategy, synthetic_series

START = 1_514_764_800_000


def periods(validation_bar: int, holdout_bar: int, end_bar: int) -> Periods:
    return Periods(START + validation_bar * BAR_MS, START + holdout_bar * BAR_MS, START + end_bar * BAR_MS)


def test_edge_calibration_is_about_two_tenths_r() -> None:
    means = [
        summarize(run_backtest(synthetic_series(12_000, seed=s, start_ms=START, interval_ms=BAR_MS, edge=EDGE_02R),
                               marker_strategy(), BAR_MS, atr_at_signal=atr_at_signal).trades).expectancy_r
        for s in range(5)
    ]
    assert 0.15 < statistics.fmean(means) < 0.25


def test_guard_false_positive_rate_on_200_noise_series() -> None:
    result = simulate(200, edge=0.0)
    assert result.rate <= 0.05


def test_guard_finds_built_in_edge_in_200_series() -> None:
    result = simulate(200, edge=EDGE_02R)
    assert result.rate >= 0.80


def test_train_and_validation_never_see_holdout_bars() -> None:
    bars = synthetic_series(3_000, seed=4, start_ms=START, interval_ms=BAR_MS, edge=EDGE_02R)
    holdout_start = START + 2_500 * BAR_MS
    seen: list[int] = []

    def spying(history):
        seen.append(history[-1].open_time)
        return marker_strategy()(history)

    config = GuardConfig(min_trades_train=20, min_trades_holdout=10, random_runs=19)
    run_guard(bars, [Variant("spy", "h", spying)], BAR_MS, m=1, config=config,
              periods=Periods(START + 2_000 * BAR_MS, holdout_start), run_holdout=False)
    assert seen and max(seen) < holdout_start


def test_verdicts_for_thin_holdout_and_extra_candidates() -> None:
    bars = synthetic_series(12_000, seed=8, start_ms=START, interval_ms=BAR_MS, edge=EDGE_02R)
    config = GuardConfig(min_trades_train=100, min_trades_holdout=10_000, random_runs=99, max_candidates_per_hypothesis=1)
    variants = [
        Variant("t3", "marker", marker_strategy(time_stop_bars=3)),
        Variant("t5", "marker", marker_strategy(time_stop_bars=5)),
        Variant("never", "other", lambda history: None),
    ]
    report = run_guard(bars, variants, BAR_MS, m=3, config=config, periods=periods(6_000, 9_000, 12_000))
    assert report.verdicts["never"] == FAILED_TRAIN
    assert len(report.candidates) == 1
    (candidate,) = report.candidates
    assert report.verdicts[candidate] == NO_VERDICT  # holdout minimum not reached
    assert NOT_SELECTED in report.verdicts.values()
    assert PASSED not in report.verdicts.values()


def test_losing_short_strategy_fails_train() -> None:
    bars = synthetic_series(6_000, seed=9, start_ms=START, interval_ms=BAR_MS, edge=EDGE_02R)

    def short_markers(history):
        signal = marker_strategy()(history)
        return None if signal is None else Signal(-1, history[-1].close + (history[-1].close - signal.stop), target_r=1.0, time_stop_bars=3)

    config = GuardConfig(min_trades_train=50, min_trades_holdout=10, random_runs=19)
    report = run_guard(bars, [Variant("short", "h", short_markers)], BAR_MS, m=1, config=config, periods=periods(4_000, 5_000, 6_000))
    assert report.verdicts["short"] == FAILED_TRAIN
