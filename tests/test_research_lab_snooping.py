"""SPA/StepM data-snooping check (additional evaluation, PROTOKOLL change log 2026-10-23)."""
from __future__ import annotations

import random
import statistics

import pytest

from src.research_lab.backtest.engine import Trade
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.runner import RunConfig, snooping, snooping_lines
from src.research_lab.stats.snooping import (
    DAY_MS,
    daily_r,
    long_run_variance,
    period_report,
    snooping_test,
    stationary_blocks,
)


def _trade(signal: int, exit_: int, r: float) -> Trade:
    return Trade(signal_time=signal, entry_time=signal, exit_time=exit_, side=1, entry_price=1.0, exit_price=1.0,
                 stop=0.9, reason="test", bars_held=1, r=r, cost_r=0.0, funding_r=0.0)


def _correlated(n: int, k: int, seed: int, edges: dict[int, float] | None = None) -> dict[str, list[float]]:
    rng = random.Random(seed)
    common = [rng.gauss(0, 1) for _ in range(n)]
    out = {}
    for i in range(k):
        edge = (edges or {}).get(i, 0.0)
        out[f"v{i:02d}"] = [0.6 * c + 0.8 * rng.gauss(0, 1) + edge for c in common]
    return out


def test_daily_r_books_on_exit_day_within_signal_period() -> None:
    start = 10 * DAY_MS
    end = start + 5 * DAY_MS
    trades = [
        _trade(start + 1, start + DAY_MS + 5, 1.0),       # day 1
        _trade(start + 2, start + DAY_MS + 7, -0.5),      # same day, summed
        _trade(start + 3 * DAY_MS, end + 9 * DAY_MS, 2.0),  # closes after the end -> last day
        _trade(start - 1, start + 1, 9.0),                # signal before the period -> ignored
        _trade(end, end + 1, 9.0),                        # signal at the end (exclusive) -> ignored
    ]
    assert daily_r(trades, start, end) == [0.0, 0.5, 0.0, 0.0, 2.0]
    with pytest.raises(ValueError):
        daily_r(trades, start, start)


def test_stationary_blocks_are_reproducible_and_have_the_mean_length() -> None:
    draws = stationary_blocks(500, 10, 300, seed=3)
    assert draws == stationary_blocks(500, 10, 300, seed=3)
    assert draws != stationary_blocks(500, 10, 300, seed=4)
    assert all(sum(length for _, length in blocks) == 500 for blocks in draws)
    assert all(0 <= start < 500 for blocks in draws for start, _ in blocks)
    # Blocks cut at the end of a draw are shorter; inner blocks average about 10.
    inner = [length for blocks in draws for _, length in blocks[:-1]]
    assert 9.0 < statistics.fmean(inner) < 11.0
    assert all(length == 1 for blocks in stationary_blocks(50, 1, 5, seed=1) for _, length in blocks)
    with pytest.raises(ValueError):
        stationary_blocks(10, 0.5, 1, seed=1)


