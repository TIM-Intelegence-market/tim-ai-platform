"""S7 evaluation (sections 5-7): cost geometry, pooled summary, judgement K1-K10, baselines A/A'/B/C, selection."""
from __future__ import annotations

import random

import pytest

from src.research_lab.backtest.engine import Trade, run_backtest
from src.research_lab.data.parse import Kline
from src.research_lab.hypotheses import s7
from src.research_lab.protocol import BASE_COSTS
from src.research_lab.stats.random_entry import atr_at_signal
from src.research_lab.studies import s7_eval as ev

H4 = s7.INTERVAL_MS
T0 = 1_577_836_800_000  # 2020-01-01


def bar(i: int, o: float, h: float, l: float, c: float) -> Kline:
    return Kline(T0 + i * H4, o, h, l, c, 10.0, T0 + (i + 1) * H4 - 1, 5.0)


def walk(n: int, seed: int, *, drift: float = 0.0, scale: float = 0.02) -> list[Kline]:
    rng = random.Random(seed)
    price, bars = 100.0, []
    for i in range(n):
        o = price
        c = o * (1 + drift + rng.gauss(0, scale))
        h = max(o, c) * (1 + abs(rng.gauss(0, scale / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, scale / 2)))
        bars.append(bar(i, o, h, l, c))
        price = c
    return bars


def trade(i: int, r: float, reason: str, side: int = 1, *, symbol_offset: int = 0, held: int = 5, stop_pct: float = 0.02) -> Trade:
    signal = T0 + (i * 42 + symbol_offset) * H4  # one signal per week and instrument
    return Trade(signal, signal + H4, signal + (held + 1) * H4, side, 100.0, 100.0 + side * r, 100.0 - side * 100.0 * stop_pct,
                 reason, held, r, 0.05, 0.0, 1.5, 3.0)


def test_p_star_matches_the_pre_registration_table() -> None:
    assert abs(ev.p_star(3.0, 0.01) - 0.2935) < 0.0005
    assert abs(ev.p_star(4.0, 0.01) - 0.2351) < 0.0005
    assert abs(ev.p_star(3.0, 0.025) - 0.2675) < 0.0005
    assert abs(ev.p_star(4.0, 0.025) - 0.2141) < 0.0005
    c_w, c_l = ev.cost_r(0.01)
    assert abs(c_w - 0.16) < 1e-9 and abs(c_l - 0.18) < 1e-9


def _trades(n_hits: int, n_losses: int, n_time: int, symbol_offset: int = 0) -> list[Trade]:
    kinds = ["hit"] * n_hits + ["loss"] * n_losses + ["time"] * n_time
    random.Random(7 + symbol_offset).shuffle(kinds)  # spread outcomes over the years
    out = []
    for i, kind in enumerate(kinds):
        if kind == "hit":
            out.append(trade(i, 2.9, "target", symbol_offset=symbol_offset))
        elif kind == "loss":
            out.append(trade(i, -1.08, "stop", side=-1, symbol_offset=symbol_offset))
        else:
            out.append(trade(i, 0.4, "time", symbol_offset=symbol_offset))
    return out


def test_summary_pools_instruments_and_clusters_by_signal_week() -> None:
    by_symbol = {"BTCUSDT": _trades(25, 35, 5), "ETHUSDT": _trades(15, 25, 5, 1), "SOLUSDT": _trades(10, 20, 5, 2)}
    s = ev.summarize(by_symbol, 3.0)
    assert s.n == 145 and s.hits == 50
    assert abs(s.hit_rate - 50 / 145) < 1e-9
    assert s.by_symbol == {"BTCUSDT": 65, "ETHUSDT": 45, "SOLUSDT": 35}
    assert s.by_side == {"long": 65, "short": 80}
    assert s.by_reason == {"stop": 80, "target": 50, "time": 15}
    assert abs(s.mean_hit_r - 2.9) < 1e-9
    assert abs(s.mean_stop_fraction - 0.02) < 1e-9
    assert abs(s.p_star - ev.p_star(3.0, 0.02)) < 1e-12
    assert 1 <= s.signal_weeks <= 145
    assert s.design_effect >= 1.0 and s.n_eff <= s.n
    assert {2020, 2021} <= set(s.expectancy_by_year)
    assert s.signal_weeks >= 60


