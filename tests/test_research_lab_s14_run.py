"""Study S14: random comparison, verdicts and the run script on synthetic bars (no market data)."""

from __future__ import annotations

import json
import math
import random

import pytest

from src.research_lab.data.parse import FundingRate
from src.research_lab.hypotheses import s14
from src.research_lab.protocol import BASE_COSTS, HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.stats.inference import section_trades
from src.research_lab.studies import s13_eval
from src.research_lab.studies import s14_eval as ev
from src.research_lab.studies import s14_random as sr
from tests.test_research_lab_s14 import _cointegrated, _pair
from tests.test_research_lab_s14_count import START, FakeStore, _script

V168 = s14.S14_VARIANTS[0]
H = s14.HOUR_MS


def _data(n: int = 3000, seed: int = 7) -> sr.PairData:
    ys, xs = _cointegrated(n, seed, noise=0.004, rho=0.97)
    pair = _pair(ys, xs)
    rates = [FundingRate(pair.times[0] + k * 8 * H, 0.0001) for k in range(n // 8)]
    return sr.PairData(pair, s14.Signals(pair, V168), rates, rates)


def test_a_random_trade_from_a_real_signal_equals_the_real_trade() -> None:
    data = _data()
    pair = data.pair
    real = s14.run_pair(pair, V168, pair.times[0], pair.times[-1] + H, BASE_COSTS, data.y_funding, data.x_funding)
    assert len(real) >= 5
    by_hour = dict(sr.candidates(data, pair.times[0], pair.times[-1] + H))
    for trade in real:
        t = pair.times.index(trade.signal_time)
        assert t in by_hour  # every real signal hour is a candidate
        sim = sr.simulate(data, t, by_hour[t], trade.side, BASE_COSTS)
        assert sim == trade


def test_candidates_are_the_hours_with_a_full_window_and_a_next_hour() -> None:
    data = _data(600)
    cands = sr.candidates(data, data.pair.times[0], data.pair.times[-1] + H)
    hours = [t for t, _ in cands]
    assert hours[0] == V168.window and hours[-1] == len(data.pair.times) - 2
    assert all(f.beta > 0 and f.sigma > 0 for _, f in cands)


def test_pool_trades_end_inside_the_section_and_match_random_pvalue() -> None:
    data = _data()
    pair = data.pair
    lo, hi = pair.times[0], pair.times[1500]
    real = section_trades(s14.run_pair(pair, V168, lo, pair.times[-1] + H, BASE_COSTS), lo, hi)
    pool = sr.draw_pool(data, [t.side for t in real], lo, hi, 300, random.Random(1))
    assert len(pool) == 300 and all(t.exit_time <= hi and t.reason != "end" and lo <= t.signal_time < hi for t in pool)
    assert {t.side for t in real} == {1, -1} and {t.side for t in pool} == {1, -1}
    a = sr.random_pvalue({"ETH/BTC": data}, {"ETH/BTC": real}, lo, hi, runs=50, seed=3)
    b = sr.random_pvalue({"ETH/BTC": data}, {"ETH/BTC": real}, lo, hi, runs=50, seed=3)
    assert a == b and 0 < a.p <= 1 and a.pool == {"ETH/BTC": sr.pool_size(len(real), 50)}
    # A shifted observation moves p the right way.
    up = sr.random_pvalue({"ETH/BTC": data}, {"ETH/BTC": [_shifted(t, 5.0) for t in real]}, lo, hi, runs=50, seed=3)
    down = sr.random_pvalue({"ETH/BTC": data}, {"ETH/BTC": [_shifted(t, -5.0) for t in real]}, lo, hi, runs=50, seed=3)
    assert up.p == pytest.approx(1 / 51) and down.p == 1.0


def _shifted(t: s14.PairTrade, by: float) -> s14.PairTrade:
    return s14.PairTrade(t.pair, t.signal_time, t.entry_time, t.exit_time, t.side, t.reason, t.hours_held, t.beta,
                         t.sigma, t.r + by, t.cost_r, t.funding_r)


def test_neighbour_rule_and_final_verdict() -> None:
    assert ev.neighbour_rule("S14-W168", {"S14-W720": 0.01})["pass"]
    assert not ev.neighbour_rule("S14-W168", {"S14-W720": -0.01})["pass"]
    assert not ev.neighbour_rule("S14-W720", {})["pass"]  # neighbour without trades
    ok, bad = {"pass": True, "reasons": []}, {"pass": False, "reasons": ["E[R] <= 0"]}
    walk, nb = {"pass": True}, {"pass": True}
    assert ev.final_verdict(ok, ok, True, walk, nb).startswith("KANDIDAT")
    assert ev.final_verdict(bad, ok, True, walk, nb) == "NICHT BESTANDEN (Training)"
    assert ev.final_verdict(ok, bad, True, walk, nb) == "NICHT BESTANDEN (Validierung)"
    assert ev.final_verdict(ok, ok, False, walk, nb) == "NICHT BESTANDEN (Validierung)"
    assert ev.final_verdict(ok, ok, True, {"pass": False}, nb) == "NICHT BESTANDEN (Validierung)"
    assert ev.final_verdict(ok, ok, True, walk, {"pass": False}) == "NICHT BESTANDEN (Validierung)"


class FundedStore(FakeStore):
    def __init__(self) -> None:
        super().__init__()
        self.funding = {s: [FundingRate(t, 0.0001) for t in range(START, START + 80 * 24 * H, 8 * H)] for s in self.bars}

    def load_funding(self, refs):
        refs = list(refs)
        self.requested += refs
        return list(self.funding[refs[0].symbol])


def test_run_writes_a_report_that_matches_the_reference(tmp_path, monkeypatch) -> None:
    script = _script()
    monkeypatch.setattr(s13_eval, "MIN_N", {"train": 1, "validation": 1})  # force the random comparison on small data
    store = FundedStore()
    assert script.run(store, tmp_path, runs=30) == 0
    assert all((r.year, r.month) <= (2024, 12) for r in store.requested)
    payload = json.loads(next(tmp_path.glob("s14_run_*.json")).read_text())
    assert set(payload["variants"]) == set(script.EVALUATED)
    assert next(tmp_path.glob("s14_run_*.md")).read_text().startswith("# S14 Auswertung")
    assert payload["walk_forward"]["windows"] == 0 and not payload["walk_forward"]["pass"]  # too short for 24/6

    hours = {sym: s14.hourly(bars) for sym, bars in store.bars.items()}
    for vid in script.EVALUATED:
        variant = next(v for v in s14.S14_VARIANTS if v.variant_id == vid)
        datas, trades = {}, {}
        for y, x in script.PAIRS:
            pair = s14.align(y, hours[y], x, hours[x])
            base = s14.run_pair(pair, variant, pair.times[0], HOLDOUT_START_MS, BASE_COSTS, store.funding[y], store.funding[x])
            trades[pair.name] = section_trades(base, VALIDATION_START_MS, HOLDOUT_START_MS)
            datas[pair.name] = sr.PairData(pair, s14.Signals(pair, variant), store.funding[y], store.funding[x])
        row = payload["variants"][vid]["validation"]
        assert row["figures"]["n"] == sum(map(len, trades.values()))
        if row["p"] is not None:
            ref = sr.random_pvalue(datas, trades, VALIDATION_START_MS, HOLDOUT_START_MS, runs=30)
            assert (row["p"], row["random_mean_r"]) == (ref.p, ref.random_mean)
        assert payload["variants"][vid]["verdict"].startswith(("NICHT BESTANDEN", "KANDIDAT"))
    assert any(payload["variants"][v]["validation"]["p"] is not None for v in script.EVALUATED), \
        "synthetic data must give E[R] > 0 somewhere so that the comparison runs"
    assert math.isfinite(payload["variants"]["S14-W168"]["train"]["figures"]["expectancy_r"])