def test_long_run_variance_without_blocks_is_the_plain_variance() -> None:
    values = [random.Random(5).gauss(0, 2) for _ in range(200)]
    assert long_run_variance(values, 1) == pytest.approx(statistics.pvariance(values))
    # Positive autocorrelation raises the long-run variance.
    trend = [float(i // 20 % 2) for i in range(400)]
    assert long_run_variance(trend, 10) > 3 * statistics.pvariance(trend)


def test_input_errors() -> None:
    with pytest.raises(ValueError):
        snooping_test({}, seed=1)
    with pytest.raises(ValueError):
        snooping_test({"a": [0.0] * 10, "b": [0.0] * 11}, seed=1)
    with pytest.raises(ValueError):
        snooping_test({"a": [0.0, 1.0]}, seed=1)


def test_same_seed_same_result_and_flat_variants_are_harmless() -> None:
    series = _correlated(120, 4, seed=1)
    series["flat"] = [0.0] * 120  # never traded: zero variance must not divide by zero
    first = snooping_test(series, reps=99, seed=11)
    assert first == snooping_test(series, reps=99, seed=11)
    assert set(first.pvalues) == {"lower", "consistent", "upper"}
    assert first.pvalues["lower"] <= first.pvalues["consistent"] <= first.pvalues["upper"]
    assert "flat" not in first.superior


def test_no_edge_rarely_passes_and_a_planted_edge_is_found() -> None:
    """Size and power on synthetic correlated variants (like the R3 guard check, small for CI)."""
    null_hits = sum(snooping_test(_correlated(200, 6, seed=s), reps=199, seed=s).pvalues["consistent"] < 0.05
                    for s in range(60))
    assert null_hits <= 7  # about 5 % expected; 7 of 60 leaves room for bootstrap noise
    found = [snooping_test(_correlated(200, 6, seed=s, edges={2: 0.35}), reps=199, seed=s) for s in range(20)]
    assert sum(r.pvalues["consistent"] < 0.05 for r in found) >= 18
    assert sum(r.superior == ("v02",) for r in found) >= 15


def test_all_losing_variants_give_no_evidence() -> None:
    rng = random.Random(3)
    losers = {f"v{i}": [-0.5 + rng.gauss(0, 1) for _ in range(400)] for i in range(5)}
    losers["flat"] = [0.0] * 400
    result = snooping_test(losers, reps=199, seed=1)
    assert result.pvalues == {"lower": 1.0, "consistent": 1.0, "upper": 1.0}
    assert result.superior == ()


def test_studentizing_keeps_a_volatile_lucky_variant_from_winning() -> None:
    rng = random.Random(9)
    steady = [0.25 + rng.gauss(0, 1) for _ in range(250)]
    wild = [0.3 + rng.gauss(0, 12) for _ in range(250)]  # higher mean, but mostly noise
    result = snooping_test({"steady": steady, "wild": wild}, reps=299, seed=2)
    assert result.superior == ("steady",)


def test_period_report_skips_short_periods_and_names_its_window() -> None:
    start = 100 * DAY_MS
    assert period_report({"a": []}, start, start + 10 * DAY_MS, seed=1) is None
    assert period_report({}, start, start + 100 * DAY_MS, seed=1) is None
    trades = {"a": [_trade(start + i * DAY_MS, start + i * DAY_MS + 1, 0.1) for i in range(40)], "b": []}
    block = period_report(trades, start, start + 40 * DAY_MS, seed=1, reps=49)
    assert block is not None
    assert block["days"] == 40 and block["variants"] == 2 and block["reps"] == 49
    assert block["end"] == "1970-05-20"  # last day, not the exclusive end
    assert "keine Regel" in block["note"]


class _Spec:
    def __init__(self, variant_id: str, start: int):
        self.variant_id, self._start = variant_id, start


def test_runner_block_covers_train_and_validation_only(monkeypatch) -> None:
    import src.research_lab.runner as runner

    specs = [_Spec("a", VALIDATION_START_MS - 400 * DAY_MS), _Spec("b", VALIDATION_START_MS - 200 * DAY_MS)]
    monkeypatch.setattr(runner, "signal_start", lambda spec: spec._start)
    trades = {"a": [_trade(VALIDATION_START_MS + DAY_MS, HOLDOUT_START_MS + 5 * DAY_MS, 1.0)], "b": []}
    before = {k: list(v) for k, v in trades.items()}
    out = snooping(trades, specs, RunConfig(snooping_reps=49))
    assert set(out) == {"train", "validation"}
    assert out["train"]["days"] == 200  # shared window starts at the latest data start
    assert out["validation"]["days"] == (HOLDOUT_START_MS - VALIDATION_START_MS) // DAY_MS
    assert trades == before  # report only: the inputs stay untouched
    assert snooping(trades, specs, RunConfig(snooping_reps=0)) == {}
    text = "\n".join(snooping_lines(out))
    assert "Glückstest" in text and "keine Regel" in text and "| train " in text


@pytest.mark.local_env
def test_matches_arch_without_studentizing() -> None:
    """Oracle check against arch 8.0.0 (only installed in .venv-research)."""
    np = pytest.importorskip("numpy")
    arch_bootstrap = pytest.importorskip("arch.bootstrap")
    series = _correlated(600, 8, seed=4, edges={0: 0.12, 1: 0.05})
    data = np.array([series[k] for k in sorted(series)]).T
    ours = snooping_test(series, block_size=10, reps=5000, seed=7, studentize=False)
    spa = arch_bootstrap.SPA(np.zeros(600), -data, block_size=10, reps=5000, seed=7)
    spa.compute()
    for kind in ("lower", "consistent", "upper"):
        assert abs(ours.pvalues[kind] - float(spa.pvalues[kind])) <= 0.02
    step = arch_bootstrap.StepM(np.zeros(600), -data, block_size=10, reps=5000, size=0.05, seed=7)
    step.compute()
    assert list(ours.superior) == [sorted(series)[i] for i in step.superior_models]
    spa._compute_variance()
    for i, name in enumerate(sorted(series)):
        assert long_run_variance(series[name], 10) == pytest.approx(float(spa._loss_diff_var[i]), rel=1e-9)
