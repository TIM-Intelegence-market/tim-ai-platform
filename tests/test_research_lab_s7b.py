"""Study S7b: portfolio cap in the engine, the locked outcome-blind count, the script and the
engine regression against the golden fixture recorded before the engine was refactored."""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import math
import random
import sys
from pathlib import Path

import pytest

from src.research_lab.backtest.engine import History, Signal, run_backtest, run_portfolio
from src.research_lab.data.archive import ArchiveRef, Dataset
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s7, s7b
from src.research_lab.protocol import BASE_COSTS, HOLDOUT_START_MS, STRESS_COSTS, VALIDATION_START_MS
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
GOLDEN = ROOT / "tests" / "fixtures" / "research_lab" / "engine_golden_7cefb19.json"


def walk(n: int, seed: int, *, scale: float = 0.02, drift: float = 0.001, t0: int = T0, gaps: frozenset[int] = frozenset()) -> list[Kline]:
    """Seeded random walk; `gaps` are skipped bar indices (the generator of the golden fixture)."""
    rng = random.Random(seed)
    price, bars = 100.0, []
    for i in range(n):
        if i in gaps:
            continue
        o = price
        c = o * (1 + drift + rng.gauss(0, scale))
        h = max(o, c) * (1 + abs(rng.gauss(0, scale / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, scale / 2)))
        bars.append(Kline(t0 + i * H4, o, h, l, c, 10.0, t0 + (i + 1) * H4 - 1, 5.0))
        price = c
    return bars


def flat(n: int, price: float = 100.0, *, skip: frozenset[int] = frozenset()) -> list[Kline]:
    return [Kline(T0 + i * H4, price, price, price, price, 10.0, T0 + (i + 1) * H4 - 1, 5.0) for i in range(n) if i not in skip]


def scripted(signals: dict[int, Signal]):
    """Strategy that emits the given signal on the bar with that index (open time T0 + i * H4)."""
    def strategy(history: History) -> Signal | None:
        return signals.get((history[-1].open_time - T0) // H4)
    return strategy


def _portfolio(bars, variant, cap, **kw):
    return run_portfolio(bars, {s: s7.breakout(variant) for s in bars}, H4, priority=SYMS, costs=BASE_COSTS,
                         atr_at_signal=atr_at_signal, gap_entry_as_loss=True, max_positions=cap, **kw)


# ----------------------------------------------------------------------------- engine: portfolio cap


def test_portfolio_without_binding_cap_equals_single_runs() -> None:
    bars = {s: walk(1500, 10 + i) for i, s in enumerate(SYMS)}
    variant = s7.S7_VARIANTS[0]
    results = _portfolio(bars, variant, cap=3)
    for sym in SYMS:
        single = run_backtest(bars[sym], s7.breakout(variant), H4, costs=BASE_COSTS, atr_at_signal=atr_at_signal, gap_entry_as_loss=True)
        assert single.trades  # the comparison is not vacuous
        assert results[sym].trades == single.trades
        assert results[sym].locked_signals == 0 and results[sym].locked_times == []
        assert results[sym].ignored_signals == single.ignored_signals
        assert results[sym].ignored_times == single.ignored_times and len(single.ignored_times) == single.ignored_signals


def test_cap_one_never_overlaps_and_counts_locked_signals() -> None:
    bars = {s: walk(2500, 20 + i) for i, s in enumerate(SYMS)}
    variant = s7.S7_VARIANTS[1]
    results = _portfolio(bars, variant, cap=1)
    trades = sorted((t.entry_time, t.exit_time, sym) for sym, r in results.items() for t in r.trades)
    assert len(trades) > 20
    for (_, exit_a, _), (entry_b, _, _) in zip(trades, trades[1:]):
        assert entry_b >= exit_a  # the next entry is never before the previous exit
    locked = sum(r.locked_signals for r in results.values())
    singles = sum(len(run_backtest(bars[s], s7.breakout(variant), H4, costs=BASE_COSTS, gap_entry_as_loss=True).trades) for s in SYMS)
    assert locked > 0 and len(trades) < singles
    for r in results.values():
        assert r.locked_signals <= r.ignored_signals
        assert len(r.locked_times) == r.locked_signals and len(r.ignored_times) == r.ignored_signals
        assert set(r.locked_times) <= set(r.ignored_times)
        assert all(t in {s[0] for s in r.signals} for t in r.ignored_times)


def test_tie_on_the_same_bar_goes_to_the_priority_instrument() -> None:
    same = walk(1500, 30)
    bars = {s: list(same) for s in SYMS}  # identical bars: every signal falls on the same bar everywhere
    results = _portfolio(bars, s7.S7_VARIANTS[0], cap=1)
    assert results["BTCUSDT"].trades
    assert results["ETHUSDT"].trades == [] and results["SOLUSDT"].trades == []
    assert results["ETHUSDT"].locked_signals == len(results["ETHUSDT"].signals) > 0
    # with the mirrored priority the roles swap
    swapped = run_portfolio(bars, {s: s7.breakout(s7.S7_VARIANTS[0]) for s in bars}, H4, priority=tuple(reversed(SYMS)),
                            costs=BASE_COSTS, atr_at_signal=atr_at_signal, max_positions=1, gap_entry_as_loss=True)
    assert swapped["SOLUSDT"].trades == results["BTCUSDT"].trades and swapped["BTCUSDT"].trades == []


def test_exit_bar_frees_the_slot_for_the_same_close() -> None:
    """A position exiting on bar t (phase one) must not block a signal on the close of bar t."""
    long_bars = walk(600, 41, drift=0.004)
    results = run_portfolio({"BTCUSDT": flat(600, 50.0), "ETHUSDT": long_bars}, {"BTCUSDT": s7.breakout(s7.S7_VARIANTS[0]),
                            "ETHUSDT": s7.breakout(s7.S7_VARIANTS[0])}, H4, priority=("BTCUSDT", "ETHUSDT"), max_positions=1,
                            gap_entry_as_loss=True)
    single = run_backtest(long_bars, s7.breakout(s7.S7_VARIANTS[0]), H4, gap_entry_as_loss=True)
    assert single.trades
    assert results["ETHUSDT"].trades == single.trades and results["ETHUSDT"].locked_signals == 0


def test_cross_instrument_exit_frees_the_slot_on_the_same_bar() -> None:
    """BTC exits by time stop on bar 12 (phase one); ETH's signal on the close of bar 12 is taken."""
    btc = scripted({10: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=2)})
    eth = scripted({12: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=5)})
    results = run_portfolio({"BTCUSDT": flat(30), "ETHUSDT": flat(30)}, {"BTCUSDT": btc, "ETHUSDT": eth}, H4,
                            priority=("BTCUSDT", "ETHUSDT"), max_positions=1)
    assert [t.reason for t in results["BTCUSDT"].trades] == ["time"]
    assert results["BTCUSDT"].trades[0].exit_time == T0 + 12 * H4 + H4  # close of bar 12
    assert len(results["ETHUSDT"].trades) == 1 and results["ETHUSDT"].locked_signals == 0
    # one bar earlier the slot is still taken
    eth_early = scripted({11: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=5)})
    results = run_portfolio({"BTCUSDT": flat(30), "ETHUSDT": flat(30)}, {"BTCUSDT": btc, "ETHUSDT": eth_early}, H4,
                            priority=("BTCUSDT", "ETHUSDT"), max_positions=1)
    assert results["ETHUSDT"].trades == [] and results["ETHUSDT"].locked_times == [T0 + 11 * H4]


