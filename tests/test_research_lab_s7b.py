"""Study S7b: portfolio cap in the engine, the locked outcome-blind count and the script."""
from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

import pytest

from src.research_lab.backtest.engine import History, run_backtest, run_portfolio
from src.research_lab.data.archive import Dataset
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s7, s7b
from src.research_lab.protocol import BASE_COSTS
from src.research_lab.stats.random_entry import atr_at_signal
from src.research_lab.stats.register import HypothesisRegister
from src.research_lab.studies import s7_eval as ev

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("research_lab_s7b", ROOT / "scripts" / "research_lab_s7b.py")
script = importlib.util.module_from_spec(_spec)
sys.modules["research_lab_s7b"] = script
_spec.loader.exec_module(script)

H4 = s7.INTERVAL_MS
T0 = 1_577_836_800_000  # 2020-01-01T00:00:00Z
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def walk(n: int, seed: int, *, scale: float = 0.02, drift: float = 0.001, t0: int = T0) -> list[Kline]:
    rng = random.Random(seed)
    price, bars = 100.0, []
    for i in range(n):
        o = price
        c = o * (1 + drift + rng.gauss(0, scale))
        h = max(o, c) * (1 + abs(rng.gauss(0, scale / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, scale / 2)))
        bars.append(Kline(t0 + i * H4, o, h, l, c, 10.0, t0 + (i + 1) * H4 - 1, 5.0))
        price = c
    return bars


def _portfolio(bars, variant, cap, **kw):
    return run_portfolio(bars, {s: s7.breakout(variant) for s in bars}, H4, priority=SYMS, costs=BASE_COSTS,
                         atr_at_signal=atr_at_signal, gap_entry_as_loss=True, max_positions=cap, **kw)


def test_portfolio_without_binding_cap_equals_single_runs() -> None:
    bars = {s: walk(1500, 10 + i) for i, s in enumerate(SYMS)}
    variant = s7.S7_VARIANTS[0]
    results = _portfolio(bars, variant, cap=3)
    for sym in SYMS:
        single = run_backtest(bars[sym], s7.breakout(variant), H4, costs=BASE_COSTS, atr_at_signal=atr_at_signal, gap_entry_as_loss=True)
        assert results[sym].trades == single.trades
        assert results[sym].locked_signals == 0
        assert results[sym].ignored_signals == single.ignored_signals


def test_cap_one_never_overlaps_and_counts_locked_signals() -> None:
    bars = {s: walk(2500, 20 + i) for i, s in enumerate(SYMS)}
    variant = s7.S7_VARIANTS[1]
    results = _portfolio(bars, variant, cap=1)
    trades = sorted((t.entry_time, t.exit_time, sym) for sym, r in results.items() for t in r.trades)
    assert trades
    for (_, exit_a, _), (entry_b, _, _) in zip(trades, trades[1:]):
        assert entry_b >= exit_a  # the next entry is never before the previous exit
    locked = sum(r.locked_signals for r in results.values())
    singles = sum(len(run_backtest(bars[s], s7.breakout(variant), H4, costs=BASE_COSTS, gap_entry_as_loss=True).trades) for s in SYMS)
    assert locked > 0 and len(trades) < singles
    for r in results.values():
        assert r.locked_signals <= r.ignored_signals


def test_tie_on_the_same_bar_goes_to_the_priority_instrument() -> None:
    same = walk(1500, 30)
    bars = {s: list(same) for s in SYMS}  # identical bars: every signal falls on the same bar everywhere
    results = _portfolio(bars, s7.S7_VARIANTS[0], cap=1)
    assert results["BTCUSDT"].trades
    assert results["ETHUSDT"].trades == [] and results["SOLUSDT"].trades == []
    assert results["ETHUSDT"].locked_signals == len(results["ETHUSDT"].signals) > 0
    # with the mirrored priority the roles swap
    swapped = run_portfolio(bars, {s: s7.breakout(s7.S7_VARIANTS[0]) for s in bars}, H4, priority=tuple(reversed(SYMS)),
                            max_positions=1, gap_entry_as_loss=True)
    assert swapped["SOLUSDT"].trades and swapped["BTCUSDT"].trades == []


def test_exit_bar_frees_the_slot_for_the_same_close() -> None:
    """A position exiting on bar t (phase one) must not block a signal on the close of bar t."""
    long_bars = walk(600, 41, drift=0.004)
    flat = [Kline(b.open_time, 50.0, 50.0, 50.0, 50.0, 10.0, b.close_time, 5.0) for b in long_bars]  # never signals
    results = run_portfolio({"BTCUSDT": flat, "ETHUSDT": long_bars}, {"BTCUSDT": s7.breakout(s7.S7_VARIANTS[0]),
                            "ETHUSDT": s7.breakout(s7.S7_VARIANTS[0])}, H4, priority=("BTCUSDT", "ETHUSDT"), max_positions=1,
                            gap_entry_as_loss=True)
    single = run_backtest(long_bars, s7.breakout(s7.S7_VARIANTS[0]), H4, gap_entry_as_loss=True)
    assert results["ETHUSDT"].trades == single.trades and results["ETHUSDT"].locked_signals == 0


