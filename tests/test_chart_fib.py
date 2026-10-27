"""Fibonacci zones of the newest swing leg on the TIM chart (0.886/0.941 from the GoatHub lesson)."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.dashboard.chart_live import FIB_RATIOS, GROUP_NAMES, GROUP_STYLE, DEFAULT_GROUPS, fib_drawings, place_drawings
from src.dashboard.public_en import GROUPS_EN, english_text
from tests.test_chart_live import _path


def _by_ratio(drawings: list[dict]) -> dict[float, float]:
    return {d["ratio"]: d["price"] for d in drawings}


def test_ratios_include_community_zones() -> None:
    assert FIB_RATIOS == (0.382, 0.5, 0.618, 0.786, 0.886, 0.941)
    assert "fib" in GROUP_STYLE and "fib" in GROUP_NAMES and "fib" in GROUPS_EN
    assert "fib" not in DEFAULT_GROUPS  # opt-in, keeps the chart readable


def test_leg_up_long_fib_from_wick_low_to_wick_high() -> None:
    # down to a swing low, then up: the newest swing is the low, the leg ends at the highest wick after it
    candles = _path([200, 180, 160, 140, 120, 100, 120, 140, 160, 180, 200, 220, 240])
    drawings = fib_drawings(candles, "1h", 2)
    assert len(drawings) == len(FIB_RATIOS)
    low = min(c["low"] for c in candles)
    high = max(c["high"] for c in candles[5:])
    prices = _by_ratio(drawings)
    for ratio, price in prices.items():
        assert price == pytest.approx(high - (high - low) * ratio)
    assert prices[0.941] < prices[0.886] < prices[0.618]  # deep zones close to the low
    assert all(d["direction"] == "UP" and d["label"].startswith("1h Fib ") for d in drawings)
    assert drawings[0]["start"] == candles[5]["open_time"].isoformat()


def test_leg_down_short_fib_from_wick_high_to_wick_low() -> None:
    candles = _path([100, 120, 140, 160, 180, 200, 180, 160, 140, 120, 100, 80])
    drawings = fib_drawings(candles, "4h", 2)
    high = max(c["high"] for c in candles)
    low = min(c["low"] for c in candles[5:])
    prices = _by_ratio(drawings)
    for ratio, price in prices.items():
        assert price == pytest.approx(low + (high - low) * ratio)
    assert prices[0.941] > prices[0.886] > prices[0.618]
    assert all(d["direction"] == "DOWN" for d in drawings)


def test_open_candle_never_moves_the_anchor() -> None:
    candles = _path([200, 180, 160, 140, 120, 100, 120, 140, 160, 180, 200])
    before = fib_drawings(candles, "1h", 2)
    candles.append({**candles[-1], "open_time": candles[-1]["open_time"] + timedelta(hours=1), "high": 900, "closed": False})
    assert fib_drawings(candles, "1h", 2) == before


def test_no_swing_no_fib() -> None:
    assert fib_drawings(_path([100, 110, 120, 130, 140]), "1h", 2) == []


def test_fib_lines_run_to_newest_candle_and_translate() -> None:
    candles = _path([200, 180, 160, 140, 120, 100, 120, 140, 160, 180, 200])
    drawings = fib_drawings(candles, "1h", 2)
    times = [int(c["open_time"].timestamp()) for c in candles]
    placed = place_drawings(drawings, times)
    assert placed and all(d["t2"] == times[-1] and d["p1"] == d["p2"] and not d["finished"] for d in placed)
    assert english_text(drawings[0]["note"]) == "Long fib, swing low → high (wicks), zone, not a signal"


def test_live_chart_draws_structure_and_trend_only_once() -> None:
    from tests.test_chart_live import _model

    model = _model()
    keys = [(d["group"], d["label"], d["t1"], d["t2"], d["p1"], d["p2"]) for d in model["drawings"]
            if d["group"] in ("structure", "trend", "fib")]
    assert keys and len(keys) == len(set(keys))