def test_stop_before_entry_frees_the_slot() -> None:
    """BTC's entry bar opens below its stop: with gap_entry_as_loss the pending entry is booked as a
    loss and the slot is free again for ETH's signal on the close of that same bar."""
    btc_bars = flat(30)
    btc_bars[11] = Kline(btc_bars[11].open_time, 90.0, 90.0, 90.0, 90.0, 10.0, btc_bars[11].close_time, 5.0)  # gap below the stop
    btc = scripted({10: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=10)})
    eth = scripted({11: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=5)})
    results = run_portfolio({"BTCUSDT": btc_bars, "ETHUSDT": flat(30)}, {"BTCUSDT": btc, "ETHUSDT": eth}, H4,
                            priority=("BTCUSDT", "ETHUSDT"), max_positions=1, gap_entry_as_loss=True)
    assert [t.reason for t in results["BTCUSDT"].trades] == ["stop_before_entry"]
    assert len(results["ETHUSDT"].trades) == 1 and results["ETHUSDT"].locked_signals == 0
    # the pending entry itself occupies the slot on bar 10
    eth_same = scripted({10: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=5)})
    results = run_portfolio({"BTCUSDT": btc_bars, "ETHUSDT": flat(30)}, {"BTCUSDT": btc, "ETHUSDT": eth_same}, H4,
                            priority=("BTCUSDT", "ETHUSDT"), max_positions=1, gap_entry_as_loss=True)
    assert results["ETHUSDT"].trades == [] and results["ETHUSDT"].locked_signals == 1


def test_a_data_gap_keeps_the_slot_until_the_gap_close() -> None:
    """BTC holds a position and has no bar 13: during the gap the slot stays taken; the gap close
    happens in phase one of bar 14, so ETH's signal on the close of bar 14 is taken."""
    btc_bars = flat(30, skip=frozenset({13}))
    btc = scripted({10: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=20)})
    eth = scripted({13: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=2), 14: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=2)})
    results = run_portfolio({"BTCUSDT": btc_bars, "ETHUSDT": flat(30)}, {"BTCUSDT": btc, "ETHUSDT": eth}, H4,
                            priority=("BTCUSDT", "ETHUSDT"), max_positions=1)
    assert [t.reason for t in results["BTCUSDT"].trades] == ["gap"] and results["BTCUSDT"].gap_closes == 1
    assert results["ETHUSDT"].locked_times == [T0 + 13 * H4]
    assert [t.signal_time for t in results["ETHUSDT"].trades] == [T0 + 14 * H4]


