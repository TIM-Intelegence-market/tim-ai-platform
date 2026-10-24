from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from urllib.request import urlopen

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.pages.prep import _prep_page
from src.dashboard.session_map import (
    aggregate,
    build_session_map,
    htf_bias,
    initial_balance,
    location,
    naked_pocs,
    poor_extremes,
    sessions,
    structure,
    summary_line,
)

NOW = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)


def _c(opened: datetime, seconds: int, o: float, h: float, l: float, c: float, v: float = 10.0, tf: str = "1h") -> dict:
    return {"symbol": "BTCUSDT", "timeframe": tf, "open_time": opened, "close_time": opened + timedelta(seconds=seconds),
            "open": o, "high": h, "low": l, "close": c, "volume": v}


def _wave(count: int, seconds: int, end: datetime, tf: str, trend: float, period: float = 30.0) -> list[dict]:
    """Zigzag around a trend: clear swing highs and lows every ``period`` candles."""
    start = end - timedelta(seconds=seconds * count)
    out, price = [], 80000.0
    for i in range(count):
        close = 80000.0 + trend * i + 400 * math.sin(2 * math.pi * i / period)
        up = close >= price  # the up candle owns the peak, so swing highs/lows have no ties
        high, low = max(price, close) + 5 + up, min(price, close) - 5 - (not up)
        out.append(_c(start + timedelta(seconds=seconds * i), seconds, price, high, low, close, 10 + i % 7, tf))
        price = close
    return out


def _iso(candles: list[dict]) -> list[dict]:
    return [{**c, "open_time": c["open_time"].isoformat(), "close_time": c["close_time"].isoformat()} for c in candles]


def _series(trend: float = 4.0) -> dict[str, list[dict]]:
    quarter = _wave(500, 900, NOW, "15m", trend / 4, period=40)
    hours = _wave(500, 3600, NOW, "1h", trend, period=36)
    return {"15m": _iso(quarter), "1h": _iso(hours)}


def test_aggregate_builds_four_hour_buckets_and_flags_the_running_one() -> None:
    start = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
    hours = [_c(start + timedelta(hours=i), 3600, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(10)]
    buckets = aggregate(hours, "4h", 4 * 3600, start + timedelta(hours=10))
    assert [b["hours"] for b in buckets] == [4, 4, 2]
    assert [b["complete"] for b in buckets] == [True, True, False]
    assert buckets[0]["open"] == 100 and buckets[0]["close"] == 103.5 and buckets[0]["high"] == 104 and buckets[0]["low"] == 99


def test_aggregate_weeks_start_on_monday_utc() -> None:
    sunday = datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)
    hours = [_c(sunday, 3600, 1, 2, 0.5, 1.5), _c(sunday + timedelta(hours=1), 3600, 1, 2, 0.5, 1.5)]
    weeks = aggregate(hours, "1W", 7 * 86400, sunday + timedelta(days=3))
    assert [w["open_time"].date() for w in weeks] == [date(2026, 10, 19), date(2026, 10, 26)]


def test_structure_reads_up_down_and_unknown() -> None:
    up = _wave(200, 3600, NOW, "1h", trend=10)
    down = _wave(200, 3600, NOW, "1h", trend=-10)
    assert structure(up)["state"] == "UP"
    assert structure(down)["state"] == "DOWN"
    assert structure(up[:5])["state"] == "UNKNOWN"
    # The running (incomplete) candle never counts.
    assert structure([{**c, "complete": False} for c in up])["candles"] == 0


def test_htf_bias_lets_daily_and_four_hour_decide() -> None:
    assert htf_bias({"1D": "UP", "4h": "UP", "1W": "UP"}) == {"bias": "LONG", "weekly_confirms": True, "text": "Long-Bias: 1D und 4h aufwärts, Woche bestätigt"}
    assert htf_bias({"1D": "DOWN", "4h": "DOWN", "1W": "UNKNOWN"})["bias"] == "SHORT"
    assert htf_bias({"1D": "UP", "4h": "DOWN"})["bias"] == "NEUTRAL"
    assert htf_bias({"1D": "UP", "4h": "RANGE"})["bias"] == "NEUTRAL"
    assert htf_bias({"1D": "UNKNOWN", "4h": "UP"})["bias"] == "UNKNOWN"
    # The week alone never makes a bias.
    assert htf_bias({"1D": "RANGE", "4h": "RANGE", "1W": "UP"})["bias"] == "NEUTRAL"


