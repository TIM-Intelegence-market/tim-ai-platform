"""Study S14: the count script on synthetic 5m bars (no market data)."""

from __future__ import annotations

import importlib.util
import json
import math
import random

from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s14
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS

START = VALIDATION_START_MS - 40 * 24 * s14.HOUR_MS  # 40 days before the validation start
HOURS = 80 * 24


def _script():
    spec = importlib.util.spec_from_file_location("research_lab_s14", "scripts/research_lab_s14.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _five_minute(log_prices: list[float]) -> list[Kline]:
    out = []
    for h, lp in enumerate(log_prices):
        prev = log_prices[h - 1] if h else lp
        for k in range(12):
            t = START + h * s14.HOUR_MS + k * s14.FIVE_MIN_MS
            o = math.exp(prev + (lp - prev) * k / 12)
            c = math.exp(prev + (lp - prev) * (k + 1) / 12)
            out.append(Kline(t, o, max(o, c), min(o, c), c, 1.0, t + s14.FIVE_MIN_MS - 1, 0.5))
    return out


class FakeStore:
    def __init__(self) -> None:
        rng = random.Random(11)
        lb, e1, e2, btc, eth, sol = math.log(30000.0), 0.0, 0.0, [], [], []
        for _ in range(HOURS):
            lb += rng.gauss(0, 0.004)
            e1 = 0.95 * e1 + rng.gauss(0, 0.003)
            e2 = 0.95 * e2 + rng.gauss(0, 0.004)
            btc.append(lb)
            eth.append(-2.5 + 1.0 * lb + e1)
            sol.append(-6.0 + 1.1 * lb + e2)
        self.bars = {"BTCUSDT": _five_minute(btc), "ETHUSDT": _five_minute(eth), "SOLUSDT": _five_minute(sol)}
        del self.bars["SOLUSDT"][500]  # one 5m bar missing: that hour is dropped
        self.requested: list = []

    def load_klines(self, refs):
        refs = list(refs)
        self.requested += refs
        return list(self.bars[refs[0].symbol])

    def dataset_hash(self, refs) -> str:
        return "fake"


def test_count_writes_an_outcome_blind_report_that_matches_the_rules(tmp_path) -> None:
    script = _script()
    store = FakeStore()
    assert script.count(store, tmp_path) == 0
    assert all(r.interval == "5m" and (r.year, r.month) <= (2024, 12) for r in store.requested)
    payload = json.loads(next(tmp_path.glob("s14_count_*.json")).read_text())
    assert payload["outcome_blind"] and payload["upper_bound"] and payload["study"] == "S14"
    assert payload["symbols"]["SOLUSDT"]["hours"] == HOURS - 1
    hours = {sym: s14.hourly(bars) for sym, bars in store.bars.items()}
    for variant in s14.S14_VARIANTS:
        row = payload["variants"][variant.variant_id]
        expected = {"train": 0, "validation": 0}
        days = {"train": set(), "validation": set()}
        for y, x in script.PAIRS:
            pair = s14.align(y, hours[y], x, hours[x])
            found = s14.entries(s14.Signals(pair, variant), pair.times[0], HOLDOUT_START_MS)
            assert row["funnel"][pair.name] == {"hours": len(pair.times), "signals": len(found)}
            for e in found:
                sec = "train" if pair.times[e.index] < VALIDATION_START_MS else "validation"
                expected[sec] += 1
                days[sec].add(script.day_of(pair.times[e.index]))
        for sec in ("train", "validation"):
            assert row[sec]["signals"] == expected[sec]
            assert row[sec]["signal_days"] == len(days[sec])
            assert row[sec]["long"] + row[sec]["short"] == expected[sec]
        assert sum(row["by_year"].values()) == expected["train"] + expected["validation"]
        assert row["passes_gate"] is False  # 80 days cannot reach 500 signals
    w168 = payload["variants"]["S14-W168"]
    assert w168["train"]["signals"] > 0 and w168["validation"]["signals"] > 0
    md = next(tmp_path.glob("s14_count_*.md")).read_text()
    assert "ergebnisblind" in md and "Obergrenze" in md and "S14-W720-K" in md


def test_refs_stop_before_the_holdout() -> None:
    script = _script()
    for symbol in script.SYMBOLS:
        refs = script.refs(symbol)
        assert refs[-1].year == 2024 and refs[-1].month == 12 and all(r.interval == "5m" for r in refs)
    assert script.refs("SOLUSDT")[0].month == 9
