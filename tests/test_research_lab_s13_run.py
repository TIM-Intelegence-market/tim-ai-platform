"""Study S13: the `run` command end to end on synthetic bars (no market data)."""

from __future__ import annotations

import importlib.util
import json
import random
from datetime import datetime, timezone

from src.research_lab.backtest.engine import run_backtest
from src.research_lab.data.parse import FundingRate, Kline
from src.research_lab.hypotheses import s13
from src.research_lab.protocol import BASE_COSTS, HOLDOUT_START_MS, VALIDATION_START_MS
from src.research_lab.stats.inference import section_trades
from src.research_lab.studies import s13_eval as ev
from src.research_lab.studies import s13_random as sr

M = s13.INTERVAL_MS
START = int(datetime(2022, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
END = int(datetime(2023, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _script():
    spec = importlib.util.spec_from_file_location("research_lab_s13", "scripts/research_lab_s13.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _bars(seed: int) -> list[Kline]:
    rng = random.Random(seed)
    out, price = [], 100.0
    drift = 0.0
    for i, t in enumerate(range(START, END, M)):
        if i % 1440 == 0:
            drift = rng.choice((-1, 1)) * rng.uniform(0, 0.0004)
        close = price * (1 + drift + rng.gauss(0, 0.0012))
        out.append(Kline(t, price, max(price, close) * 1.0002, min(price, close) * 0.9998, close, 1 + rng.random(), t + M - 1, 0.5))
        price = close
    return out


class FakeStore:
    def __init__(self) -> None:
        self.bars = {s: _bars(i) for i, s in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT"))}
        self.funding = {s: [FundingRate(t, 0.0001) for t in range(START, END, 8 * 3_600_000)] for s in self.bars}

    def load_klines(self, refs):
        return self.bars[refs[0].symbol]

    def load_funding(self, refs):
        return self.funding[refs[0].symbol]

    def dataset_hash(self, refs) -> str:
        return "synthetic"


def test_run_writes_report_and_matches_the_reference_pvalue(tmp_path, monkeypatch) -> None:
    script = _script()
    monkeypatch.setattr(script, "SYMBOLS", {s: (2022, 11) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")})
    monkeypatch.setattr(ev, "MIN_N", {"train": 1, "validation": 1})  # force the random comparison on small data
    store = FakeStore()
    assert script.run(store, tmp_path, runs=40) == 0
    payload = json.loads(next(tmp_path.glob("s13_run_*.json")).read_text())
    assert next(tmp_path.glob("s13_run_*.md")).read_text().startswith("# S13 Auswertung")
    assert set(payload["variants"]) == {"S13-NY", "S13-UTC"}
    assert payload["walk_forward"]["windows"] == 0 and not payload["walk_forward"]["pass"]  # too short for 24/6

    # The per-instrument pools of the script give exactly the p-value of random_pvalue.
    variant = s13.S13_VARIANTS[1]
    insts, trades = {}, {}
    for sym, bars in store.bars.items():
        table = s13.build_table(bars, variant, START, HOLDOUT_START_MS)
        insts[sym] = sr.Instrument(bars, table, store.funding[sym])
        base = run_backtest(bars, s13.strategy(table), M, costs=BASE_COSTS, funding=store.funding[sym], start_ms=START,
                            end_ms=HOLDOUT_START_MS).trades
        trades[sym] = section_trades(base, VALIDATION_START_MS, HOLDOUT_START_MS)
    row = payload["variants"]["S13-UTC"]["validation"]
    assert row["figures"]["n"] == sum(map(len, trades.values())) > 0
    assert row["p"] is not None, "synthetic data must give E[R] > 0 here so that the comparison runs"
    ref = sr.random_pvalue(insts, trades, VALIDATION_START_MS, HOLDOUT_START_MS, runs=40)
    assert (row["p"], row["random_mean_r"]) == (ref.p, ref.random_mean)
    assert 0 <= row["figures"]["session_end_share"] <= 1
    assert payload["variants"]["S13-UTC"]["verdict"].startswith(("NICHT BESTANDEN", "KANDIDAT"))


def _fig(**kw) -> dict:
    base = {"n": 600, "n_eff": 300, "expectancy_r": 0.05, "profit_factor": 1.3, "max_drawdown_pct": 0.1}
    return base | kw


def test_section_verdicts_follow_the_preregistered_thresholds() -> None:
    assert ev.section_verdict(_fig(), 0.05, "train")["pass"]
    assert not ev.section_verdict(_fig(), 0.10, "train")["pass"]  # p < 0.10 strictly
    assert ev.section_verdict(_fig(n=499), 0.01, "train")["reasons"] == ["n < 500"]
    assert ev.section_verdict(_fig(n_eff=159), 0.01, "train")["reasons"] == ["n_eff < 160"]
    assert ev.section_verdict(_fig(n=250, n_eff=183), 0.049, "validation")["pass"]
    assert not ev.section_verdict(_fig(), 0.05, "validation")["pass"]
    assert ev.section_verdict(_fig(profit_factor=1.1), 0.01, "validation")["reasons"] == ["PF <= 1.1"]
    assert ev.section_verdict(_fig(max_drawdown_pct=0.21), 0.01, "validation")["reasons"] == ["DD > 20%"]
    assert ev.section_verdict(_fig(max_drawdown_pct=0.21), 0.01, "train")["pass"]  # DD only in validation
    assert "p nicht berechnet" in ev.section_verdict(_fig(expectancy_r=-0.1), None, "train")["reasons"]


def test_final_verdict_needs_training_validation_years_and_walk_forward() -> None:
    ok, bad = {"pass": True, "reasons": []}, {"pass": False, "reasons": ["E[R] <= 0"]}
    walk_ok, walk_bad = {"pass": True}, {"pass": False}
    assert ev.final_verdict(ok, ok, True, walk_ok).startswith("KANDIDAT")
    assert ev.final_verdict(bad, ok, True, walk_ok) == "NICHT BESTANDEN (Training)"
    assert ev.final_verdict(ok, bad, True, walk_ok) == "NICHT BESTANDEN (Validierung)"
    assert ev.final_verdict(ok, ok, False, walk_ok) == "NICHT BESTANDEN (Validierung)"
    assert ev.final_verdict(ok, ok, True, walk_bad) == "NICHT BESTANDEN (Validierung)"