def test_different_start_dates_warm_up_without_signals_and_share_the_slot() -> None:
    """SOL starts later: before its start it emits nothing, and BTC's position blocks its first signal."""
    btc = scripted({10: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=20)})
    sol = scripted({5: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=2), 15: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=2),
                    31: Signal(1, stop=95.0, target_r=3.0, time_stop_bars=2)})
    results = run_portfolio({"BTCUSDT": flat(40), "SOLUSDT": flat(40)}, {"BTCUSDT": btc, "SOLUSDT": sol}, H4,
                            priority=("BTCUSDT", "SOLUSDT"), max_positions=1, start_ms_by_symbol={"SOLUSDT": T0 + 15 * H4})
    assert [t for t, _, _ in results["SOLUSDT"].signals] == [T0 + 15 * H4, T0 + 31 * H4]  # bar 5 lies before the start
    assert results["SOLUSDT"].locked_times == [T0 + 15 * H4]
    assert [t.signal_time for t in results["SOLUSDT"].trades] == [T0 + 31 * H4]


def test_cap_two_takes_two_and_locks_the_third() -> None:
    sig = Signal(1, stop=95.0, target_r=3.0, time_stop_bars=5)
    strategies = {s: scripted({10: sig}) for s in SYMS}
    results = run_portfolio({s: flat(30) for s in SYMS}, strategies, H4, priority=SYMS, max_positions=2)
    assert len(results["BTCUSDT"].trades) == 1 and len(results["ETHUSDT"].trades) == 1
    assert results["SOLUSDT"].trades == [] and results["SOLUSDT"].locked_signals == 1
    results = run_portfolio({s: flat(30) for s in SYMS}, strategies, H4, priority=SYMS, max_positions=3)
    assert all(len(r.trades) == 1 and r.locked_signals == 0 for r in results.values())


def test_prefix_invariance_the_past_does_not_depend_on_later_bars() -> None:
    """Cutting the data at a later bar changes nothing before the cut (causality of the lockstep)."""
    bars = {s: walk(2000, 70 + i) for i, s in enumerate(SYMS)}
    full = _portfolio(bars, s7.S7_VARIANTS[1], cap=1)
    cut = 1400
    cut_close = bars["BTCUSDT"][cut - 1].close_time + 1
    part = _portfolio({s: b[:cut] for s, b in bars.items()}, s7.S7_VARIANTS[1], cap=1)
    for sym in SYMS:
        closed_before_cut = [t for t in full[sym].trades if t.exit_time <= cut_close]
        assert closed_before_cut
        assert [t for t in part[sym].trades if t.reason != "end"] == closed_before_cut
        assert part[sym].locked_times == [t for t in full[sym].locked_times if t < cut_close]
        assert part[sym].signals == [s for s in full[sym].signals if s[0] < cut_close]


def test_portfolio_rejects_bad_arguments() -> None:
    bars = {s: walk(300, 1) for s in SYMS}
    strategies = {s: s7.breakout(s7.S7_VARIANTS[0]) for s in SYMS}
    with pytest.raises(ValueError):
        run_portfolio(bars, strategies, H4, priority=("BTCUSDT", "ETHUSDT"))
    with pytest.raises(ValueError):
        run_portfolio(bars, strategies, H4, priority=SYMS + ("BTCUSDT",))
    with pytest.raises(ValueError):
        run_portfolio(bars, strategies, H4, priority=SYMS, max_positions=0)
    dup = {**bars, "SOLUSDT": bars["SOLUSDT"] + bars["SOLUSDT"][-1:]}
    with pytest.raises(ValueError):
        run_portfolio(dup, strategies, H4, priority=SYMS)


# ----------------------------------------------------------------------------- engine: golden regression


def test_run_backtest_matches_the_golden_fixture_of_the_old_engine() -> None:
    """The engine was split into the _Runner state machine for S7b; its single-instrument output must
    stay bit-for-bit what the old engine produced (fixture recorded at commit 7cefb19)."""
    golden = json.loads(GOLDEN.read_text())
    fields = golden["fields"]
    assert golden["engine_commit"] == "7cefb19" and len(golden["cases"]) == 24
    checked = 0
    for case in golden["cases"]:
        bars = walk(1500, case["seed"], gaps=frozenset(case["gaps"]))
        variant = s7.S7_VARIANTS[case["variant"]]
        costs = BASE_COSTS if case["costs"] == "base" else STRESS_COSTS
        r = run_backtest(bars, s7.breakout(variant), H4, costs=costs, start_ms=bars[250].open_time, end_ms=bars[1450].open_time,
                         atr_at_signal=atr_at_signal, gap_entry_as_loss=True)
        assert r.signals and [list(sig) for sig in r.signals] == case["signals"]
        assert r.ignored_signals == case["ignored"] and r.invalid_signals == case["invalid"] and r.gap_closes == case["gap_closes"]
        assert len(r.trades) == len(case["trades"]) > 0
        for trade, expected in zip(r.trades, case["trades"]):
            for name, value in zip(fields, expected):
                got = getattr(trade, name)
                if isinstance(value, float):
                    assert math.isclose(got, value, rel_tol=0.0, abs_tol=1e-12), (case, name, got, value)
                else:
                    assert got == value, (case, name, got, value)
            checked += 1
    assert checked > 500


