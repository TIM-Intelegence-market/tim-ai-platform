"""P3 order-flow signals F1-F10: arithmetic on hand-made bars and a look-ahead test for every bar-based signal."""
from __future__ import annotations

import random

import pytest

from src.research_lab.fusion import of_features as f
from src.research_lab.fusion.of_features import Bar

M = 60_000


def bar(i, o, h, lo, c, buy=10.0, sell=10.0):
    return Bar(i * M, o, h, lo, c, buy, sell)


def random_bars(n=120, seed=7):
    rnd = random.Random(seed)
    out, p = [], 100.0
    for i in range(n):
        o = p
        c = o * (1 + rnd.gauss(0, 0.004))
        h, lo = max(o, c) * (1 + abs(rnd.gauss(0, 0.002))), min(o, c) * (1 - abs(rnd.gauss(0, 0.002)))
        out.append(Bar(i * M, o, h, lo, c, rnd.uniform(5, 30), rnd.uniform(5, 30)))
        p = c
    return out


def test_bars_from_trades():
    trades = [{"ts_ms": 5, "price": 10, "qty": 1, "side": 1},
              {"ts_ms": M - 1, "recv_ms": M + 500, "price": 12, "qty": 2, "side": -1},
              {"ts_ms": M + 1, "price": 11, "qty": 3, "side": 1}]
    b = f.bars_from_trades(trades, M)
    assert len(b) == 2
    assert b[0].known_ms == M + 500 and b[1].known_ms == 2 * M  # never before the bar end
    assert (b[0].open, b[0].high, b[0].low, b[0].close, b[0].buy, b[0].sell) == (10, 12, 10, 12, 1, 2)
    assert b[0].delta == -1 and f.cvd(b, 1) == 2
    with pytest.raises(ValueError):
        f.bars_from_trades([{"ts_ms": 1, "price": 1, "qty": 1, "side": 0}], M)


SIGNALS = {
    "F1": lambda b, i: f.cvd_divergence(b, i, lookback=20, right=2, k_sigma=0.5),
    "F2": lambda b, i: f.aggressor_imbalance(b, i, 5, history=40),
    "F3": lambda b, i: f.absorption(b, i, level=100.0, band=3.0, history=20, z_min=1.0, max_move_atr=0.5),
    "F6": lambda b, i: f.sweep(b, i, lookback=20, m=3, min_excess=0.0005, vol_mult=1.0),
    "F7": lambda b, i: f.failed_breakout(b, i, lookback=20, m=3, min_width_atr=0.5),
}


@pytest.mark.parametrize("name", sorted(SIGNALS))
def test_no_look_ahead(name):
    bars = random_bars(400)
    fn = SIGNALS[name]
    fired = 0
    for i in range(30, 380, 3):
        before = fn(bars, i)
        fired += before[0] is not None if isinstance(before, tuple) else before != 0
        future = [Bar(b.open_ms, b.open * 3, b.high * 3, b.low * 0.1, b.close * 2, b.buy * 9, 0.0) for b in bars[i + 1:]]
        assert fn(bars[: i + 1] + future, i) == before, (name, i)
    assert fired > 0, f"{name} never fired on the test data, so the look-ahead test proved nothing"


def test_cvd_divergence_bearish():
    bars = [bar(i, 100, 101, 99, 100) for i in range(25)]
    bars[10] = bar(10, 100, 105, 99, 104, buy=200, sell=10)     # swing high with strong buying
    bars += [bar(25, 100, 106, 99, 105, buy=5, sell=400)]        # new high on heavy selling
    assert f.cvd_divergence(bars, 25, lookback=20, right=2, k_sigma=0.1) == -1


def test_aggressor_imbalance_z():
    bars = [bar(i, 100, 101, 99, 100, buy=10 + (i % 3), sell=10) for i in range(50)]
    bars += [bar(50 + k, 100, 101, 99, 100, buy=50, sell=5) for k in range(5)]
    ai, z = f.aggressor_imbalance(bars, 54, 5, history=40)
    assert ai == pytest.approx(225 / 275) and z is not None and z > 3


