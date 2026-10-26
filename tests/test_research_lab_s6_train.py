"""Study S6 training/validation rules, robustness and re-pricing (sections 5.1, 5.3, 5.4)."""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

from src.research_lab.hypotheses import s6
from src.research_lab.hypotheses.s6 import LONG, SHORT, NOMINAL, STOP_FRACTION, Trade
from src.research_lab.studies import s6_eval as ev
from tests.test_research_lab_s6_eval import trade
from tests.test_research_lab_s6_latency import _market

T0 = 1_577_836_800_000
M = 60_000
MONTH = 31 * 86_400_000


def test_reprice_to_protocol_costs_changes_only_the_fee_legs() -> None:
    bars = _market(2_500)
    end = bars[-1].open_time + M
    sim = s6.simulate(bars, [], s6.S6_VARIANTS[0], T0, end)
    assert sim.trades, "fixture market must produce trades"
    for t in sim.trades:
        p = ev.reprice(t, s6.BASE_COSTS, ev.PROTOCOL_COSTS)
        assert p.reason == t.reason and p.entry_fill == t.entry_fill and p.exit_fill == t.exit_fill
        if t.reason == "both":
            assert p.net_r < t.net_r
            continue
        q = NOMINAL / t.entry_fill
        exit_rate = 0.0008 if t.reason == "target" else 0.0005
        assert p.fees == pytest.approx(0.0008 * NOMINAL + exit_rate * q * t.exit_fill)
        assert p.net_r == pytest.approx(t.net_r - (p.fees - t.fees) / (STOP_FRACTION * NOMINAL))
        assert p.net_r < t.net_r
    back = ev.reprice(ev.reprice(sim.trades[0], s6.BASE_COSTS, ev.PROTOCOL_COSTS), ev.PROTOCOL_COSTS, s6.BASE_COSTS)
    assert back.net_r == pytest.approx(sim.trades[0].net_r)


def test_gap_alternative_closes_on_the_bar_after_the_gap() -> None:
    bars = _market(400)
    gap_trade = Trade(LONG, 100, bars[100].open_time, bars[100].open, 150, bars[150].open_time, bars[150].close, "gap", False,
                      s6.BASE_COSTS.maker_fee * NOMINAL, 0.0, 0.1)
    other = trade(0.2)
    out = ev.gap_alternative([gap_trade, other], bars, s6.BASE_COSTS)
    assert out[1] is other and out[0].reason == "gap_after" and out[0].exit_index == 151 and out[0].exit_time == bars[151].open_time
    stop = bars[100].open * (1 - STOP_FRACTION)
    expected_price = min(stop, bars[151].open) * (1 - s6.BASE_COSTS.stop_slippage)
    assert out[0].exit_fill == pytest.approx(expected_price)


def test_training_and_validation_verdicts_name_every_reason() -> None:
    wins = [trade(0.2, day=i % 400) for i in range(600)]
    good = ev.summarize(wins + [trade(-1.08, day=500 + i, reason="stop") for i in range(15)])  # 16.2 R drawdown < 20 R
    assert ev.training_verdict(good, 0.01) == {"pass": True, "reasons": []}
    bad = ev.training_verdict(ev.summarize(wins[:100] + [trade(-1.08, day=900 + i, reason="stop") for i in range(10)]), 0.5)
    assert set(bad["reasons"]) >= {"n < 500", "n_eff < 160", "p >= 0.1", "hit rate < 95 %"} and not bad["pass"]
    val = ev.validation_verdict(good, 0.01, {"year_stability": True, "walk_forward": False, "neighbours": True})
    assert val == {"pass": False, "reasons": ["robustness: walk_forward"]}
    assert ev.validation_verdict(good, 0.01, {"walk_forward": True})["pass"]
    small = ev.summarize(wins[:150])  # all hits, D = 1, n_eff = 150
    assert "n_eff < 183" in ev.validation_verdict(small, 0.01, {})["reasons"]


