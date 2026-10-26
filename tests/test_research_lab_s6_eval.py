"""Study S6 metrics, judgement and baselines (sections 5-7)."""
from __future__ import annotations

import math

import pytest

from src.research_lab.hypotheses import s6
from src.research_lab.hypotheses.s6 import LONG, SHORT, Trade
from src.research_lab.studies import s6_eval as ev

T0 = 1_577_836_800_000


def trade(net_r: float, *, day: int = 0, side: int = LONG, reason: str = "target", ambiguous: bool = False) -> Trade:
    t = T0 + day * 86_400_000
    return Trade(side, 0, t, 100.0, 1, t + 60_000, 100.0, reason, ambiguous, 0.0, 0.0, net_r)


def test_clopper_pearson_matches_known_values() -> None:
    # section 6: n = 80, 0 / 3 / 4 losers -> 96.3 / 90.6 / 88.9 %; n = 160 with 9 losers -> 90.4 %
    assert ev.clopper_pearson_lower(80, 80) == pytest.approx(0.9632, abs=5e-4)
    assert ev.clopper_pearson_lower(77, 80) == pytest.approx(0.9059, abs=5e-4)
    assert ev.clopper_pearson_lower(76, 80) == pytest.approx(0.8892, abs=5e-4)
    assert ev.clopper_pearson_lower(151, 160) == pytest.approx(0.9039, abs=5e-4)
    assert ev.clopper_pearson_lower(0, 10) == 0.0


def test_design_effect_and_effective_counts() -> None:
    # independent-looking hits spread over days: D close to 1; all losers on one day: D large
    hits = [True] * 95 + [False] * 5
    spread = [str(i) for i in range(100)]
    assert ev.design_effect(hits, spread) == pytest.approx(1.0, abs=0.02)  # 100/99 from the G/(G-1) factor
    clustered = ["loss-day"] * 5 + [str(i) for i in range(95)]
    hits2 = [False] * 5 + [True] * 95
    assert ev.design_effect(hits2, clustered) > 2.0
    assert ev.design_effect([True] * 10, ["a"] * 10) == 1.0
    assert ev.effective_counts(320, 18, 2.0) == (160, 9)
    assert ev.effective_counts(321, 17, 2.0) == (160, 9)


def test_summary_and_drawdown() -> None:
    trades = [trade(0.2, day=i) for i in range(19)] + [trade(-1.08, day=19, reason="stop")]
    s = ev.summarize(trades)
    assert s.n == 20 and s.hits == 19 and s.hit_rate == 0.95
    assert s.expectancy == pytest.approx((19 * 0.2 - 1.08) / 20)
    assert s.profit_factor == pytest.approx(19 * 0.2 / 1.08)
    assert s.max_drawdown == pytest.approx(1.08)
    assert s.mean_win == pytest.approx(0.2) and s.mean_loss == pytest.approx(-1.08) and s.worst_loss == -1.08
    assert ev.max_drawdown_r([1, -2, 1, -3]) == pytest.approx(4.0)


def test_judgement_passes_a_clean_sample_and_fails_on_k3_k6() -> None:
    wins = [trade(0.2, day=i % 300, side=LONG if i % 2 else SHORT) for i in range(380)]
    losses = [trade(-1.08, day=300 + i, reason="stop") for i in range(12)]
    by_symbol = {"BTCUSDT": wins[:130] + losses[:4], "ETHUSDT": wins[130:260] + losses[4:8], "SOLUSDT": wins[260:] + losses[8:]}
    stress = {k: [trade(t.net_r * 0.8 if t.net_r > 0 else t.net_r, day=i) for i, t in enumerate(v)] for k, v in by_symbol.items()}
    out = ev.judge(by_symbol, stress, baseline_p=0.0001, holm_threshold=0.05 / 60)
    assert out["K6"]["hit_rate"] == pytest.approx(380 / 392)
    assert out["K3"]["pass"] and out["K6"]["pass"] and out["K1"]["pass"] and out["K9"]["pass"] and out["K10"]["pass"]
    assert out["verdict"]["verdict"] == "BESTANDEN (Holdout)"
    small = {k: v[:40] for k, v in by_symbol.items()}
    assert ev.judge(small, small, 0.0001, 0.05 / 60)["verdict"]["verdict"] == "KEIN URTEIL"
    more_losses = {k: v + [trade(-1.08, day=400 + i, reason="stop") for i in range(10)] for k, v in by_symbol.items()}
    out2 = ev.judge(more_losses, more_losses, 0.0001, 0.05 / 60)
    assert not out2["K6"]["pass"] and out2["verdict"]["verdict"] == "NICHT BESTANDEN"


def test_fill_haircut_removes_the_best_trades() -> None:
    trades = [trade(r) for r in (0.5, 0.2, 0.1, -1.0, 0.3)]
    kept = ev.fill_haircut(trades, 0.05)  # 5 % of 5 -> 1 trade
    assert len(kept) == 4 and max(t.net_r for t in kept) == 0.3
    assert len(ev.fill_haircut(trades, 0.4)) == 3


def _market(n: int = 2_000) -> list:
    rnd = __import__("random").Random(7)
    bars = []
    price = 100.0
    for i in range(n):
        o = price
        c = price * (1 + rnd.gauss(0, 0.0007))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0003)))
        lo = min(o, c) * (1 - abs(rnd.gauss(0, 0.0003)))
        t = T0 + i * 60_000
        bars.append(s6.Kline(t, o, h, lo, c, 10.0, t + 59_999, 5.0))
        price = c
    return bars


def test_baselines_are_deterministic_and_use_the_variants_exits() -> None:
    bars = _market()
    ref = s6.compute_reference(bars)
    ticks = s6.empirical_ticks(bars)
    variant = s6.S6_VARIANTS[0]
    end = bars[-1].open_time + 60_000
    pool = ev.build_pool(bars, ref, [], variant, T0, end, s6.BASE_COSTS, ticks, per_decile=20)
    pool2 = ev.build_pool(bars, ref, [], variant, T0, end, s6.BASE_COSTS, ticks, per_decile=20)
    assert pool.results == pool2.results and all(len(v) == 20 for v in pool.results.values())
    cuts = ev.sigma_deciles(ref, bars, T0, end)
    assert len(cuts) == 9 and cuts == sorted(cuts)
    fills = [("x", 3), ("x", 5), ("x", 9)]
    p, mean = ev.baseline_a_pvalue(fills, {"x": pool}, observed_expectancy=10.0, runs=200)
    assert p == pytest.approx(1 / 201)  # nothing beats 10 R
    p2, _ = ev.baseline_a_pvalue(fills, {"x": pool}, observed_expectancy=-10.0, runs=200)
    assert p2 == 1.0
    t = ev.random_entry_trade(bars, 500, LONG, variant, ticks["2020-01"], s6.BASE_COSTS, end, [], [])
    assert t.entry_fill == bars[500].open and t.reason in ("stop", "target", "time", "section_end")
    mirrored = ev.mirrored_trades(bars, [t], variant, s6.BASE_COSTS, end, ticks, [])
    assert mirrored[0].side == SHORT and mirrored[0].entry_fill == t.entry_fill
    lo, hi = ev.day_block_bootstrap([trade(0.2, day=i) for i in range(5)] + [trade(-1.0, day=5)], draws=100)
    assert lo <= hi and not math.isnan(lo)