def test_judge_applies_k1_to_k10_with_k6_reported_only() -> None:
    by_symbol = {"BTCUSDT": _trades(25, 35, 5), "ETHUSDT": _trades(15, 25, 5, 1), "SOLUSDT": _trades(10, 20, 5, 2)}
    out = ev.judge(by_symbol, by_symbol, 3.0, 0.0004, True)
    assert out["K1"]["pass"] and out["K2"]["pass"] and out["K5"]["pass"] and out["K7"]["pass"]
    assert out["K3"]["min"] == [100, 60]
    assert out["K4"]["pass"] is (out["K4"]["max_drawdown"] <= 20.0)
    assert out["K6"]["criterion"] is False and out["K6"]["pass"] is True
    assert out["K8"]["pass"] and out["K8"]["forced_share"] == 15 / 145
    assert out["K9"]["pass"] and out["K9"]["required"] == 2.5
    assert out["K10"]["pass"] and set(out["K10"]["side_shares"]) == {"long", "short"}
    # too few trades: no verdict regardless of the rest
    small = {"BTCUSDT": _trades(10, 10, 0), "ETHUSDT": _trades(10, 10, 0, 1), "SOLUSDT": _trades(10, 10, 0, 2)}
    assert ev.judge(small, small, 3.0, 0.0004, True)["verdict"]["verdict"] == "KEIN URTEIL"
    # not significant under Holm: failed
    assert ev.judge(by_symbol, by_symbol, 3.0, 0.3, False)["verdict"]["verdict"] == "NICHT BESTANDEN"
    # one instrument below 15 %: K10 fails
    thin = {"BTCUSDT": _trades(40, 60, 10), "ETHUSDT": _trades(30, 50, 10, 1), "SOLUSDT": _trades(2, 3, 0, 2)}
    assert not ev.judge(thin, thin, 3.0, 0.0004, True)["K10"]["pass"]


def test_hits_below_target_fail_k9() -> None:
    cheap = {"BTCUSDT": [trade(i, 2.2, "target") for i in range(40)] + [trade(50 + i, -1.1, "stop") for i in range(40)],
             "ETHUSDT": [trade(i, 2.2, "target", symbol_offset=1) for i in range(30)],
             "SOLUSDT": [trade(i, 2.2, "target", symbol_offset=2) for i in range(30)]}
    out = ev.judge(cheap, cheap, 3.0, 0.0004, True)
    assert not out["K9"]["pass"] and abs(out["K9"]["mean_hit_r"] - 2.2) < 1e-9


def test_training_and_validation_verdicts_list_reasons() -> None:
    by_symbol = {"BTCUSDT": _trades(60, 80, 20), "ETHUSDT": _trades(50, 70, 20, 1), "SOLUSDT": _trades(40, 60, 20, 2)}
    s = ev.summarize(by_symbol, 3.0)
    assert s.n == 420
    ok = ev.training_verdict(s, 0.01, 0.02)
    assert ok["pass"] is (s.signal_weeks >= 100), ok
    bad = ev.training_verdict(s, 0.2, 0.01)
    assert "p(A) >= 0.1" in bad["reasons"]
    v = ev.validation_verdict(s, 0.01, 0.01, {"Jahresstabilität": True, "Walk-Forward": False})
    assert "Robustheit: Walk-Forward" in v["reasons"]


def test_candidate_selection_one_per_target_at_most_two() -> None:
    scores = {"S7-D20-T3": 0.2, "S7-D55-T3": 0.3, "S7-D20-T4": 0.1, "S7-D55-T4": 0.05}
    assert ev.select_candidates(scores) == ["S7-D20-T4", "S7-D55-T3"]
    assert ev.select_candidates({"S7-D20-T3": 0.2}) == ["S7-D20-T3"]
    assert ev.select_candidates({}) == []


def test_neighbour_rule_and_year_rule() -> None:
    train = {"S7-D20-T3": 0.2, "S7-D20-T4": 0.1, "S7-D55-T3": -0.1, "S7-D55-T4": 0.3}
    assert not ev.neighbour_rule(train, s7.S7_VARIANTS[0])  # D20-T3 has neighbour D55-T3 <= 0
    assert ev.neighbour_rule({"S7-D20-T3": 0.2, "S7-D20-T4": 0.1, "S7-D55-T3": 0.1, "S7-D55-T4": 0.3}, s7.S7_VARIANTS[0])
    good = ev.summarize({"BTCUSDT": _trades(40, 40, 10)}, 3.0)
    bad = ev.summarize({"BTCUSDT": [trade(i, -1.0, "stop") for i in range(60)]}, 3.0)
    assert ev.year_rule(good, good)
    assert not ev.year_rule(bad, bad)