def test_year_stability_counts_only_years_with_enough_trades() -> None:
    def year_trades(year: int, r: float, n: int) -> list[Trade]:
        t0 = int(__import__("datetime").datetime(year, 1, 1, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
        return [Trade(LONG, 0, t0 + i * 86_400_000, 100.0, 1, t0 + i * 86_400_000 + M, 100.0, "target", False, 0.0, 0.0, r) for i in range(n)]

    trades = year_trades(2020, 0.2, 40) + year_trades(2021, -0.1, 40) + year_trades(2022, 0.1, 40) + year_trades(2023, -0.5, 10)
    out = ev.year_stability(trades)
    assert out["years_counted"] == 3 and out["years_positive"] == 2 and out["pass"]
    assert out["years"]["2023"]["n"] == 10
    assert not ev.year_stability(year_trades(2020, 0.2, 40) + year_trades(2021, -0.1, 40))["pass"]  # 50 % < 60 %
    assert not ev.year_stability([])["pass"]


def test_walk_forward_uses_only_closed_trades_for_the_choice() -> None:
    start = T0
    end = T0 + 36 * MONTH  # ~3 years -> windows of 24 + 6 months
    def mk(entry: int, exit_: int, r: float) -> Trade:
        return Trade(LONG, 0, entry, 100.0, 1, exit_, 100.0, "target", False, 0.0, 0.0, r)

    fit_end = ev.walk_forward_windows(start, end)[0].fit_end
    good_closed = [mk(start + i * 7 * 86_400_000, start + i * 7 * 86_400_000 + M, 0.3) for i in range(90)]
    # variant B looks better only through a trade still open at the fit end
    b_trades = [mk(start + i * 7 * 86_400_000, start + i * 7 * 86_400_000 + M, 0.1) for i in range(90)] + [mk(fit_end - M, fit_end + 10 * M, 50.0)]
    test_a = [mk(fit_end + 5 * 86_400_000, fit_end + 6 * 86_400_000, 0.2)]
    test_b = [mk(fit_end + 5 * 86_400_000, fit_end + 6 * 86_400_000, -1.0)]
    out = ev.walk_forward({"A": good_closed + test_a, "B": b_trades + test_b}, start, end)
    assert out["chosen"][0] == "A" and out["windows"] >= 1
    assert out["pass"] is (out["expectancy"] > 0 and out["hit_rate"] >= 0.9)
    assert ev.walk_forward({"A": [], "B": []}, start, end)["pass"] is False


def test_neighbours_and_candidate_selection() -> None:
    k2t15, k2t20, k2t25, k3t15, k3t20, k3t25 = (v for v in s6.S6_VARIANTS)
    train_e = {"S6-k2-t15": 0.1, "S6-k2-t20": 0.1, "S6-k2-t25": -0.1, "S6-k3-t15": 0.1, "S6-k3-t20": 0.1, "S6-k3-t25": 0.1}
    assert ev.neighbours_positive(k2t15, train_e)["pass"]  # neighbours k3-t15, k2-t20
    assert not ev.neighbours_positive(k2t20, train_e)["pass"]  # k2-t25 is negative
    assert set(ev.neighbours_positive(k3t25, train_e)["neighbours"]) == {"S6-k2-t25", "S6-k3-t20"}
    assert not ev.neighbours_positive(k3t15, {})["pass"]
    val_e = {"S6-k2-t15": 0.05, "S6-k3-t15": 0.09, "S6-k2-t20": 0.07, "S6-k3-t25": 0.01}
    assert ev.select_candidates(val_e, list(val_e)) == ["S6-k3-t15", "S6-k2-t20"]  # one per target, best E first
    assert ev.select_candidates(val_e, ["S6-k2-t15", "S6-k3-t15"]) == ["S6-k3-t15"]
    assert ev.select_candidates(val_e, []) == []
    assert math.isfinite(ev.PROTOCOL_COSTS.maker_fee) and ev.PROTOCOL_COSTS.maker_fee == 0.0008


def _script():
    spec = importlib.util.spec_from_file_location("s6_script", Path("scripts/research_lab_s6.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_train_requires_latency_and_refuses_raise_delta(tmp_path) -> None:
    module = _script()
    with pytest.raises(SystemExit):
        module.main(["train", "--out", str(tmp_path)])
    report = tmp_path / "lat.json"
    report.write_text(json.dumps({"summary": {"pooled": {"lambda": 0.3, "raise_delta": True}}}))
    with pytest.raises(SystemExit):
        module.train(None, report, tmp_path)
    assert not any(ref.touches_holdout for ref in module.funding_refs("SOLUSDT")) and len(module.funding_refs("SOLUSDT")) == 52


def test_register_status_applies_the_report(tmp_path) -> None:
    from src.research_lab.stats.register import HypothesisRegister

    module = _script()
    reg_path = tmp_path / "REGISTER.jsonl"
    register = HypothesisRegister(reg_path)
    for v in s6.S6_VARIANTS:
        register.register(v.variant_id, "S6", {"k": v.k})
    report = tmp_path / "s6_train_x.json"
    report.write_text(json.dumps({"commit": "abcdef1234", "register_status": {"S6-k2-t15": {"status": "failed_train", "note": "Training: E[R] <= 0"},
                                                                              "S6-k3-t20": {"status": "candidate", "note": "Kandidatin"}}}))
    assert module.register_status(report, reg_path) == 0
    statuses = {k: v["status"] for k, v in HypothesisRegister(reg_path).variants().items()}
    assert statuses["S6-k2-t15"] == "failed_train" and statuses["S6-k3-t20"] == "candidate" and statuses["S6-k2-t20"] == "registered"
