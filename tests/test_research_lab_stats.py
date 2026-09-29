from __future__ import annotations

import json

import pytest

from src.research_lab.backtest.engine import Trade, run_backtest
from src.research_lab.data.store import HoldoutPermission
from src.research_lab.stats.inference import (
    holm,
    iid_band,
    month_block_bootstrap_ci,
    neighbours_positive,
    walk_forward,
    walk_forward_windows,
    year_stability,
)
from src.research_lab.stats.random_entry import atr_at_signal, atr_series, random_entry_pvalue, simulate_trade
from src.research_lab.stats.register import HypothesisRegister, RegisterError, claim_holdout
from src.research_lab.protocol import BASE_COSTS, _utc_ms
from src.research_lab.synthetic import marker_strategy, synthetic_series

H = 3_600_000


def trade(entry_time: int, r: float) -> Trade:
    return Trade(entry_time, entry_time, entry_time + H, 1, 100.0, 101.0, 99.0, "time", 1, r, 0.0, 0.0, 1.0, None)


# --- random-entry benchmark -------------------------------------------------

def test_random_simulation_reproduces_engine_trades() -> None:
    bars = synthetic_series(4000, seed=5, edge=0.2)
    trades = run_backtest(bars, marker_strategy(), H, costs=BASE_COSTS, atr_at_signal=atr_at_signal).trades
    atr_values = atr_series(bars)
    index_of = {b.open_time: i for i, b in enumerate(bars)}
    for t in trades[:50]:
        if t.reason in {"end", "gap"}:
            continue
        i = index_of[t.signal_time]
        r = simulate_trade(bars, i, t.side, t.stop_atr * atr_values[i], t.target_r, 3, H, BASE_COSTS, (), [])
        assert r == pytest.approx(t.r, rel=1e-9, abs=1e-9)


def test_edge_beats_random_entries_and_noise_does_not() -> None:
    edge_bars = synthetic_series(6000, seed=21, edge=0.3)
    edge_trades = run_backtest(edge_bars, marker_strategy(), H, atr_at_signal=atr_at_signal).trades
    assert random_entry_pvalue(edge_bars, edge_trades, H, runs=199, seed=1) <= 0.01
    noise_bars = synthetic_series(6000, seed=21, edge=0.0)
    noise_trades = run_backtest(noise_bars, marker_strategy(), H, atr_at_signal=atr_at_signal).trades
    assert random_entry_pvalue(noise_bars, noise_trades, H, runs=199, seed=1) > 0.05


def test_pvalue_needs_stop_distance_in_atr() -> None:
    bars = synthetic_series(500, seed=2)
    trades = run_backtest(bars, marker_strategy(), H).trades
    with pytest.raises(ValueError, match="stop_atr"):
        random_entry_pvalue(bars, trades, H, runs=9, seed=1)
    assert random_entry_pvalue(bars, [], H, runs=9, seed=1) == 1.0


# --- corrections and bootstrap ---------------------------------------------

def test_holm_uses_full_register_size() -> None:
    p = {"a": 0.002, "b": 0.02}
    assert holm(p, m=2) == {"a", "b"}
    assert holm(p, m=48) == set()  # 0.002 > 0.05 / 48
    assert holm({"a": 0.0005, "b": 0.02}, m=48) == {"a"}
    with pytest.raises(ValueError):
        holm(p, m=1)


def test_bootstrap_intervals() -> None:
    jan, feb = _utc_ms(2024, 1, 5), _utc_ms(2024, 2, 5)
    trades = [trade(jan, 1.0), trade(jan + H, 1.0), trade(feb, -1.0)]
    low, high = month_block_bootstrap_ci(trades, draws=2000, seed=1)
    assert -1.0 <= low < high <= 1.0
    low, high = iid_band([1.0, -1.0], 400, draws=2000, seed=1)
    assert -0.15 < low < 0 < high < 0.15


def test_year_stability_ignores_thin_years() -> None:
    assert year_stability({2020: (10, 0.1), 2021: (10, -0.1), 2022: (10, 0.2), 2023: (2, -5.0)})
    assert not year_stability({2020: (10, 0.1), 2021: (10, -0.1)})
    assert not year_stability({2020: (3, 0.1)})