def _blocks(*closes: float) -> list[dict]:
    return [{"close": c, "complete": True} for c in closes]


def test_location_needs_two_thirty_minute_closes_for_acceptance() -> None:
    value = {"vah": 110.0, "val": 90.0}
    assert location(115, value, _blocks(105, 112, 113))["state"] == "ABOVE_ACCEPTED"
    assert location(115, value, _blocks(112, 105))["state"] == "ABOVE_NOT_ACCEPTED"
    assert location(115, value, _blocks(112))["state"] == "ABOVE_NOT_ACCEPTED"
    assert location(85, value, _blocks(89, 88))["state"] == "BELOW_ACCEPTED"
    assert location(85, value, _blocks(95, 88))["state"] == "BELOW_NOT_ACCEPTED"
    assert location(100, value, _blocks(100, 100))["state"] == "IN_VALUE"
    assert location(100, None, [])["state"] == "UNKNOWN"
    # An incomplete block is ignored.
    assert location(115, value, [{"close": 112, "complete": True}, {"close": 113, "complete": False}])["state"] == "ABOVE_NOT_ACCEPTED"


def _day(highs_lows: list[tuple[float, float]]) -> dict:
    start = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)
    candles = [_c(start + timedelta(minutes=15 * i), 900, (h + l) / 2, h, l, (h + l) / 2, tf="15m") for i, (h, l) in enumerate(highs_lows)]
    return {"candles": candles, "high": max(h for h, _ in highs_lows), "low": min(l for _, l in highs_lows), "profile": {"step": 1.0}}


def test_poor_high_needs_two_thirty_minute_periods_at_the_extreme() -> None:
    # Two 30m blocks (candles 0-1 and 2-3) touch 120; the low at 80 is hit once.
    day = _day([(120, 100), (110, 100), (119.5, 100), (110, 95), (105, 80), (105, 95)])
    result = poor_extremes(day)
    assert result["poor_high"] is True and result["high_periods"] == 2
    assert result["poor_low"] is False and result["low_periods"] == 1


def test_naked_poc_disappears_once_a_later_candle_trades_through_it() -> None:
    day = {"period": date(2026, 10, 22), "complete": True, "profile": {"poc": 100.0}}
    open_day = {"period": date(2026, 10, 23), "complete": False, "profile": {"poc": 50.0}}
    later_miss = [_c(datetime(2026, 10, 23, 1, tzinfo=timezone.utc), 900, 110, 112, 105, 111)]
    later_hit = later_miss + [_c(datetime(2026, 10, 23, 2, tzinfo=timezone.utc), 900, 105, 106, 99, 101)]
    same_day = [_c(datetime(2026, 10, 22, 12, tzinfo=timezone.utc), 900, 100, 101, 99, 100)]
    assert naked_pocs([day, open_day], later_miss + same_day) == [{"day": "2026-10-22", "price": 100.0}]
    assert naked_pocs([day], later_hit) == []


def test_sessions_follow_local_exchange_time_across_daylight_saving() -> None:
    def quarter_hours(day: datetime) -> list[dict]:
        return [_c(day + timedelta(minutes=15 * i), 900, 100, 101 + i % 3, 99, 100, tf="15m") for i in range(96)]

    summer = datetime(2026, 10, 23, tzinfo=timezone.utc)
    found = {s["name"]: s for s in sessions(quarter_hours(summer), summer + timedelta(hours=23))}
    assert found["London"]["start"] == "2026-10-23T07:00:00+00:00"
    assert found["New York"]["start"] == "2026-10-23T13:30:00+00:00"
    assert found["Asia"]["start"] == "2026-10-23T00:00:00+00:00"
    assert not any(s["running"] for s in found.values())
    # After both clock changes (EU 25.10., US 01.11.) the UTC times move one hour later.
    winter = datetime(2026, 11, 3, tzinfo=timezone.utc)
    found = {s["name"]: s for s in sessions(quarter_hours(winter), winter + timedelta(hours=15))}
    assert found["London"]["start"] == "2026-11-03T08:00:00+00:00" and found["London"]["running"]
    assert found["New York"]["start"] == "2026-11-03T14:30:00+00:00" and found["New York"]["running"]
    assert found["Asia"]["start"] == "2026-11-03T00:00:00+00:00" and not found["Asia"]["running"]


