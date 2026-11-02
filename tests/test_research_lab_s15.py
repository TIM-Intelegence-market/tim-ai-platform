"""Study S15: GARCH(1,1) forecast study on synthetic data (no market data)."""

from __future__ import annotations

import importlib.util
import json
import math
import random

import pytest

from src.research_lab.data.parse import Kline
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.studies import s15

H4, D1 = s15.S15_VARIANTS


def _garch_returns(n: int, g: s15.Garch, seed: int) -> list[float]:
    rng, h, out = random.Random(seed), g.unconditional, []
    for _ in range(n):
        r = math.sqrt(h) * rng.gauss(0, 1)
        out.append(r)
        h = g.omega + g.alpha * r * r + g.beta * h
    return out


def _periods(returns: list[float], horizon: s15.Horizon, start: int = 0, rng_seed: int = 3) -> list[s15.Period]:
    """Periods whose realized variance is a noisy unbiased proxy of r^2's conditional variance."""
    rng = random.Random(rng_seed)
    out = []
    for k, r in enumerate(returns):
        out.append(s15.Period(start + k * horizon.period_ms, r, r * r * 0.5 + 0.5 * r * r * rng.uniform(0.5, 1.5)))
    return out


def _bars(start: int, closes: list[float]) -> list[Kline]:
    out, prev = [], closes[0]
    for k, c in enumerate(closes):
        t = start + k * s15.FIVE_MIN_MS
        out.append(Kline(t, prev, max(prev, c), min(prev, c), c, 1.0, t + s15.FIVE_MIN_MS - 1, 0.5))
        prev = c
    return out


def test_periods_complete_only_and_realized_variance():
    closes = [100 * math.exp(0.001 * math.sin(k)) for k in range(2 * 48)]
    bars = _bars(0, closes)
    ps = s15.periods(bars, H4)
    assert len(ps) == 2
    first = bars[:48]
    rv = (100 * math.log(first[0].close / first[0].open)) ** 2 + sum(
        (100 * math.log(first[k].close / first[k - 1].close)) ** 2 for k in range(1, 48))
    assert ps[0].rv == pytest.approx(rv)
    assert ps[0].ret == pytest.approx(100 * math.log(first[-1].close / first[0].open))
    del bars[60]
    assert [p.start for p in s15.periods(bars, H4)] == [0]


def test_fit_recovers_parameters():
    true = s15.Garch(0.05, 0.10, 0.85)
    g = s15.fit_garch(_garch_returns(20000, true, 2))
    assert g.alpha == pytest.approx(0.10, abs=0.03)
    assert g.beta == pytest.approx(0.85, abs=0.05)
    assert g.persistence < 1


def test_nelder_mead_minimizes_quadratic():
    x = s15.nelder_mead(lambda v: (v[0] - 1) ** 2 + 2 * (v[1] + 3) ** 2, [0.0, 0.0], max_evals=2000, tol=1e-12)
    assert x[0] == pytest.approx(1, abs=1e-3) and x[1] == pytest.approx(-3, abs=1e-3)


def test_forecasts_use_only_past_periods():
    rets = _garch_returns(500 * 1, s15.Garch(0.05, 0.1, 0.85), 5)
    burn = s15.BURN_IN_DAYS
    ps = _periods(rets, D1)
    t = burn + 40
    base = {f.start: f for f in s15.forecasts(ps, D1, 0, 10 ** 15)}
    changed = ps[:t] + [s15.Period(p.start, p.ret * 7, p.rv * 49) for p in ps[t:]]
    again = {f.start: f for f in s15.forecasts(changed, D1, 0, 10 ** 15)}
    for start, f in base.items():
        g = again[start]
        if start <= ps[t].start:
            assert (g.rolling, g.ewma, g.garch) == (f.rolling, f.ewma, f.garch)
    assert min(base) == ps[burn].start


def test_rolling_and_ewma_definitions():
    rets = [float(k % 5 - 2) for k in range(420)]
    ps = _periods(rets, D1)
    fs = s15.forecasts(ps, D1, 0, 10 ** 15)
    t = s15.BURN_IN_DAYS
    assert fs[0].rolling == pytest.approx(sum(r * r for r in rets[t - 14:t]) / 14)
    e = sum(r * r for r in rets[:14]) / 14
    for k in range(15, t + 1):
        e = 0.94 * e + 0.06 * rets[k - 1] ** 2
    assert fs[0].ewma == pytest.approx(e)


def test_garch_beats_rolling_on_garch_data():
    true = s15.Garch(0.05, 0.15, 0.80)
    rets = _garch_returns(1500, true, 9)
    ps = [s15.Period(k * D1.period_ms, r, r * r) for k, r in enumerate(rets)]  # rv = r^2, unbiased proxy
    fs = s15.forecasts(ps, D1, 0, 10 ** 15)
    d = s15.pooled_differences({"X": fs})
    dm = s15.diebold_mariano(d)
    assert dm["mean"] > 0 and dm["p_one_sided"] < 0.05