def test_neighbours_rule_on_ordered_parameters() -> None:
    grid = {"n": [100, 150, 200]}
    assert neighbours_positive(grid, {(100,): 0.1, (150,): 0.2, (200,): 0.05}, (150,))
    assert not neighbours_positive(grid, {(100,): -0.1, (150,): 0.4, (200,): 0.05}, (150,))
    assert neighbours_positive(grid, {(100,): 0.1, (150,): 0.2, (200,): -0.3}, (100,))


def test_walk_forward_selects_only_on_fit_windows() -> None:
    start, end = _utc_ms(2019, 1, 1), _utc_ms(2022, 1, 1)
    windows = walk_forward_windows(start, end)
    assert [(w.fit_start, w.fit_end, w.test_end) for w in windows] == [
        (start, _utc_ms(2021, 1, 1), _utc_ms(2021, 7, 1)),
        (_utc_ms(2019, 7, 1), _utc_ms(2021, 7, 1), _utc_ms(2022, 1, 1)),
    ]
    # "a" shines in the fit period, then fails; "b" is the opposite. The chained
    # result must reflect the choice made without seeing the test window.
    fit, test = _utc_ms(2020, 6, 1), _utc_ms(2021, 3, 1)
    variant_trades = {"a": [trade(fit, 1.0), trade(test, -1.0)], "b": [trade(fit, -1.0), trade(test, 1.0)]}
    mean, chosen = walk_forward(variant_trades, windows[:1])
    assert chosen == ["a"] and mean == -1.0


# --- register and holdout lock ---------------------------------------------

def test_register_counts_every_attempt_and_detects_edits(tmp_path) -> None:
    register = HypothesisRegister(tmp_path / "register.jsonl", limit=3)
    register.register("L1-100-long", "L1", {"n": 100})
    register.register("L1-150-long", "L1", {"n": 150})
    register.set_status("L1-100-long", "failed_train")
    assert register.m == 2
    with pytest.raises(RegisterError):
        register.register("L1-100-long", "L1", {"n": 100})
    with pytest.raises(RegisterError):
        register.set_status("L1-100-long", "candidate")  # final status stays final
    register.register("L1-200-long", "L1", {"n": 200})
    with pytest.raises(RegisterError, match="limit"):
        register.register("L1-250-long", "L1", {"n": 250})
    lines = (tmp_path / "register.jsonl").read_text().splitlines()
    tampered = json.loads(lines[0])
    tampered["params"] = {"n": 90}
    lines[0] = json.dumps(tampered, sort_keys=True)
    (tmp_path / "register.jsonl").write_text("\n".join(lines) + "\n")
    with pytest.raises(RegisterError, match="hash chain"):
        register.m


def test_holdout_runs_only_once(tmp_path) -> None:
    register = HypothesisRegister(tmp_path / "register.jsonl")
    register.register("M1-20-2", "M1", {"N": 20, "k": 2})
    with pytest.raises(RegisterError, match="candidate status"):
        claim_holdout(tmp_path / "holdout.lock", ["M1-20-2"], register)
    register.set_status("M1-20-2", "candidate")
    permission = claim_holdout(tmp_path / "holdout.lock", ["M1-20-2"], register)
    assert isinstance(permission, HoldoutPermission) and permission.m == 1 and permission.candidates == ("M1-20-2",)
    lock = json.loads((tmp_path / "holdout.lock").read_text())
    assert lock["m"] == 1 and lock["register_head"] == register.events()[-1]["hash"]
    with pytest.raises(FileExistsError):
        claim_holdout(tmp_path / "holdout.lock", ["M1-20-2"], register)
    with pytest.raises(RegisterError):
        claim_holdout(tmp_path / "other.lock", ["unknown"], register)


def test_candidate_limit_and_final_no_verdict(tmp_path) -> None:
    register = HypothesisRegister(tmp_path / "register.jsonl")
    for n in (20, 30, 40):
        register.register(f"M1-{n}", "M1", {"N": n})
        register.set_status(f"M1-{n}", "candidate")
    with pytest.raises(RegisterError, match="two candidates"):
        claim_holdout(tmp_path / "holdout.lock", ["M1-20", "M1-30", "M1-40"], register)
    register.set_status("M1-40", "no_verdict")
    with pytest.raises(RegisterError, match="final"):
        register.set_status("M1-40", "passed_holdout")
