"""OF2 building blocks from the Fabervaale video (16.11.2026): candle profile, change of flow, delta peak, void
ratio (P1/P2) and the multi-day balance filter (P4). The filter is off by default and leaves OF2 1.0 unchanged."""
from __future__ import annotations

import dataclasses

import pytest

from src.research_lab.of2 import engine, flow, levels, models
from src.research_lab.of2.config import MINUTE_MS, Config
from src.research_lab.of2.footprint import Footprint

CFG = Config()


def fp(bins: list[tuple[int, int, int]], step: float = 1.0) -> Footprint:
    return Footprint(0, 15, step, tuple(bins))


def day(val: float, vah: float, close: float, poc: float | None = None) -> levels.DaySummary:
    return levels.DaySummary(0, vah + 5, val - 5, close, poc if poc is not None else (val + vah) / 2, val, vah)


def signal(model: str, direction: int) -> models.Signal:
    return models.Signal(model, direction, 0, "MARKET", None, 30 * MINUTE_MS, 90.0, 120.0, "L", 100.0, True, "ASIA")


# -- P1 candle profile and change of flow -------------------------------------------------------------------------
def test_candle_profile_poc_and_value_area():
    p = flow.candle_profile(fp([(100, 1, 1), (101, 10, 10), (102, 1, 1)]))
    assert p is not None
    assert p.poc == pytest.approx(101.5)
    assert p.val <= p.poc <= p.vah


def test_candle_profile_empty_is_none():
    assert flow.candle_profile(fp([])) is None
    assert flow.candle_profile([]) is None


def test_merged_profile_over_two_candles():
    a = fp([(100, 5, 5), (101, 1, 1)])
    b = fp([(101, 1, 1), (102, 20, 20)])
    assert flow.candle_profile([a, b]).poc == pytest.approx(102.5)


def test_merge_refuses_different_bin_widths():
    with pytest.raises(ValueError):
        flow.merge_footprints([fp([(1, 1, 1)], 1.0), fp([(1, 1, 1)], 2.0)])


@pytest.mark.parametrize("poc, close, expected", [
    (106.0, 111.0, "WECHSEL_HOCH"),   # POC higher, close above previous VAH: shift to buyers
    (106.0, 108.0, "KAEUFER"),        # POC higher, no acceptance above
    (104.0, 99.0, "WECHSEL_TIEF"),
    (104.0, 102.0, "VERKAEUFER"),     # POC lower: sellers lead
    (105.0, 120.0, "NEUTRAL"),        # POC did not move
])
def test_flow_state(poc, close, expected):
    prev = flow.CandleProfile(105.0, 100.0, 110.0)
    last = flow.CandleProfile(poc, poc - 3, poc + 3)
    assert flow.flow_state(prev, last, close) == expected


def test_flow_state_without_profile_is_neutral():
    assert flow.flow_state(None, flow.CandleProfile(1, 0, 2), 5) == "NEUTRAL"


# -- P2 delta peak and void ratio ------------------------------------------------------------------------------
def test_delta_peak_long_and_short():
    f = fp([(100, 3, 1), (101, 9, 1), (102, 1, 6)])
    assert flow.delta_peak([f], 1) == pytest.approx(101.5)    # +8 net buy
    assert flow.delta_peak([f], -1) == pytest.approx(102.5)   # +5 net sell


def test_delta_peak_tie_takes_the_start_of_the_move():
    f = fp([(100, 5, 1), (101, 1, 1), (102, 5, 1)])
    assert flow.delta_peak([f], 1) == pytest.approx(100.5)
    g = fp([(100, 1, 5), (101, 1, 1), (102, 1, 5)])
    assert flow.delta_peak([g], -1) == pytest.approx(102.5)


def test_delta_peak_none_without_net_aggression():
    assert flow.delta_peak([fp([(100, 1, 5)])], 1) is None
    assert flow.delta_peak([fp([])], 1) is None


def test_delta_peak_over_an_impulse_of_several_candles():
    a = fp([(100, 4, 1), (101, 2, 1)])
    b = fp([(101, 6, 1), (102, 2, 1)])
    assert flow.delta_peak([a, b], 1) == pytest.approx(101.5)   # 1 + 5 net at 101


def test_void_ratio_thin_middle():
    f = fp([(100, 10, 10), (101, 0, 0), (102, 1, 0), (103, 10, 10)])
    r = flow.void_ratio([f], 101.0, 103.0)   # centres 101.5, 102.5
    assert r is not None and r < 0.2
    assert flow.void_ratio([f], 100.0, 104.0) == pytest.approx(1.0)


def test_void_ratio_none_cases():
    f = fp([(100, 1, 1)])
    assert flow.void_ratio([f], 200.0, 300.0) is None
    assert flow.void_ratio([f], 5.0, 1.0) is None
    assert flow.void_ratio([fp([])], 0.0, 1.0) is None


# -- P4 balance state and acceptance bias ---------------------------------------------------------------------
def test_balance_state_cases():
    a, b, c = day(100, 110, 105), day(102, 112, 107), day(101, 111, 106)
    assert levels.balance_state([a, b, c], 3, 0.5) == "BALANCE"
    assert levels.balance_state([a, b, day(113, 120, 118)], 3, 0.5) == "IMBALANCE_HOCH"
    assert levels.balance_state([a, b, day(90, 99, 95)], 3, 0.5) == "IMBALANCE_TIEF"
    assert levels.balance_state([a, day(108, 118, 115), day(109, 119, 116)], 3, 0.5) == "TRANSITION"
    assert levels.balance_state([a, b], 3, 0.5) == "UNBEKANNT"