def test_qlike_minimum_at_truth_and_dm_sign():
    assert s15.qlike(2.0, 2.0) == pytest.approx(0)
    assert s15.qlike(2.0, 1.0) > 0 and s15.qlike(2.0, 4.0) > 0
    assert s15.diebold_mariano([1.0, 2.0, 1.5, 0.5] * 50)["p_one_sided"] < 0.01
    assert s15.diebold_mariano([-1.0, -2.0, -1.5, -0.5] * 50)["p_one_sided"] > 0.99


def test_pooled_differences_average_per_start():
    a = s15.Forecast(0, 1.0, 2.0, 1.0, 1.0)
    b = s15.Forecast(0, 1.0, 1.0, 1.0, 2.0)
    d = s15.pooled_differences({"A": [a], "B": [b]})
    assert d == [pytest.approx(0.5 * (s15.qlike(1, 2) - 0) + 0.5 * (0 - s15.qlike(1, 2)))]
    assert s15.pooled_differences({"A": [s15.Forecast(0, 0.0, 1.0, 1.0, 1.0)]}) == []


def test_verdict_rules():
    good = {"n": 600, "mean": 0.1, "p_one_sided": 0.01}
    ok = s15.verdict(good, good | {"n": 300}, {"A": 0.1, "B": 0.2, "C": -0.1}, {"2023": 0.1, "2024": 0.05})
    assert ok["passed"]
    assert not s15.verdict(good, good | {"p_one_sided": 0.06}, {"A": 1, "B": 1}, {"2023": 1})["passed"]
    assert not s15.verdict(good, good, {"A": 1, "B": -1, "C": -1}, {"2023": 1})["passed"]
    assert not s15.verdict(good, good, {"A": 1, "B": 1}, {"2023": 1, "2024": -0.01})["passed"]
    assert not s15.verdict(good | {"n": 499}, good, {"A": 1, "B": 1}, {"2023": 1, "2024": 1})["passed"]
    both = {"2023": 1, "2024": 1}
    assert not s15.verdict(good, good, {"A": 1, "B": 1}, {"2023": 1})["passed"]  # missing year fails
    assert s15.verdict(good | {"p_one_sided": 0.07}, good, {"A": 1, "B": 1}, both)["passed"]
    assert not s15.verdict(good | {"p_one_sided": 0.11}, good, {"A": 1, "B": 1}, both)["passed"]
    assert not s15.verdict(good | {"mean": -0.01, "p_one_sided": 0.001}, good, {"A": 1, "B": 1}, both)["passed"]


# ---------------------------------------------------------------- script on a fake store

DAYS = 420
START = VALIDATION_START_MS - 400 * s15.DAY_MS


def _script():
    spec = importlib.util.spec_from_file_location("research_lab_s15", "scripts/research_lab_s15.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeStore:
    def __init__(self) -> None:
        self.bars = {}
        for i, sym in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT")):
            rng, lp, closes = random.Random(i), math.log(100.0), []
            for _ in range(DAYS * 288):
                lp += rng.gauss(0, 0.002)
                closes.append(math.exp(lp))
            self.bars[sym] = _bars(START, closes) + _bars(HOLDOUT_START_MS, closes[:288])  # one holdout day
        self.requested: list = []

    def load_klines(self, refs):
        refs = list(refs)
        self.requested += refs
        return list(self.bars[refs[0].symbol])

    def dataset_hash(self, refs) -> str:
        return "fake"


@pytest.fixture(scope="module")
def store():
    return FakeStore()


def test_run_evaluates_gate_passing_variants(tmp_path, store, monkeypatch):
    mod = _script()
    monkeypatch.setattr(mod.s15, "GATE", {"train": 1, "validation": 1})
    assert mod.run(store, tmp_path) == 0
    res = json.loads(next(tmp_path.glob("s15_run_*.json")).read_text())
    assert set(res["variants"]) == {"S15-4h", "S15-1d"}
    d1 = res["variants"]["S15-1d"]
    assert d1["validation"]["dm_rolling"]["n"] == 20  # the holdout day is cut off
    assert set(d1["validation"]["by_year"]) == {"2023"}
    assert not d1["verdict"]["checks"]["years"]


def test_count_and_run_scripts(tmp_path, store):
    mod = _script()
    assert mod.count(store, tmp_path) == 0
    assert all(r.year < 2025 for r in store.requested)
    payload = json.loads(next(tmp_path.glob("s15_count_*.json")).read_text())
    d1 = payload["variants"]["S15-1d"]
    assert d1["pooled_periods"]["validation"] == DAYS - 400 + 0  # 20 validation days after the start
    assert d1["pooled_periods"]["train"] == 400 - s15.BURN_IN_DAYS
    assert not d1["passes_gate"]
    assert mod.run(store, tmp_path) == 0
    res = json.loads(next(tmp_path.glob("s15_run_*.json")).read_text())
    assert res["variants"] == {}  # both variants are below the count gate here: no outcome is computed
    assert not mod.count_rows({v: {"X": []} for v in ("S15-4h", "S15-1d")})["S15-1d"]["passes_gate"]
    assert (tmp_path / next(tmp_path.glob("s15_run_*.json")).name.replace(".json", ".md")).exists()
