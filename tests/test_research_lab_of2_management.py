"""OF2 trade management variants (plan package P5): paired replay of finished trades with other exits."""
from __future__ import annotations

import pytest

from src.research_lab.of2 import management as mg
from src.research_lab.of2.config import MINUTE_MS, Config
from src.research_lab.orderflow_ml.bars import E8, MinuteBar

CFG = Config(fee=0.0, slippage=0.0, stop_slippage=0.0, time_stop_bars=1000)   # costs off: R arithmetic only


def bar(i: int, h: float, l: float, c: float) -> MinuteBar:
    t = i * MINUTE_MS
    return MinuteBar(t, 10, 5, 5 * E8, 5 * E8, E8, 0, 500 * E8, 500 * E8, int(c * E8), int(c * E8), int(h * E8), int(l * E8), t + 1000)


TRADE = {"direction": 1, "entry": 100.0, "stop": 99.0, "target": 102.0, "fill_ms": 0, "tf": 15}


def path(*hlc: tuple[float, float, float]) -> list[MinuteBar]:
    return [bar(i, *x) for i, x in enumerate(hlc)]


def test_fest_target_and_stop():
    assert mg.replay(TRADE, path((101, 99.5, 100.5), (102.1, 100, 102)), "FEST", CFG)["netto_r"] == pytest.approx(2.0)
    r = mg.replay(TRADE, path((100.5, 98.9, 99)), "FEST", CFG)
    assert r["netto_r"] == pytest.approx(-1.0) and r["grund"] == "STOP"


def test_stop_before_target_in_the_same_minute():
    assert mg.replay(TRADE, path((102.5, 98.5, 100)), "FEST", CFG)["netto_r"] == pytest.approx(-1.0)


def test_teil_half_at_one_r_rest_break_even():
    r = mg.replay(TRADE, path((101.2, 99.8, 101), (101, 99.9, 99.95)), "TEIL", CFG)
    assert r["netto_r"] == pytest.approx(0.5)          # +0.5 from the half, 0 from the rest at break-even
    r = mg.replay(TRADE, path((101.2, 99.8, 101), (102.2, 101, 102)), "TEIL", CFG)
    assert r["netto_r"] == pytest.approx(1.5)          # 0.5 + 0.5 x 2


def test_nachziehen_runs_past_the_target_and_trails():
    r = mg.replay(TRADE, path((101, 99.5, 101), (105, 101, 105), (105, 103.9, 104)), "NACHZIEHEN", CFG)
    assert r["netto_r"] == pytest.approx(4.0)          # best 105, trail 1 R -> 104


def test_aufbau_adds_a_third_of_the_floating_profit():
    r = mg.replay(TRADE, path((102.5, 99.5, 102.5), (106, 102.5, 106), (106, 104.9, 105)), "AUFBAU", CFG)
    # first: 100 -> 105 = 5 R; second at 102.5, stop 101 (+1 R lock), risk = 1/3 x 2.5 R -> size 0.5556, 2.5 x 0.5556
    assert r["beine"] == 2
    assert r["netto_r"] == pytest.approx(5 + (105 - 102.5) * (2.5 / 3 / 1.5), rel=1e-6)


def test_aufbau_worst_case_stays_positive_after_the_add():
    r = mg.replay(TRADE, path((102.5, 99.5, 102.5), (102.5, 100.5, 100.6)), "AUFBAU", CFG)
    # the 1-R trail (102.5 - 1 = 101.5) is tighter than the lock (101): first +1.5 R, second -1 x size 0.5556
    assert r["netto_r"] == pytest.approx(1.5 - 2.5 / 3 / 1.5, rel=1e-6) and r["netto_r"] > 0


def test_short_mirror_and_time_limits():
    short = {**TRADE, "direction": -1, "stop": 101.0, "target": 98.0}
    assert mg.replay(short, path((100.5, 97.9, 98)), "FEST", CFG)["netto_r"] == pytest.approx(2.0)
    cfg = Config(fee=0.0, slippage=0.0, stop_slippage=0.0, time_stop_bars=1)
    r = mg.replay({**TRADE, "tf": 1}, path((100.2, 99.9, 100.1), (100.2, 99.9, 100.1)), "NACHZIEHEN", cfg)
    assert r["grund"] == "TIME_STOP"


def test_costs_are_charged_per_leg():
    r0 = mg.replay(TRADE, path((102.1, 100, 102)), "FEST", CFG)["netto_r"]
    r1 = mg.replay(TRADE, path((102.1, 100, 102)), "FEST", Config(time_stop_bars=1000))["netto_r"]
    assert r1 < r0


def test_unknown_variant():
    with pytest.raises(ValueError):
        mg.replay(TRADE, [], "X", CFG)