def test_acceptance_bias():
    a = day(100, 110, 105)
    assert levels.acceptance_bias([a, day(102, 112, 113)], 2) == "HOEHER"
    assert levels.acceptance_bias([a, day(102, 112, 99)], 2) == "TIEFER"
    assert levels.acceptance_bias([a, day(102, 112, 106)], 2) == "INNEN"
    assert levels.acceptance_bias([a], 2) == "UNBEKANNT"


@pytest.mark.parametrize("model, direction, balance, bias, blocked", [
    ("M1", 1, "IMBALANCE_TIEF", "INNEN", "gegen_imbalance"),
    ("M7", -1, "BALANCE", "HOEHER", "gegen_akzeptanz"),
    ("M4", 1, "BALANCE", "INNEN", None),
    ("M2", 1, "IMBALANCE_TIEF", "INNEN", "gegen_imbalance"),
    ("M2", 1, "BALANCE", "TIEFER", None),           # continuation is not blocked by the bias
    ("M5", -1, "IMBALANCE_TIEF", "TIEFER", None),   # with the imbalance
    ("S1", 1, "IMBALANCE_TIEF", "TIEFER", None),    # swing models pass
])
def test_balance_block(model, direction, balance, bias, blocked):
    assert engine._balance_block(signal(model, direction), balance, bias) == blocked


def test_balance_filter_off_keeps_the_of2_digest():
    assert "balance_filter" not in CFG.as_dict()
    on = dataclasses.replace(CFG, balance_filter=True)
    assert on.as_dict()["balance_filter"] is True and on.digest() != CFG.digest()


def test_engine_rejects_a_fade_against_the_imbalance():
    cfg = dataclasses.replace(CFG, balance_filter=True)
    e = engine.Engine(cfg)
    e.session = levels.SessionState("ASIA", 0)
    e.balance, e.bias = "IMBALANCE_TIEF", "INNEN"
    e._consider(signal("M4", 1), 0, 0)
    assert e.stats.verworfen.get("M4_gegen_imbalance") == 1
    assert not e.tracker.pending


# -- P3 M8 transition candle + retest ------------------------------------------------------------------------------
from src.research_lab.of2.candles import Candle  # noqa: E402

M8CFG = dataclasses.replace(CFG, m8=True)


def c15(i: int, o: float, h: float, l: float, c: float, volume: int = 10, delta: int = 0) -> Candle:
    return Candle(i * 15 * MINUTE_MS, 15, 10, o, h, l, c, volume, delta)


def _balance(n: int = 16) -> tuple[list[Candle], list[Footprint]]:
    candles = [c15(i, 100.0, 101.0, 99.0, 100.0 + (0.5 if i % 2 else -0.5)) for i in range(n)]
    fps = [Footprint(c.start, 15, 0.1, tuple((b, 5, 5) for b in range(990, 1010))) for c in candles]
    return candles, fps


def _lv() -> levels.Levels:
    return levels.Levels(levels.DaySummary(0, 120.0, 80.0, 100.0, 100.0, 95.0, 110.0))


def test_m8_long_breakout_arms_limit_at_the_delta_peak():
    candles, fps = _balance()
    candles.append(c15(16, 100.5, 103.0, 100.4, 102.8, volume=100, delta=60))
    fps.append(Footprint(candles[-1].start, 15, 0.1, ((1005, 2, 2), (1015, 40, 2), (1025, 30, 30))))
    s = models.transition(candles, fps, _lv(), M8CFG)
    assert s is not None and s.model == "M8" and s.direction == 1 and s.kind == models.LIMIT
    assert s.trigger == pytest.approx(101.55)            # delta peak bin 1015 above the edge 101
    assert s.stop < 101.0 and s.stop > 99.0               # back inside the range
    assert s.cancel_beyond == 101.0
    assert s.target == 110.0                              # yesterday's VAH, first level with R:R >= 1.5
    assert s.confirmed                                    # POC 102.55 above the balance VAH, nothing traded up to 110


def test_m8_needs_a_close_beyond_the_range_and_relative_volume():
    candles, fps = _balance()
    candles.append(c15(16, 100.0, 101.0, 99.5, 100.8, volume=100))
    fps.append(fps[-1])
    assert models.transition(candles, fps, _lv(), M8CFG) is None      # no close beyond
    candles[-1] = c15(16, 100.5, 103.0, 100.4, 102.8, volume=10)
    assert models.transition(candles, fps, _lv(), M8CFG) is None      # no volume


def test_m8_rejects_a_wide_range_and_short_history():
    candles, fps = _balance()
    candles[3] = c15(3, 100.0, 110.0, 99.0, 100.0)                   # range 11 % > 3 %
    candles.append(c15(16, 100.5, 112.0, 100.4, 111.0, volume=100))
    fps.append(fps[-1])
    assert models.transition(candles, fps, _lv(), M8CFG) is None
    short_c, short_f = _balance(10)
    assert models.transition(short_c, short_f, _lv(), M8CFG) is None


def test_m8_off_keeps_the_of2_digest():
    assert not any(k.startswith("m8") for k in CFG.as_dict())
    assert M8CFG.as_dict()["m8"] is True and M8CFG.digest() != CFG.digest()
