"""The statistical guard: train -> validation -> one holdout run (protocol section 8).

This module runs the selection rules on already registered variants. The
neighbourhood and walk-forward rules need a parameter grid and are applied by
the R4 runner with the helpers in inference.py; here they are out of scope.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from src.research_lab.backtest.engine import Strategy, Trade, run_backtest
from src.research_lab.backtest.metrics import Summary, summarize
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.data.store import HoldoutPermission
from src.research_lab.protocol import (
    BASE_COSTS,
    FAMILY_ALPHA,
    HOLDOUT_START_MS,
    MAX_DRAWDOWN_LIMIT,
    RANDOM_RUNS,
    VALIDATION_START_MS,
    CostModel,
)
from src.research_lab.stats.inference import holm, year_stability
from src.research_lab.stats.random_entry import atr_at_signal, atr_series, random_entry_pvalue

PASSED = "BESTANDEN"
FAILED = "NICHT BESTANDEN"
NO_VERDICT = "KEIN URTEIL"
FAILED_TRAIN = "failed_train"
FAILED_VALIDATION = "failed_validation"
NOT_SELECTED = "not_selected"


@dataclass(frozen=True, slots=True)
class Variant:
    variant_id: str
    hypothesis: str
    strategy: Strategy


@dataclass(frozen=True, slots=True)
class Periods:
    validation_start: int = VALIDATION_START_MS
    holdout_start: int = HOLDOUT_START_MS
    holdout_end: int | None = None


@dataclass(frozen=True, slots=True)
class GuardConfig:
    min_trades_train: int
    min_trades_holdout: int
    random_runs: int = RANDOM_RUNS
    seed: int = 20260929
    costs: CostModel = BASE_COSTS
    drawdown_limit: float = MAX_DRAWDOWN_LIMIT
    min_profit_factor: float = 1.1
    train_p: float = 0.10
    validation_p: float = 0.05
    alpha: float = FAMILY_ALPHA
    max_candidates_per_hypothesis: int = 2


@dataclass(slots=True)
class StageResult:
    summary: Summary
    trades: list[Trade]
    p: float | None = None


@dataclass(slots=True)
class GuardReport:
    verdicts: dict[str, str] = field(default_factory=dict)
    stages: dict[str, dict[str, StageResult]] = field(default_factory=dict)
    candidates: list[str] = field(default_factory=list)


def _stage(bars, variant, interval_ms, start, end, config, funding, atr_values, seed_offset, need_p) -> StageResult:
    result = run_backtest(bars, variant.strategy, interval_ms, costs=config.costs, funding=funding,
                          start_ms=start, end_ms=end, atr_at_signal=atr_at_signal)
    stage = StageResult(summarize(result.trades), result.trades)
    if need_p(stage.summary):
        stage.p = random_entry_pvalue(bars, result.trades, interval_ms, runs=config.random_runs,
                                      seed=config.seed + seed_offset, costs=config.costs, funding=funding,
                                      start_ms=start, end_ms=end, atr_values=atr_values)
    return stage


def run_guard(
    bars: Sequence[Kline],
    variants: Sequence[Variant],
    interval_ms: int,
    *,
    m: int,
    config: GuardConfig,
    periods: Periods = Periods(),
    funding: Sequence[FundingRate] = (),
    holdout: HoldoutPermission | None = None,
) -> GuardReport:
    """Apply the selection rules. Train and validation never see holdout bars.

    Without a holdout permission the run stops after freezing the candidate
    list. With it (from claim_holdout) the recomputed candidates and m must
    match what the lock froze, and the holdout is evaluated once."""
    report = GuardReport()
    if holdout is not None and m != holdout.m:
        raise ValueError("m differs from the register size frozen in the holdout lock")
    before_holdout = [b for b in bars if b.open_time < periods.holdout_start]
    atr_before = atr_series(before_holdout)
    validation_scores: dict[str, float] = {}

    for number, variant in enumerate(variants):
        train = _stage(before_holdout, variant, interval_ms, None, periods.validation_start, config, funding, atr_before,
                       3 * number, lambda s: s.expectancy_r > 0 and s.trades >= config.min_trades_train)
        report.stages[variant.variant_id] = {"train": train}
        if train.p is None or train.p >= config.train_p:
            report.verdicts[variant.variant_id] = FAILED_TRAIN
            continue
        validation = _stage(before_holdout, variant, interval_ms, periods.validation_start, periods.holdout_start, config,
                            funding, atr_before, 3 * number + 1,
                            lambda s: s.expectancy_r > 0 and s.trades >= config.min_trades_train / 2)
        report.stages[variant.variant_id]["validation"] = validation
        summary = validation.summary
        combined = summarize(train.trades + validation.trades)
        if (validation.p is None or validation.p >= config.validation_p
                or summary.profit_factor <= config.min_profit_factor
                or summary.max_drawdown_pct > config.drawdown_limit
                or not year_stability(combined.expectancy_by_year)):
            report.verdicts[variant.variant_id] = FAILED_VALIDATION
            continue
        validation_scores[variant.variant_id] = summary.expectancy_r

    by_hypothesis: dict[str, list[str]] = {}
    for variant in variants:
        if variant.variant_id in validation_scores:
            by_hypothesis.setdefault(variant.hypothesis, []).append(variant.variant_id)
    for ids in by_hypothesis.values():
        ranked = sorted(ids, key=lambda v: (-validation_scores[v], v))
        report.candidates.extend(ranked[: config.max_candidates_per_hypothesis])
        for dropped in ranked[config.max_candidates_per_hypothesis:]:
            report.verdicts[dropped] = NOT_SELECTED
    if holdout is None or not report.candidates:
        return report
    if tuple(sorted(report.candidates)) != holdout.candidates:
        raise ValueError("candidates differ from the list frozen in the holdout lock")

    atr_all = atr_series(bars)
    pvalues: dict[str, float] = {}
    for number, variant in enumerate(variants):
        if variant.variant_id not in report.candidates:
            continue
        holdout = _stage(bars, variant, interval_ms, periods.holdout_start, periods.holdout_end, config, funding, atr_all,
                         3 * number + 2, lambda s: s.trades > 0)
        report.stages[variant.variant_id]["holdout"] = holdout
        pvalues[variant.variant_id] = holdout.p if holdout.p is not None else 1.0
    significant = holm(pvalues, m, config.alpha)
    for variant_id in pvalues:
        summary = report.stages[variant_id]["holdout"].summary
        if summary.trades < config.min_trades_holdout:
            report.verdicts[variant_id] = NO_VERDICT
        elif summary.expectancy_r > 0 and variant_id in significant and summary.max_drawdown_pct <= config.drawdown_limit:
            report.verdicts[variant_id] = PASSED
        else:
            report.verdicts[variant_id] = FAILED
    return report