def _section(bars: list[Kline], funding=()) -> ev.SectionData:
    return ev.SectionData(bars, ev.atr_series_contiguous(bars), funding, bars[250].open_time, bars[-1].open_time + H4)


def _run(bars_by_symbol: dict[str, list[Kline]], variant: s7.S7Variant) -> dict[str, list[Trade]]:
    out = {}
    for symbol, bars in bars_by_symbol.items():
        result = run_backtest(bars, s7.breakout(variant), H4, costs=BASE_COSTS, start_ms=bars[250].open_time,
                              atr_at_signal=atr_at_signal, gap_entry_as_loss=True)
        out[symbol] = [t for t in result.trades if t.reason != "end"]
    return out


def test_baselines_a_aprime_c_and_b_on_synthetic_bars() -> None:
    bars_by_symbol = {"BTCUSDT": walk(1600, 11, drift=0.003), "ETHUSDT": walk(1600, 12, drift=0.003), "SOLUSDT": walk(1600, 13, drift=0.003)}
    data = {s: _section(b) for s, b in bars_by_symbol.items()}
    trades = _run(bars_by_symbol, s7.S7_VARIANTS[0])
    assert sum(len(t) for t in trades.values()) >= 10
    a = ev.random_baseline(data, trades, mode="A", runs=200)
    a_prime = ev.random_baseline(data, trades, mode="A'", runs=200)
    c = ev.random_baseline(data, trades, mode="C", runs=200)
    for res in (a, a_prime, c):
        assert 0 < res.p <= 1 and 0 <= res.hit_rate <= 1 and res.pool_sizes
    assert set(a.pool_sizes) == set(bars_by_symbol)
    assert all("/" in k for k in a_prime.pool_sizes) and all(k.endswith(("long", "short")) for k in c.pool_sizes)
    # deterministic for the seed
    assert ev.random_baseline(data, trades, mode="A", runs=200).p == a.p
    # candidates stay 31 bars before the section end and need a contiguous ATR window
    cands = data["BTCUSDT"].candidates()
    assert max(cands) <= 1600 - ev.EDGE_BARS - 1 and min(cands) >= 250
    # mirrored trades: same count, opposite side, reasons from the engine vocabulary
    b = ev.mirrored(data, trades)
    assert {s: len(v) for s, v in b.items()} == {s: len(v) for s, v in trades.items()}
    summary = ev.baseline_summary(b)
    assert summary["n"] == sum(len(v) for v in trades.values())
    assert ev.buy_and_hold(data["BTCUSDT"]) is not None


def test_atr_series_is_none_across_a_gap() -> None:
    bars = walk(60, 3)
    shifted = bars[:30] + [Kline(b.open_time + H4, b.open, b.high, b.low, b.close, 10.0, b.close_time + H4, 5.0) for b in bars[30:]]
    values = ev.atr_series_contiguous(shifted)
    assert values[29] is not None and values[59] is not None
    assert all(v is None for v in values[30:30 + s7.ATR_PERIOD])
    assert values[30 + s7.ATR_PERIOD] is not None


def test_random_baseline_rejects_trades_without_atr() -> None:
    bars = walk(400, 4)
    data = {"BTCUSDT": _section(bars)}
    t = Trade(bars[300].open_time, bars[301].open_time, bars[305].open_time, 1, 100.0, 101.0, 98.0, "target", 5, 2.9, 0.05, 0.0, None, 3.0)
    with pytest.raises(ValueError):
        ev.random_baseline(data, {"BTCUSDT": [t]}, runs=10)


def test_trend_series_matches_pointwise_trend() -> None:
    bars = walk(400, 9, drift=0.001)
    series = ev.trend_series(bars)
    assert len(series) == 400 and all(v is None for v in series[:199])
    assert all(series[i] == ev.trend_at(bars, i) for i in range(199, 400, 7))
    data = ev.SectionData(bars, ev.atr_series_contiguous(bars), (), bars[250].open_time, bars[-1].open_time + H4, series)
    assert data.trend(300) == series[300]