def test_portfolio_rejects_bad_arguments() -> None:
    bars = {s: walk(300, 1) for s in SYMS}
    strategies = {s: s7.breakout(s7.S7_VARIANTS[0]) for s in SYMS}
    with pytest.raises(ValueError):
        run_portfolio(bars, strategies, H4, priority=("BTCUSDT", "ETHUSDT"))
    with pytest.raises(ValueError):
        run_portfolio(bars, strategies, H4, priority=SYMS, max_positions=0)
    dup = {**bars, "SOLUSDT": bars["SOLUSDT"] + bars["SOLUSDT"][-1:]}
    with pytest.raises(ValueError):
        run_portfolio(dup, strategies, H4, priority=SYMS)


def test_variants_and_params_carry_the_portfolio_rule() -> None:
    assert [v.variant_id for v in s7b.S7B_VARIANTS] == ["S7b-D20-T3", "S7b-D20-T4", "S7b-D55-T3", "S7b-D55-T4"]
    assert [v.variant_id for v in s7b.GATE_VARIANTS] == ["S7b-D20-T3", "S7b-D20-T4"]
    p = s7b.params(s7b.S7B_VARIANTS[0])
    assert p["max_positions"] == 1 and p["priority"] == "BTCUSDT>ETHUSDT>SOLUSDT" and p["parent"] == "S7"
    assert p["channel"] == 20 and p["target_r"] == 3.0 and p["time_stop"] == 30
    assert all(v.hypothesis == "S7b" for v in s7b.S7B_VARIANTS)


def test_locked_count_is_outcome_blind_and_bounds_the_engine() -> None:
    bars = {s: walk(1800, 50 + i) for i, s in enumerate(SYMS)}
    variant = s7b.S7B_VARIANTS[0]
    start, end = bars["BTCUSDT"][300].open_time, bars["BTCUSDT"][1700].open_time
    windows = {s: (start, end) for s in SYMS}
    count = s7b.count_signals_locked(bars, variant, windows)
    assert count.upper == sum(s7.count_signals(bars[s], variant, start, end).upper for s in SYMS)
    times = [t for t, _ in count.lower_times]
    assert all(b - a >= s7b.LOCK_MS for a, b in zip(times, times[1:]))
    assert all(start <= t < end for t in times)
    results = run_portfolio(bars, {s: s7.breakout(variant) for s in SYMS}, H4, priority=SYMS, max_positions=1,
                            start_ms_by_symbol={s: start for s in SYMS}, end_ms=end, gap_entry_as_loss=True)
    taken = sum(len(r.trades) + r.invalid_signals for r in results.values())
    assert count.lower <= taken <= count.upper
    # no outcome enters: changing every price after the window leaves the count unchanged
    altered = {s: b[:1700] + [Kline(x.open_time, 1.0, 1.0, 1.0, 1.0, 1.0, x.close_time, 1.0) for x in b[1700:]] for s, b in bars.items()}
    assert s7b.count_signals_locked(altered, variant, windows) == count


def test_locked_count_tie_break_follows_priority() -> None:
    same = walk(1200, 7)
    bars = {s: list(same) for s in SYMS}
    start, end = same[250].open_time, same[1150].open_time
    count = s7b.count_signals_locked(bars, s7b.S7B_VARIANTS[1], {s: (start, end) for s in SYMS})
    assert count.lower > 0 and {sym for _, sym in count.lower_times} == {"BTCUSDT"}
    assert count.upper == 3 * count.lower or count.upper >= 3 * count.lower


# ----------------------------------------------------------------------------- script


class FakeStore:
    def __init__(self, bars: dict[str, list[Kline]]) -> None:
        self.bars = bars

    def load_klines(self, refs):
        symbol = refs[0].symbol
        lo, hi = refs[0].start_ms, refs[-1].end_ms
        return [b for b in self.bars[symbol] if lo <= b.open_time < hi]

    def load_funding(self, refs):
        assert refs[0].dataset is Dataset.FUNDING
        return []

    def dataset_hash(self, refs) -> str:
        return "cafebabe"


def _five_years() -> dict[str, list[Kline]]:
    return {s: walk(5 * 366 * 6, 60 + i, drift=0.0006) for i, s in enumerate(script.SYMBOLS)}