def test_absorption_bullish():
    bars = [bar(i, 100, 100.5, 99.5, 100, buy=10, sell=10 + (i % 2)) for i in range(30)]
    bars.append(bar(30, 100, 100.2, 98.9, 99.9, buy=10, sell=120))  # heavy selling into 99, little damage
    assert f.absorption(bars, 30, level=99.0, band=0.2, history=20, z_min=3, max_move_atr=0.5) == 1
    assert f.absorption(bars, 30, level=110.0, band=0.2, history=20, z_min=3, max_move_atr=0.5) == 0


def test_book_measures():
    assert f.book_imbalance([(99, 3), (98, 1)], [(101, 1), (102, 1)], 2) == pytest.approx(2 / 6)
    assert f.microprice(99, 3, 101, 1) == pytest.approx(100.5)
    assert f.ofi((99, 5, 101, 5), (99, 7, 101, 5)) == 2          # bid queue grew
    assert f.ofi((99, 5, 101, 5), (100, 1, 101, 5)) == 1         # new better bid
    assert f.ofi((99, 5, 101, 5), (99, 5, 100, 2)) == -2         # new better ask
    x = f.pulling_stacking({99: 10, 98: 5}, {99: 2, 98: 9}, {99: 3}, ref=100, max_bp=500)
    assert x == {"pulled": 5, "stacked": 4}


def test_sweep_and_failed_breakout():
    base = [bar(i, 100, 101, 99, 100, buy=10, sell=10) for i in range(25)]
    s = base + [bar(25, 100, 102, 99.5, 101.5, buy=40, sell=10), bar(26, 101.5, 101.6, 99.8, 100.2),
                bar(27, 100.2, 100.5, 99.6, 100.0, buy=5, sell=60)]
    assert f.sweep(s, 27, lookback=20, m=3, min_excess=0.001, vol_mult=1.5) == -1
    assert f.failed_breakout(s, 27, lookback=20, m=3, min_width_atr=0.5) == -1
    assert f.sweep(base, 24, lookback=20, m=3, min_excess=0.001, vol_mult=1.5) == 0


def test_footprint_and_profile():
    levels = [(100, 10, 5), (101, 2, 30), (102, 2, 30), (103, 2, 30), (104, 10, 10)]
    assert f.stacked_imbalances(levels, ratio=3, run=3, tick=1) == 1
    assert f.stacked_imbalances([(100, 0, 5), (101, 0, 5), (102, 0, 5), (103, 0, 5)], ratio=3, run=3, tick=1) == 1
    gap = [(100, 10, 5), (101, 2, 30), (103, 2, 30), (104, 2, 30), (105, 10, 10)]
    assert f.stacked_imbalances(gap, ratio=3, run=3, tick=1) == 0  # 101 -> 103 is not adjacent
    nodes = f.volume_nodes([(100, 5), (101, 50), (102, 20), (103, 1), (104, 8)])
    assert nodes["poc"] == 101 and 101 in nodes["hvn"] and 103 in nodes["lvn"]


def test_spoofing_like_pattern_only():
    snaps = [(0, {100: 5, 99: 5}), (1000, {100: 5, 99: 5, 98: 100}), (2000, {100: 5, 99: 5, 98: 0})]
    ev = f.spoofing_like(snaps, [], k_median=5, max_life_ms=5000)
    assert len(ev) == 1 and ev[0]["price"] == 98 and "pattern only" in ev[0]["label"]
    assert f.spoofing_like(snaps, [(1500, 98, 90)], k_median=5, max_life_ms=5000) == []  # it traded: not flagged
    assert len(f.spoofing_like(snaps, [(9000, 98, 90)], k_median=5, max_life_ms=5000)) == 1  # later trade: ignored
    gradual = [(0, {100: 5, 99: 5}), (1000, {100: 5, 99: 5, 98: 100}), (2000, {100: 5, 99: 5, 98: 50}),
               (3000, {100: 5, 99: 5, 98: 1})]
    assert len(f.spoofing_like(gradual, [], k_median=5, max_life_ms=5000)) == 1
    assert f.spoofing_like(gradual, [], k_median=5, max_life_ms=1500) == []  # outlived max_life


def test_multi_exchange_and_clock():
    assert f.multi_exchange({"binance": 1, "bybit": 1, "bitunix": 0}) == 1
    assert f.multi_exchange({"binance": 1, "bybit": 1, "bitunix": -1}) == 0
    assert f.multi_exchange({"binance": -1}) == 0
    assert f.clock_offset_ms([{"ts_ms": 0, "recv_ms": 40}, {"ts_ms": 0, "recv_ms": 60}]) == 50
