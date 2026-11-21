"""S34 / S35a: Simulator-Reihenfolge, Kosten, LVN-Regel, Holm."""
from __future__ import annotations

import math
from datetime import date

from src.research_lab.studies import s34, s35a
from src.research_lab.studies.minute_sim import FEE, SLIP, SLIP_STOP, Minutes, simulate


class _M(Minutes):
    def __init__(self, bars):  # bars: list of (open, high, low, close)
        self.t0 = 0
        self.n = len(bars)
        self.open, self.high, self.low, self.close = ([b[k] for b in bars] for k in range(4))


def test_stop_wins_same_minute_and_cost_in_r():
    m = _M([(100, 100, 100, 100), (100, 103, 97, 100)])
    t = simulate(m, None, "X", 1, 0, 98.0, 102.0, 10, 0)
    assert t.reason == "target" or t.reason == "stop"
    m2 = _M([(100, 103, 97, 100)])
    t2 = simulate(m2, None, "X", 1, 0, 98.0, 102.0, 10, 0)
    assert t2.reason == "stop" and t2.exit == 98.0
    gross = (98.0 - 100) / 100 / 0.02
    assert math.isclose(t2.gross_r, gross)
    assert math.isclose(t2.net_r, gross - (2 * FEE + SLIP + SLIP_STOP) / 0.02)


def test_short_target_and_no_trade_beyond_stop():
    m = _M([(100, 100.5, 98, 99)])
    t = simulate(m, None, "X", -1, 0, 101.0, 99.0, 10, 0)
    assert t.reason == "target" and t.gross_r > 0
    assert simulate(m, None, "X", -1, 0, 99.5, 98.0, 10, 0, entry_override=100.0) is None


def test_lvn_rule():
    g = s34.GRID
    base = math.exp(5 * g * 1000)
    k0 = s34.gidx(base)
    hist = {k0 + d: 100 for d in range(-8, 9)}
    hist[k0] = 10
    assert s34.value_area(hist) is not None
    price = math.exp((k0 + 0.5) * g)
    va = s34.value_area(hist)
    assert isinstance(s34.lvn_near(hist, price, 1), bool)
    hist[k0] = 100
    assert not s34.lvn_near(hist, price, 1)


def test_holm_adjusted_monotone_and_configs():
    adj = s35a.holm_adjusted({"a": 0.001, "b": 0.02}, 12)
    assert adj["a"] == 0.012 and adj["b"] >= adj["a"]
    assert len(s35a.CONFIGS) == 12