def test_sessions_skip_windows_that_have_not_started() -> None:
    day = datetime(2026, 10, 23, tzinfo=timezone.utc)
    candles = [_c(day + timedelta(minutes=15 * i), 900, 100, 101, 99, 100, tf="15m") for i in range(40)]
    names = [s["name"] for s in sessions(candles, day + timedelta(hours=10))]
    assert names == ["Asia", "London"]


def test_initial_balance_width_against_the_median_day() -> None:
    day = datetime(2026, 10, 24, tzinfo=timezone.utc)
    narrow = [_c(day + timedelta(minutes=15 * i), 900, 100, 101, 99, 100, tf="15m") for i in range(8)]
    ib = initial_balance(narrow, [20, 20, 20], day + timedelta(hours=2))
    assert ib["high"] == 101 and ib["low"] == 99 and ib["complete"] and ib["width"].startswith("eng")
    wide = initial_balance(narrow, [3, 3, 3], day + timedelta(minutes=45))
    assert wide["width"].startswith("breit") and not wide["complete"]
    assert initial_balance(narrow, [], day + timedelta(hours=2))["width"] == "unbekannt"
    assert initial_balance([], [10], day) is None


def test_build_session_map_from_runtime_series() -> None:
    model = build_session_map(_series(trend=6.0), NOW)
    assert model["schema"] == "tim_session_map/1" and model["read_only"] is True
    assert model["htf"]["4h"]["state"] == "UP" and model["bias"]["bias"] in {"LONG", "NEUTRAL", "UNKNOWN"}
    assert model["previous_day"]["day"] == "2026-10-23"
    pd = model["previous_day"]
    assert pd["val"] <= pd["poc"] <= pd["vah"] and pd["low"] <= pd["val"] and pd["vah"] <= pd["high"]
    assert model["location"]["state"] in {"ABOVE_ACCEPTED", "ABOVE_NOT_ACCEPTED", "IN_VALUE", "BELOW_NOT_ACCEPTED", "BELOW_ACCEPTED"}
    prices = [level["price"] for level in model["levels"]]
    assert prices == sorted(prices, reverse=True)
    assert {level["side"] for level in model["levels"]} <= {"über", "unter", "am Kurs"}
    assert any(level["label"].startswith("Vortag VAH") for level in model["levels"])
    assert model["initial_balance"] is not None
    json.dumps(model, default=str)
    line = summary_line(model)
    assert model["bias"]["text"] in line and model["location"]["label"] in line


def test_build_session_map_without_candles_says_so() -> None:
    model = build_session_map({}, NOW)
    assert model["levels"] == [] and model["notes"]
    page = _prep_page({}, model)
    assert "Zu wenige 15m- oder 1h-Kerzen" in page


def test_prep_page_renders_levels_and_sessions() -> None:
    model = build_session_map(_series(), NOW)
    page = _prep_page({}, model)
    assert "Level-Karte" in page and "Vortag VAH" in page and "row--current" in page
    assert "Sessions" in page and "/api/prep" in page


def _state() -> DashboardState:
    state = DashboardState()
    with state.lock:
        for tf, rows in _series().items():
            for candle in rows:
                state.record_chart_candle(candle)
    return state


def test_server_serves_prep_page_and_json() -> None:
    server = DashboardServer(_state(), port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/prep", timeout=5) as response:
            assert response.status == 200
            assert "Vorbereitung".encode() in response.read()
        with urlopen(f"http://127.0.0.1:{port}/api/prep", timeout=5) as response:
            model = json.loads(response.read())
            assert model["schema"] == "tim_session_map/1" and model["levels"]
    finally:
        server.stop()