# ----------------------------------------------------------------------------- hypothesis module


def test_variants_and_params_carry_the_portfolio_rule() -> None:
    assert [v.variant_id for v in s7b.S7B_VARIANTS] == ["S7b-D20-T3", "S7b-D20-T4", "S7b-D55-T3", "S7b-D55-T4"]
    assert [v.variant_id for v in s7b.GATE_VARIANTS] == ["S7b-D20-T3", "S7b-D20-T4"]
    p = s7b.params(s7b.S7B_VARIANTS[0])
    assert p["max_positions"] == 1 and p["priority"] == "BTCUSDT>ETHUSDT>SOLUSDT" and p["parent"] == "S7"
    assert p["channel"] == 20 and p["target_r"] == 3.0 and p["time_stop"] == 30
    assert all(v.hypothesis == "S7b" for v in s7b.S7B_VARIANTS)
    assert s7b.LOCK_MS == 30 * H4


def test_locked_count_is_outcome_blind_and_bounds_the_engine() -> None:
    bars = {s: walk(1800, 50 + i) for i, s in enumerate(SYMS)}
    variant = s7b.S7B_VARIANTS[0]
    start, end = bars["BTCUSDT"][300].open_time, bars["BTCUSDT"][1700].open_time
    windows = {s: (start, end) for s in SYMS}
    count = s7b.count_signals_locked(bars, variant, windows)
    assert count.upper == sum(s7.count_signals(bars[s], variant, start, end).upper for s in SYMS) > count.lower > 0
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
    with pytest.raises(ValueError):
        s7b.count_signals_locked({**bars, "XRPUSDT": bars["BTCUSDT"]}, variant, {**windows, "XRPUSDT": windows["BTCUSDT"]})


def test_locked_count_tie_break_follows_priority_and_counts_ties() -> None:
    same = walk(1200, 7)
    bars = {s: list(same) for s in SYMS}
    start, end = same[250].open_time, same[1150].open_time
    windows = {s: (start, end) for s in SYMS}
    count = s7b.count_signals_locked(bars, s7b.S7B_VARIANTS[1], windows)
    assert count.lower > 0 and {sym for _, sym in count.lower_times} == {"BTCUSDT"}
    assert count.upper == 3 * count.ties  # every signal time is a tie of all three instruments
    reversed_count = s7b.count_signals_locked(bars, s7b.S7B_VARIANTS[1], windows, priority=tuple(reversed(SYMS)))
    assert {sym for _, sym in reversed_count.lower_times} == {"SOLUSDT"} and reversed_count.lower == count.lower
    distinct = {s: walk(1200, 80 + i) for i, s in enumerate(SYMS)}
    assert s7b.count_signals_locked(distinct, s7b.S7B_VARIANTS[1], windows).ties < count.ties


# ----------------------------------------------------------------------------- script: count and gate


class FakeStore:
    def __init__(self, bars: dict[str, list[Kline]]) -> None:
        self.bars = bars
        self.fetched: list[ArchiveRef] = []

    def fetch(self, ref: ArchiveRef, permission=None):
        assert not ref.touches_holdout or permission is not None
        self.fetched.append(ref)

    def load_klines(self, refs, permission=None):
        refs = list(refs)
        assert all(not r.touches_holdout for r in refs) or permission is not None
        symbol = refs[0].symbol
        lo, hi = refs[0].start_ms, refs[-1].end_ms
        return [b for b in self.bars[symbol] if lo <= b.open_time < hi]

    def load_funding(self, refs, permission=None):
        refs = list(refs)
        assert refs[0].dataset is Dataset.FUNDING
        assert all(not r.touches_holdout for r in refs) or permission is not None
        return []

    def dataset_hash(self, refs) -> str:
        return "cafebabe"


def _years(n: int) -> dict[str, list[Kline]]:
    return {s: walk(n * 366 * 6, 60 + i, drift=0.0006) for i, s in enumerate(script.SYMBOLS)}


