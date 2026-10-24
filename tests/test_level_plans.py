from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.dashboard.chart_model import build_chart_model
from src.dashboard.level_plans import RULE, anchors, build_level_plans, level_plan
from src.dashboard.pages.chart import _level_plan_rows
from src.dashboard.session_map import merge_same_price

T0 = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)


def _candles(count: int = 48, mid: float = 100.0, swing: float = 2.0) -> list[dict]:
    """30m candles that swing between mid-swing and mid+swing (period 12 candles)."""
    rows = []
    for i in range(count):
        centre = mid + swing * math.sin(2 * math.pi * i / 12)
        opened = T0 + timedelta(minutes=30 * i)
        rows.append({"timeframe": "30m", "open_time": opened, "close_time": opened + timedelta(minutes=30),
                     "open": centre - 0.1, "close": centre + 0.1, "high": centre + 0.3, "low": centre - 0.3, "volume": 10.0})
    return rows


def _prep(**extra) -> dict:
    levels = [
        {"label": "PWH · Vorwoche Hoch", "price": 106.0, "source": "Vorwoche"},
        {"label": "Asia Hoch", "price": 103.5, "source": "Session"},
        {"label": "Vortag VAH", "price": 101.6, "source": "Profil Vortag"},
        {"label": "Vortag VAL", "price": 98.6, "source": "Profil Vortag"},
        {"label": "PDL · Vortag Tief", "price": 98.5, "source": "Vortag"},
        {"label": "PWL · Vorwoche Tief", "price": 94.0, "source": "Vorwoche"},
    ]
    return {"levels": levels, "bias": {"bias": "LONG"}, "location": {"label": "im Vortages-Value"}, **extra}


def test_close_main_levels_merge_and_sessions_are_no_anchor() -> None:
    places = anchors(_prep())
    assert [p["labels"] for p in places] == [["PWL · Vorwoche Tief"], ["PDL · Vortag Tief", "Vortag VAL"], ["Vortag VAH"], ["PWH · Vorwoche Hoch"]]
    assert places[1]["low"] == 98.5 and places[1]["high"] == 98.6


def test_merged_same_price_level_stays_an_anchor() -> None:
    merged = merge_same_price([{"label": "PDL · Vortag Tief", "price": 98.5, "source": "Vortag"},
                               {"label": "London Tief", "price": 98.5, "source": "Session"},
                               {"label": "Asia Hoch", "price": 97.0, "source": "Session"},
                               {"label": "IB Hoch", "price": 97.0, "source": "Initial Balance"}])
    assert [m["label"] for m in merged] == ["PDL · Vortag Tief · London Tief", "Asia Hoch · IB Hoch"]
    assert merged[0]["source"] == "Vortag · Session"
    assert anchors({"levels": merged})[0]["labels"] == ["PDL · Vortag Tief · London Tief"]


def test_long_plan_at_nearest_level_below_with_stop_behind_swing() -> None:
    candles = _candles()
    now = candles[-1]["close_time"]
    result = build_level_plans(_prep(), candles, now)
    long = next(p for p in result["plans"] if p["direction"] == "LONG")
    preview = long["preview"]
    assert long["rule"] == RULE and long["id"] == "L1" and long["anchor"] == "PDL · Vortag Tief + Vortag VAL"
    assert preview["entry"] == 98.6 and long["entry_low"] < 98.5 < 98.6 < long["entry_high"]
    swing = long["invalidation_level"]["level"]
    assert swing < long["entry_low"] and preview["stop"] < swing
    assert preview["targets"][0] > long["entry_high"] and preview["reward_risk"] >= 1.5
    assert long["trend"] == "mit Trend" and long["state"] == "PROPOSED"


def test_short_against_the_bias_is_marked() -> None:
    candles = _candles()
    result = build_level_plans(_prep(), candles, candles[-1]["close_time"])
    short = next((p for p in result["plans"] if p["direction"] == "SHORT"), None)
    if short is None:
        assert any(r.startswith("SHORT") for r in result["dropped"])
    else:
        assert short["trend"] == "gegen den Trend" and short["preview"]["stop"] > short["entry_high"]


def test_plan_dropped_when_first_target_too_close() -> None:
    place = {"low": 99.0, "high": 99.0, "labels": ["Vortag VAL"]}
    plan, reason = level_plan(place, "LONG", 100.0, highs=[], lows=[98.0], targets_from=[{"price": 99.8, "label": "x"}],
                              bias=None, location=None, plan_id="L1")
    assert plan is None and "R entfernt" in reason


def test_plan_dropped_when_stop_too_far() -> None:
    place = {"low": 99.0, "high": 99.0, "labels": ["Vortag VAL"]}
    plan, reason = level_plan(place, "LONG", 100.0, highs=[], lows=[90.0], targets_from=[{"price": 120.0, "label": "x"}],
                              bias=None, location=None, plan_id="L1")
    assert plan is None and "max. 2 %" in reason


def test_stale_candles_give_no_plans() -> None:
    candles = _candles()
    result = build_level_plans(_prep(), candles, candles[-1]["close_time"] + timedelta(hours=2))
    assert result["plans"] == [] and "veraltet" in result["dropped"][0]


def test_rows_render_plan_and_empty_state() -> None:
    candles = _candles()
    html = _level_plan_rows(build_level_plans(_prep(), candles, candles[-1]["close_time"]))
    assert "L1" in html and "Vortag VAL" in html
    assert "Kein Level-Plan" in _level_plan_rows({"plans": []})


def test_chart_model_carries_level_plans_and_stale_note() -> None:
    candles = _candles(96)
    series = {"30m": [{**c, "open_time": c["open_time"].isoformat(), "close_time": c["close_time"].isoformat()} for c in candles]}
    now = candles[-1]["close_time"] + timedelta(hours=3)
    model = build_chart_model(series, "30m", now=now)
    assert model["level_plans"]["rule"] == RULE
    assert model["notes"][0].startswith("Achtung: letzte 30m-Kerze")
