"""Fibonacci retracement of the newest swing leg on the TIM chart, drawn like TradingView's Fib tool."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.dashboard.chart_live import (DEFAULT_GROUPS, FIB_RATIOS, GROUP_NAMES, GROUP_STYLE, average_range, fib_retracement,
                                      zigzag_pivots)
from src.dashboard.public_en import GROUPS_EN, english_chart_model, english_text
from tests.test_chart_live import _path


def _by_ratio(leg: dict) -> dict[float, float]:
    return {level["ratio"]: level["price"] for level in leg["levels"]}


def _epoch(candle: dict) -> int:
    return int(candle["open_time"].timestamp())


def test_levels_like_tradingview_plus_community_zones() -> None:
    assert FIB_RATIOS == (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 0.886, 0.941, 1.0, 1.618)
    assert "fib" in GROUP_STYLE and "fib" in GROUP_NAMES and "fib" in GROUPS_EN
    assert "fib" not in DEFAULT_GROUPS  # opt-in, keeps the chart readable


def test_pullback_keeps_the_big_leg_down() -> None:
    # Uzi's 30m picture: a big drop, a bounce of about half of it, price drifting lower again.
    # The fib belongs to the drop (high -> low), not to the small bounce.
    candles = _path([200, 300, 400, 500, 600, 700, 600, 500, 400, 300, 200, 100, 150, 200, 250, 300, 260, 220])
    leg = fib_retracement(candles, "30m", mult=2)
    assert leg is not None and leg["direction"] == "DOWN" and leg["finished"]
    high = max(c["high"] for c in candles)
    low = min(c["low"] for c in candles)
    assert leg["start_price"] == high and leg["end_price"] == low
    assert leg["start"] == _epoch(candles[5]) and leg["end"] == _epoch(candles[11])
    prices = _by_ratio(leg)
    assert prices[0.0] == pytest.approx(low) and prices[1.0] == pytest.approx(high)  # 0 at the end, 1 at the start
    for ratio, price in prices.items():
        assert price == pytest.approx(low + (high - low) * ratio)
    assert prices[1.618] > high  # extension beyond the start
    assert english_text(leg["note"]) == "Short fib, swing high → low (wicks), zone, not a signal"


def test_confirmed_lower_high_keeps_the_big_leg_down() -> None:
    # drop, bounce, and a second drop deep enough to confirm the bounce high as a swing:
    # everything after the drop stays inside it, so the fib stays on the drop
    candles = _path([200, 300, 400, 500, 600, 700, 600, 500, 400, 300, 200, 100, 200, 300, 400, 300, 200, 150])
    pivots, _ = zigzag_pivots([c for c in candles], 2 * average_range(candles))
    assert [p["kind"] for p in pivots][-2:] == ["LOW", "HIGH"]  # the bounce high is a confirmed swing
    leg = fib_retracement(candles, "30m", mult=2)
    assert leg["direction"] == "DOWN" and leg["start_price"] == max(c["high"] for c in candles)
    assert leg["end_price"] == min(c["low"] for c in candles)


def test_break_below_the_leg_starts_a_new_one() -> None:
    # after the bounce price falls below the old low: the drop no longer holds, the new move is the leg
    candles = _path([700, 600, 500, 400, 300, 200, 300, 400, 500, 400, 300, 200, 100, 0, -100])
    leg = fib_retracement(candles, "30m", mult=2)
    assert leg["direction"] == "DOWN" and not leg["finished"]
    assert leg["start_price"] == max(c["high"] for c in candles[5:])
    assert leg["end_price"] == min(c["low"] for c in candles)


def test_running_move_bigger_than_last_leg_becomes_the_leg() -> None:
    # down 200 -> 100, then up to 400: the move up is bigger, the fib runs from the low to the newest high
    candles = _path([200, 170, 140, 100, 150, 200, 250, 300, 350, 400, 380])
    leg = fib_retracement(candles, "1h", mult=2)
    assert leg is not None and leg["direction"] == "UP" and not leg["finished"]
    low = min(c["low"] for c in candles)
    high = max(c["high"] for c in candles)
    assert leg["start_price"] == low and leg["end_price"] == high
    prices = _by_ratio(leg)
    for ratio, price in prices.items():
        assert price == pytest.approx(high - (high - low) * ratio)
    assert prices[0.941] < prices[0.886] < prices[0.618] < prices[0.0]


def test_small_wiggles_do_not_start_a_leg() -> None:
    # a clear rise with tiny pullbacks: one leg from the first low to the top, not the last wiggle
    closes = []
    for step in range(12):
        closes += [100 + step * 30, 100 + step * 30 + 25, 100 + step * 30 + 15]
    candles = _path(closes)
    leg = fib_retracement(candles, "15m")
    assert leg is not None and leg["direction"] == "UP"
    assert leg["start_price"] == min(c["low"] for c in candles)
    assert leg["end_price"] == max(c["high"] for c in candles)


def test_open_candle_never_moves_the_anchor() -> None:
    candles = _path([200, 300, 400, 500, 600, 700, 600, 500, 400, 300, 200, 100, 150, 200, 250])
    before = fib_retracement(candles, "1h", mult=2)
    candles.append({**candles[-1], "open_time": candles[-1]["open_time"] + timedelta(hours=1), "high": 9000, "closed": False})
    assert fib_retracement(candles, "1h", mult=2) == before


def test_no_swing_no_fib() -> None:
    assert fib_retracement(_path([100, 101, 102]), "1h") is None
    assert fib_retracement([], "1h") is None


def test_zigzag_alternates_and_needs_the_threshold() -> None:
    candles = _path([100, 200, 300, 200, 100, 200, 300, 250])
    pivots, running = zigzag_pivots(candles, 150)
    kinds = [p["kind"] for p in pivots]
    assert kinds == ["LOW", "HIGH", "LOW"]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    assert running is not None and running["kind"] == "HIGH" and running["price"] == max(c["high"] for c in candles[4:])
    assert average_range(candles) > 0


def test_live_model_carries_fib_and_no_fib_lines() -> None:
    from tests.test_chart_live import _model

    model = _model()
    assert "fib" in model
    assert not [d for d in model["drawings"] if d["group"] == "fib"]  # no labels on the price axis any more
    if model["fib"]:
        assert english_chart_model(model)["fib"]["note"].endswith("not a signal")


def test_live_chart_draws_structure_and_trend_only_once() -> None:
    from tests.test_chart_live import _model

    model = _model()
    keys = [(d["group"], d["label"], d["t1"], d["t2"], d["p1"], d["p2"]) for d in model["drawings"]
            if d["group"] in ("structure", "trend")]
    assert keys and len(keys) == len(set(keys))