def test_project_by_month_takes_the_weakest_calendar_year() -> None:
    signals = {2020: 24, 2021: 36, 2022: 12, 2023: 48, 2024: 60}
    weeks = {2020: 20, 2021: 30, 2022: 10, 2023: 40, 2024: 5}
    projected, projected_weeks, weak_signal, weak_week = script.project_by_month(signals, weeks)
    assert (weak_signal, weak_week) == (2022, 2024)
    assert math.isclose(projected, 12 / 12 * script.HOLDOUT_MONTHS) and math.isclose(projected_weeks, 5 / 12 * script.HOLDOUT_MONTHS)
    assert script.project_by_month({}, {}) == (0.0, 0.0, 2020, 2020)  # a missing year counts as zero


def test_section_of_uses_half_open_windows() -> None:
    assert script._section_of(VALIDATION_START_MS - 1, "BTCUSDT") == "train"
    assert script._section_of(VALIDATION_START_MS, "BTCUSDT") == "validation"
    assert script._section_of(HOLDOUT_START_MS - 1, "SOLUSDT") == "validation"
    assert script._section_of(HOLDOUT_START_MS, "SOLUSDT") is None
    assert script._section_of(script.s7script._begin("SOLUSDT") - 1, "SOLUSDT") is None  # before SOL's first month
    assert script._section_of(script.s7script._begin("SOLUSDT"), "SOLUSDT") == "train"


def test_count_writes_gate_report_with_locked_lower_bounds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(script.s7script, "_commit", lambda: "testcommit")
    assert script.count(FakeStore(_years(5)), tmp_path) == 0
    files = sorted(tmp_path.iterdir())
    assert [f.suffix for f in files] == [".json", ".md"] and files[0].name.startswith("s7b_count_")
    payload = json.loads(files[0].read_text())
    assert payload["study"] == "S7b" and payload["parent"] == "S7" and payload["outcome_blind"] is True
    assert payload["lock"] == {"max_positions": 1, "priority": list(SYMS), "lock_bars": 30}
    assert payload["gate"] == {"train": 100, "train_weeks": 60, "validation": 50, "validation_weeks": 30, "holdout": 50, "holdout_weeks": 30}
    assert payload["holdout_months"] == 21 and payload["commit"] == "testcommit"
    assert set(payload["variants"]) == {v.variant_id for v in s7b.S7B_VARIANTS}
    for vid, v in payload["variants"].items():
        assert v["registrable"] == vid.startswith("S7b-D20")
        assert v["passes_gate"] is False or v["registrable"]
        assert sum(v["by_symbol"].values()) == v["totals"]["train"]["lower"] + v["totals"]["validation"]["lower"] <= v["upper_all_instruments"]
        assert v["totals"]["train"]["lower"] > 0 and v["totals"]["validation"]["lower"] > 0
        assert sum(b["lower"] for b in v["by_year"].values()) == v["totals"]["train"]["lower"] + v["totals"]["validation"]["lower"]
        assert set(v["by_year"]) == {"2020", "2021", "2022", "2023", "2024"}
        assert v["ties"] >= 0 and v["projected_holdout_lower"] >= 0 and v["weakest_year_signals"] in range(2020, 2025)
        for sec in ("train", "validation"):
            assert math.isclose(sum(v["instrument_shares"][sec].values()), 1.0)
        assert "hit" not in json.dumps(v) and "expectancy" not in json.dumps(v)
    text = files[1].read_text()
    assert "Positionsgrenze 1" in text and "Ties" in text and "Holdout 2025+ nicht geladen" in text


