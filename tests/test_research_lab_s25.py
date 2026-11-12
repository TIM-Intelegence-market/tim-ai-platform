import json
import statistics

import pytest

from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.studies import s25

P = s25.HORIZON.period_ms
T0 = VALIDATION_START_MS


def flat_series(sigma=1.0, days=200, start=T0 - 200 * s25.DAY_MS):
    n = days * s25.HORIZON.per_day
    starts = [start + i * P for i in range(n)]
    return s25.SigmaSeries(starts, [sigma] * n)


def test_weight_clip_and_reference():
    s = flat_series(1.0)
    entry = s.starts[-1]
    assert s25.weight(s, entry) == pytest.approx(1.0)
    wild = s25.SigmaSeries(s.starts, s.sigmas[:-1] + [4.0])
    assert s25.weight(wild, entry) == s25.W_MIN  # 1/4 clipped to 0.5
    calm = s25.SigmaSeries(s.starts, s.sigmas[:-1] + [0.25])
    assert s25.weight(calm, entry) == s25.W_MAX


def test_reference_uses_only_the_past_and_needs_min_days():
    s = flat_series(1.0, days=200)
    too_early = s.starts[s25.REF_MIN_DAYS * s25.HORIZON.per_day - 1]
    assert s.reference(too_early) is None
    entry = s.starts[-1]
    future = s25.SigmaSeries(s.starts + [entry + P], s.sigmas + [100.0])
    assert future.reference(entry) == s.reference(entry)  # a later period does not change the reference


def test_no_forecast_no_weight():
    s = flat_series()
    assert s25.weight(s, s.starts[-1] + 7) is None  # not a period start


def _trade(symbol, entry, exit_, r, variant=s25.VARIANT, section="validation"):
    return {"symbol": symbol, "entry_time": entry, "exit_time": exit_, "r": r, "cost_r": 0.05,
            "variant": variant, "section": section}


def test_attach_and_count_are_consistent_and_count_ignores_r():
    s = flat_series()
    sigmas = {"BTCUSDT": s}
    good = _trade("BTCUSDT", s.starts[-1], s.starts[-1] + 3 * P, 1.0)
    early = _trade("BTCUSDT", s.starts[10], s.starts[12], -1.0)
    other = _trade("SOLUSDT", s.starts[-1], s.starts[-1] + P, 2.0)
    with_w, missing = s25.attach([good, early, other], sigmas)
    assert len(with_w) == 1 and missing == 2
    blind = [{k: v for k, v in t.items() if k not in ("r", "cost_r", "exit_time")} for t in (good, early, other)]
    rows = s25.count_rows(blind, sigmas)
    assert rows[s25.VARIANT]["validation"] == {
        "trades": 3, "with_weight": 1,
        "by_symbol": {"BTCUSDT": {"trades": 2, "with_weight": 1}, "SOLUSDT": {"trades": 1, "with_weight": 0}},
    }


def test_holdout_trade_is_refused():
    with pytest.raises(ValueError):
        s25.select([_trade("BTCUSDT", HOLDOUT_START_MS, HOLDOUT_START_MS + P, 1.0)], s25.VARIANT, "validation")


def test_weighted_keeps_mean_size():
    w = [0.5, 1.0, 2.0]
    out = s25.weighted([1.0, 1.0, 1.0], w)
    assert statistics.fmean(out) == pytest.approx(1.0)


def test_garch_weights_that_shrink_losses_lower_drawdown_and_placebo_detects_it():
    results = [1.0, -1.0] * 60
    weights = [1.0 if r > 0 else 0.5 for r in results]  # small size exactly on the losers
    trades = [s25.WTrade("BTCUSDT", i, i, r, 0.0, w) for i, (r, w) in enumerate(zip(results, weights))]
    res = s25.section_result(trades)
    assert res["garch"]["drawdown"] < res["fixed"]["drawdown"]
    assert res["placebo_p"] <= 0.05
    assert s25.placebo_p(results, weights, res["garch"]["drawdown"]) == res["placebo_p"]  # fixed seed


def test_verdict_branches():
    good = {"fixed": {"drawdown": 10.0, "r_per_risk": 0.02}, "garch": {"drawdown": 8.0, "r_per_risk": 0.03},
            "placebo_p": 0.01}
    train = {"fixed": {"drawdown": 10.0}, "garch": {"drawdown": 9.0}}
    assert s25.verdict(train, good, 100)["verdict"] == "BESTANDEN"
    assert s25.verdict(train, good, 79)["verdict"] == "KEIN URTEIL"
    weak = {**good, "garch": {"drawdown": 9.5, "r_per_risk": 0.03}}
    assert s25.verdict(train, weak, 100)["verdict"] == "NICHT BESTANDEN"
    lucky = {**good, "placebo_p": 0.2}
    assert s25.verdict(train, lucky, 100)["verdict"] == "NICHT BESTANDEN"


def test_run_is_locked_before_freeze(tmp_path):
    assert s25.FROZEN is False
    trades = tmp_path / "t.json"
    trades.write_text(json.dumps([]))
    assert s25.main(["run", "--trades", str(trades), "--out", str(tmp_path / "out")]) == 2
    assert not (tmp_path / "out").exists()