def test_count_writes_gate_report_with_locked_lower_bounds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(script.s7script, "_commit", lambda: "testcommit")
    assert script.count(FakeStore(_five_years()), tmp_path) == 0
    files = sorted(tmp_path.iterdir())
    assert [f.suffix for f in files] == [".json", ".md"] and files[0].name.startswith("s7b_count_")
    payload = json.loads(files[0].read_text())
    assert payload["outcome_blind"] is True and payload["lock"] == {"max_positions": 1, "priority": list(SYMS), "lock_bars": 30}
    assert payload["gate"]["holdout"] == 50 and payload["commit"] == "testcommit"
    assert set(payload["variants"]) == {v.variant_id for v in s7b.S7B_VARIANTS}
    for vid, v in payload["variants"].items():
        assert v["registrable"] == vid.startswith("S7b-D20")
        assert v["passes_gate"] is False or v["registrable"]
        assert sum(v["by_symbol"].values()) == v["totals"]["train"]["lower"] + v["totals"]["validation"]["lower"] <= v["upper_all_instruments"]
        assert "hit" not in json.dumps(v) and "r" not in v
    assert "Positionsgrenze" in files[1].read_text()


def test_register_takes_only_gate_variants(tmp_path: Path) -> None:
    report = tmp_path / "count.json"
    report.write_text(json.dumps({"commit": "abc", "dataset_hash": "d", "variants": {
        "S7b-D20-T3": {"passes_gate": True}, "S7b-D20-T4": {"passes_gate": False},
        "S7b-D55-T3": {"passes_gate": True}, "S7b-D55-T4": {"passes_gate": True}}}))
    register_path = tmp_path / "REGISTER.jsonl"
    assert script.register_variants(report, register_path) == 0
    register = HypothesisRegister(register_path)
    assert list(register.variants()) == ["S7b-D20-T3"]
    params = register.variants()["S7b-D20-T3"]["params"]
    assert params["max_positions"] == 1 and params["parent"] == "S7" and params["gate_commit"] == "abc"
    assert script.register_variants(report, register_path) == 0 and register.m == 1


def test_train_applies_portfolio_cap_and_s7b_minimums(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ev, "POOL_PER_DECILE", 40)
    monkeypatch.setattr(ev, "MIN_POOL", 80)
    monkeypatch.setattr(ev, "POOL_FACTOR", 2)
    monkeypatch.setattr(script.s7script, "_commit", lambda: "testcommit")
    bars = _five_years()
    register_path = tmp_path / "REGISTER.jsonl"
    assert script.train(FakeStore(bars), tmp_path / "none", register_path=register_path) == 1
    register = HypothesisRegister(register_path)
    for v in s7b.GATE_VARIANTS:
        register.register(v.variant_id, s7b.HYPOTHESIS, s7b.params(v))
    out = tmp_path / "reports"
    assert script.train(FakeStore(bars), out, runs=25, register_path=register_path, commit_register=True, progress=lambda line: None) == 0
    files = sorted(out.iterdir())
    assert len(files) == 3 and all(f.name.startswith("s7b_train_") for f in files)
    payload = json.loads(next(f for f in files if f.name.endswith("Z.json") and "trades" not in f.name).read_text())
    assert payload["study"] == "S7b" and payload["parent"] == "S7" and payload["minimums"]["holdout"] == [50, 30]
    assert payload["registered"] == ["S7b-D20-T3", "S7b-D20-T4"] and payload["lock"]["max_positions"] == 1
    for vid, entry in payload["variants"].items():
        assert entry["params"]["max_positions"] == 1
        tr = entry["sections"]["train"]
        assert tr["summary"]["n"] > 0 and set(tr["baselines"]) == {"A", "A'", "C", "B"}
        if vid.startswith("S7b-D55"):
            assert entry["status"] == "nicht registriert (nur Nachbar)"
        else:
            assert entry["status"] in {"failed_train", "failed_validation", "candidate", "not_selected"}
    trades = json.loads(next(f for f in files if f.name.endswith("trades.json")).read_text())
    by_variant: dict[str, list] = {}
    for t in trades:
        by_variant.setdefault(t["variant"], []).append((t["entry_time"], t["exit_time"]))
    for rows in by_variant.values():
        rows.sort()
        assert all(b[0] >= a[1] for a, b in zip(rows, rows[1:]))  # the cap holds in the recorded trades
    text = next(f for f in files if f.suffix == ".md").read_text()
    assert "Positionsgrenze 1" in text and "## Urteile" in text and "Ableitung aus S7" in text
    statuses = {v: e["status"] for v, e in HypothesisRegister(register_path).variants().items()}
    assert set(statuses) == {"S7b-D20-T3", "S7b-D20-T4"}