def test_count_gate_verdict_follows_the_thresholds(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(script.s7script, "_commit", lambda: "testcommit")
    store = FakeStore(_years(5))
    monkeypatch.setattr(script, "GATE_TRAIN", 10**6)
    assert script.count(store, tmp_path / "high") == 0
    high = json.loads(next((tmp_path / "high").glob("*.json")).read_text())
    assert all(v["passes_gate"] is False for v in high["variants"].values())
    for name in ("GATE_TRAIN", "GATE_TRAIN_WEEKS", "GATE_VALIDATION", "GATE_VALIDATION_WEEKS", "GATE_HOLDOUT", "GATE_HOLDOUT_WEEKS"):
        monkeypatch.setattr(script, name, 0)
    assert script.count(store, tmp_path / "zero") == 0
    zero = json.loads(next((tmp_path / "zero").glob("*.json")).read_text())
    assert {vid: v["passes_gate"] for vid, v in zero["variants"].items()} == {
        "S7b-D20-T3": True, "S7b-D20-T4": True, "S7b-D55-T3": False, "S7b-D55-T4": False}  # N 55 is never registrable
    assert "BESTANDEN" in next((tmp_path / "zero").glob("*.md")).read_text()


# ----------------------------------------------------------------------------- script: registration


def _count_report(tmp_path: Path, study: str = "S7b") -> Path:
    report = tmp_path / f"count_{study}.json"
    report.write_text(json.dumps({"study": study, "commit": "abc", "dataset_hash": "d", "variants": {
        "S7b-D20-T3": {"passes_gate": True}, "S7b-D20-T4": {"passes_gate": False},
        "S7b-D55-T3": {"passes_gate": True}, "S7b-D55-T4": {"passes_gate": True}}}))
    return report


def _doc(tmp_path: Path, version: str) -> Path:
    doc = tmp_path / "doc.md"
    doc.write_text(f"# S7b\n\n| Feld | Wert |\n|---|---|\n| Version | **{version}** |\n")
    return doc


def test_register_takes_only_gate_variants_of_a_released_doc(tmp_path: Path) -> None:
    report = _count_report(tmp_path)
    register_path = tmp_path / "REGISTER.jsonl"
    assert script.register_variants(report, register_path, _doc(tmp_path, "0.2")) == 1  # not released
    assert not register_path.exists()
    assert script.register_variants(_count_report(tmp_path, study="S7"), register_path, _doc(tmp_path, "1.0")) == 1  # wrong study
    assert not register_path.exists()
    assert script.register_variants(report, register_path, _doc(tmp_path, "1.0")) == 0
    register = HypothesisRegister(register_path)
    assert list(register.variants()) == ["S7b-D20-T3"]  # D20-T4 failed the gate, D55 is never registrable
    params = register.variants()["S7b-D20-T3"]["params"]
    assert params["max_positions"] == 1 and params["parent"] == "S7" and params["gate_commit"] == "abc"
    assert params["gate_report"] == "count_S7b.json" and params["dataset_hash"] == "d"
    assert script.register_variants(report, register_path, _doc(tmp_path, "1.0")) == 0 and register.m == 1  # idempotent


def test_the_real_doc_is_not_released_before_uzi_s_card() -> None:
    """Guard against registering from a draft: the committed doc must not read 1.0 unless released."""
    text = (ROOT / script.DOC).read_text()
    register = HypothesisRegister(ROOT / script.REGISTER)
    registered = [v for v in register.variants() if v.startswith("S7b-")]
    assert ("| Version | **1.0" in text) == bool(registered), "doc 1.0 and S7b register entries belong together"


# ----------------------------------------------------------------------------- script: verdict helpers


def _summary(n: int, weeks: int, expectancy: float = 0.3) -> ev.Summary:
    base = ev.summarize({}, 3.0)
    return dataclasses.replace(base, n=n, signal_weeks=weeks, expectancy=expectancy, profit_factor=1.5, max_drawdown=5.0)


def test_verdicts_use_the_s7_minimums_for_s7b() -> None:
    assert script.MINIMUMS == {"train": (200, 100), "validation": (100, 50), "holdout": (100, 60)}
    assert ev.training_verdict(_summary(200, 100), 0.001, 0.001, script.MINIMUMS)["pass"]
    assert ev.training_verdict(_summary(199, 100), 0.001, 0.001, script.MINIMUMS)["reasons"] == ["n < 200"]
    assert ev.training_verdict(_summary(200, 99), 0.001, 0.001, script.MINIMUMS)["reasons"] == ["Signal-Wochen < 100"]
    robust = {"Jahresstabilität": True, "Walk-Forward": True, "Nachbarschaft": True}
    assert ev.validation_verdict(_summary(100, 50), 0.001, 0.001, robust, script.MINIMUMS)["pass"]
    assert ev.validation_verdict(_summary(99, 50), 0.001, 0.001, robust, script.MINIMUMS)["reasons"] == ["n < 100"]
    assert not ev.sample_ok(_summary(99, 60), "holdout", script.MINIMUMS) and ev.sample_ok(_summary(100, 60), "holdout", script.MINIMUMS)
    assert ev.sample_ok(_summary(60, 40), "holdout", {"holdout": (50, 30)})  # looser minimums would pass: the study keeps S7's


def test_neighbour_rule_and_candidates_work_on_s7b_ids() -> None:
    train = {"S7b-D20-T3": 0.2, "S7b-D20-T4": 0.3, "S7b-D55-T3": 0.1, "S7b-D55-T4": -0.1}
    d20t3 = s7b.S7B_VARIANTS[0]
    assert ev.neighbour_rule(train, d20t3, s7b.S7B_VARIANTS) is True
    assert ev.neighbour_rule(train, s7b.S7B_VARIANTS[1], s7b.S7B_VARIANTS) is False  # neighbour D55-T4 negative
    assert ev.neighbour_rule({k.replace("S7b", "S7"): v for k, v in train.items()}, d20t3, s7b.S7B_VARIANTS) is False  # S7 ids are unknown
    with pytest.raises(TypeError):
        ev.neighbour_rule(train, d20t3)  # the grid is mandatory
    validation = {"S7b-D20-T3": 0.2, "S7b-D55-T3": 0.25, "S7b-D20-T4": 0.1}
    assert ev.select_candidates(validation, s7b.S7B_VARIANTS) == ["S7b-D20-T4", "S7b-D55-T3"]
    assert ev.select_candidates(validation, s7b.GATE_VARIANTS) == ["S7b-D20-T3", "S7b-D20-T4"]
    assert ev.select_candidates({}, s7b.S7B_VARIANTS) == []


def test_iid_drawdown_share_is_a_probability_and_deterministic() -> None:
    bars = walk(1500, 90)
    trades = run_backtest(bars, s7.breakout(s7.S7_VARIANTS[0]), H4, gap_entry_as_loss=True).trades
    assert len(trades) > 10
    share = script.iid_drawdown_share(trades, limit=1.0, shuffles=200)
    assert 0.0 < share <= 1.0 and share == script.iid_drawdown_share(trades, limit=1.0, shuffles=200)
    assert script.iid_drawdown_share(trades, limit=10**6, shuffles=50) == 0.0
    assert script.iid_drawdown_share([], shuffles=50) is None


# ----------------------------------------------------------------------------- script: training and validation


def _small_baselines(monkeypatch) -> None:
    monkeypatch.setattr(ev, "POOL_PER_DECILE", 40)
    monkeypatch.setattr(ev, "MIN_POOL", 80)
    monkeypatch.setattr(ev, "POOL_FACTOR", 2)
    monkeypatch.setattr(script, "IID_SHUFFLES", 50)
    monkeypatch.setattr(script.s7script, "_commit", lambda: "testcommit")


def test_train_applies_portfolio_cap_and_s7_minimums(tmp_path: Path, monkeypatch) -> None:
    _small_baselines(monkeypatch)
    bars = _years(5)
    register_path = tmp_path / "REGISTER.jsonl"
    assert script.train(FakeStore(bars), tmp_path / "none", register_path=register_path) == 1
    assert not (tmp_path / "none").exists()
    register = HypothesisRegister(register_path)
    for v in s7b.GATE_VARIANTS:
        register.register(v.variant_id, s7b.HYPOTHESIS, s7b.params(v))
    out = tmp_path / "reports"
    lines: list[str] = []
    assert script.train(FakeStore(bars), out, runs=25, register_path=register_path, commit_register=True, progress=lines.append) == 0
    files = sorted(out.iterdir())
    assert len(files) == 3 and all(f.name.startswith("s7b_train_") for f in files)
    payload = json.loads(next(f for f in files if f.name.endswith("Z.json")).read_text())
    assert payload["study"] == "S7b" and payload["parent"] == "S7" and payload["holm_m"] == 60
    assert payload["minimums"] == {"train": [200, 100], "validation": [100, 50], "holdout": [100, 60]}
    assert payload["registered"] == ["S7b-D20-T3", "S7b-D20-T4"] and payload["lock"]["max_positions"] == 1
    assert "Portfolio-Lauf" in payload["stress_rule"]
    for vid, entry in payload["variants"].items():
        assert entry["params"]["max_positions"] == 1 and entry["registered"] == vid.startswith("S7b-D20")
        assert set(entry["locked_signals"]) == set(entry["ignored_signals"]) == {"train", "validation"}
        assert all(entry["locked_signals"][s] <= entry["ignored_signals"][s] for s in ("train", "validation"))
        assert sum(entry["locked_signals"].values()) > 0
        for section in ("train", "validation"):
            sec = entry["sections"][section]
            assert sec["summary"]["n"] > 0 and set(sec["baselines"]) == {"A", "A'", "C", "B"}
            assert sec["stress_n"] > 0 and isinstance(sec["stress_expectancy"], float)
            assert 0.0 <= sec["iid_drawdown_over_limit"] <= 1.0
            assert len(sec["bootstrap_ci_95"]) == 2 and set(sec["buy_and_hold"]) == set(SYMS)
            assert ("reversed_priority" in sec) == entry["registered"]
            if entry["registered"]:
                assert sec["reversed_priority"]["n"] > 0 and set(sec["reversed_priority"]["by_symbol"]) <= set(SYMS)
        if vid.startswith("S7b-D55"):
            assert entry["status"] == "nicht registriert (nur Nachbar)"
        else:
            assert entry["status"] in {"failed_train", "failed_validation", "candidate", "not_selected"}
            assert "training_verdict" in entry
    assert all(c in payload["registered"] for c in payload["candidates"])
    trades = json.loads(next(f for f in files if f.name.endswith("trades.json")).read_text())
    by_variant: dict[str, list] = {}
    for t in trades:
        by_variant.setdefault(t["variant"], []).append((t["entry_time"], t["exit_time"]))
    assert set(by_variant) == set(payload["variants"])
    for rows in by_variant.values():
        rows.sort()
        assert all(b[0] >= a[1] for a, b in zip(rows, rows[1:]))  # the cap holds in the recorded trades
    text = next(f for f in files if f.suffix == ".md").read_text()
    assert "Positionsgrenze 1" in text and "## Urteile" in text and "Ableitung aus S7" in text and "verfallen" in text
    statuses = {v: e["status"] for v, e in HypothesisRegister(register_path).variants().items()}
    assert set(statuses) == {"S7b-D20-T3", "S7b-D20-T4"} and all(s != "registered" for s in statuses.values())
    assert any("verfallen" in line for line in lines)


# ----------------------------------------------------------------------------- script: holdout


def test_holdout_needs_approval_and_a_candidate(tmp_path: Path) -> None:
    register_path = tmp_path / "REGISTER.jsonl"
    lock = tmp_path / "lock.json"
    assert script.holdout(FakeStore({}), tmp_path / "out", approval="  ", register_path=register_path, lock_path=lock) == 1
    HypothesisRegister(register_path).register("S7b-D20-T3", "S7b", s7b.params(s7b.S7B_VARIANTS[0]))
    assert script.holdout(FakeStore({}), tmp_path / "out", approval="Karte 26.10.", register_path=register_path, lock_path=lock) == 1
    assert not lock.exists() and not (tmp_path / "out").exists()


def test_holdout_runs_once_from_a_flat_start_and_consumes_the_lock(tmp_path: Path, monkeypatch) -> None:
    _small_baselines(monkeypatch)
    bars = _years(7)  # 2020-01 .. 2026-12, the holdout window ends 2026-10-01
    register_path = tmp_path / "REGISTER.jsonl"
    register = HypothesisRegister(register_path)
    for v in s7b.GATE_VARIANTS:
        register.register(v.variant_id, s7b.HYPOTHESIS, s7b.params(v))
    register.set_status("S7b-D20-T3", "candidate", "test")
    register.set_status("S7b-D20-T4", "failed_validation", "test")
    lock = tmp_path / "HOLDOUT_LOCK.json"
    store = FakeStore(bars)
    out = tmp_path / "out"
    assert script.holdout(store, out, approval="Karte 26.10. 20:00", runs=25, register_path=register_path, lock_path=lock,
                          progress=lambda line: None) == 0
    assert json.loads(lock.read_text())["candidates"] == ["S7b-D20-T3"] and json.loads(lock.read_text())["m"] == 2
    with pytest.raises(FileExistsError):  # the lock is exclusive: no second holdout run
        script.holdout(store, out, approval="noch einmal", runs=25, register_path=register_path, lock_path=lock)
    assert HypothesisRegister(register_path).variants()["S7b-D20-T3"]["status"] == "candidate"  # untouched without --commit-register
    assert len(list(out.iterdir())) == 2
    out = tmp_path / "out_final"
    assert script.holdout(store, out, approval="Karte 26.10. 20:00", runs=25, register_path=register_path, lock_path=tmp_path / "lock2.json",
                          commit_register=True, progress=lambda line: None) == 0
    assert {(r.year, r.month) for r in store.fetched} == set(script.months((2025, 1), (2026, 9)))
    assert all(r.touches_holdout for r in store.fetched) and len(store.fetched) == 2 * 3 * 2 * 21  # two runs, 3 symbols x 2 datasets x 21 months
    files = sorted(out.iterdir())
    assert [f.suffix for f in files] == [".json", ".md"] and files[0].name.startswith("s7b_holdout_")
    payload = json.loads(files[0].read_text())
    assert payload["candidates"] == ["S7b-D20-T3"] and list(payload["variants"]) == ["S7b-D20-T3"]
    assert payload["approval"] == "Karte 26.10. 20:00" and payload["register_m"] == 2 and payload["holm_m"] == 60
    assert payload["lock"]["window"] == [HOLDOUT_START_MS, script.HOLDOUT_END_MS]
    entry = payload["variants"]["S7b-D20-T3"]
    assert entry["status"] in {"passed_holdout", "failed_holdout", "no_verdict"}
    assert set(entry["judgement"]) == {f"K{i}" for i in range(1, 11)} | {"verdict"}
    assert entry["judgement"]["K3"]["min"] == [100, 60]
    assert entry["trades"] and all(t["entry_time"] >= HOLDOUT_START_MS for t in entry["trades"])  # flat start, nothing carried over
    assert all(t["exit_time"] <= script.HOLDOUT_END_MS for t in entry["trades"])
    rows = sorted((t["entry_time"], t["exit_time"]) for t in entry["trades"])
    assert all(b[0] >= a[1] for a, b in zip(rows, rows[1:]))
    assert entry["summary"]["n"] == len(entry["trades"]) and 0.0 <= entry["iid_drawdown_over_limit"] <= 1.0
    assert HypothesisRegister(register_path).variants()["S7b-D20-T3"]["status"] == entry["status"]
    assert "verbraucht" in files[1].read_text()
    assert entry["status"] != "candidate"  # the final status is written and cannot be reopened
    assert script.holdout(store, out, approval="noch einmal", runs=25, register_path=register_path, lock_path=tmp_path / "lock3.json") == 1
    assert not (tmp_path / "lock3.json").exists()
