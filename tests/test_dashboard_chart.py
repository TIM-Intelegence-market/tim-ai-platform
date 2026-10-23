from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.chart_model import break_of_structure, build_chart_model, clean_candles, profile_source, volume_profile
from src.dashboard.layout import _content_security_policy
from src.dashboard.pages.chart import render_chart_page

END = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _candle(tf: str, opened: datetime, seconds: int, o: float, h: float, l: float, c: float, v: float = 10.0) -> dict:
    return {"symbol": "BTCUSDT", "timeframe": tf, "open_time": opened.isoformat(), "close_time": (opened + timedelta(seconds=seconds)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "trade_count": 5, "provenance": "PUBLIC_MARKET_DATA"}


def _minute_series(count: int = 600) -> list[dict]:
    """Deterministic 1m candles: a range around 83,000 that rallies at the end."""
    out, price = [], 83000.0
    start = END - timedelta(minutes=count)
    for i in range(count):
        drift = 3.0 if i > count - 120 else 0.0
        close = price + drift + 25 * math.sin(i / 7)
        out.append(_candle("1m", start + timedelta(minutes=i), 60, price, max(price, close) + 6, min(price, close) - 6, close, 5 + (i % 9)))
        price = close
    return out


def _aggregate(minutes: list[dict], tf: str, size: int) -> list[dict]:
    out = []
    for i in range(0, len(minutes) - size + 1, size):
        group = minutes[i:i + size]
        out.append({**group[0], "timeframe": tf, "close_time": group[-1]["close_time"], "high": max(g["high"] for g in group),
                    "low": min(g["low"] for g in group), "close": group[-1]["close"], "volume": sum(g["volume"] for g in group)})
    return out


def _state() -> DashboardState:
    state = DashboardState()
    minutes = _minute_series()
    with state.lock:
        for tf, size in (("1m", 1), ("5m", 5), ("15m", 15), ("1h", 60)):
            for candle in _aggregate(minutes, tf, size):
                state.record_chart_candle(candle)
    return state


def test_state_keeps_newest_candles_per_timeframe_without_duplicates() -> None:
    state = DashboardState()
    start = END - timedelta(minutes=10)
    with state.lock:
        for i in range(10):
            state.record_chart_candle(_candle("1m", start + timedelta(minutes=i), 60, 100, 101, 99, 100.5), limit=5)
        # The same open time again replaces the old candle instead of adding one.
        state.record_chart_candle(_candle("1m", start + timedelta(minutes=9), 60, 100, 105, 99, 104), limit=5)
        state.record_chart_candle(_candle("5m", start, 300, 100, 101, 99, 100.5), limit=5)
    series = state.chart_series()
    assert len(series["1m"]) == 5 and series["1m"][-1]["close"] == 104
    assert [c["open_time"] for c in series["1m"]] == sorted(c["open_time"] for c in series["1m"])
    assert len(series["5m"]) == 1


def test_state_falls_back_to_recent_candles_grouped_by_timeframe() -> None:
    state = DashboardState()
    state.recent_candles = [_candle("1m", END, 60, 1, 2, 0.5, 1.5), _candle("5m", END, 300, 1, 2, 0.5, 1.5)]
    assert set(state.chart_series()) == {"1m", "5m"}


def test_model_clean_candles_drops_broken_rows() -> None:
    rows = [
        _candle("1m", END, 60, 100, 101, 99, 100),
        {**_candle("1m", END + timedelta(minutes=1), 60, 100, 101, 99, 100), "high": 98},  # high below open
        {**_candle("1m", END + timedelta(minutes=2), 60, 100, 101, 99, 100), "close": "nan"},
        {**_candle("1m", END + timedelta(minutes=3), 60, 100, 101, 99, 100), "open_time": "kaputt"},
        _candle("5m", END, 300, 100, 101, 99, 100),
    ]
    assert len(clean_candles(rows, "1m")) == 1


def test_model_volume_profile_finds_poc_and_seventy_percent_value_area() -> None:
    start = END
    candles = clean_candles([
        _candle("1m", start, 60, 100, 101, 100, 101, 1),
        _candle("1m", start + timedelta(minutes=1), 60, 104, 105, 104, 105, 80),
        _candle("1m", start + timedelta(minutes=2), 60, 103, 104, 103, 104, 10),
        _candle("1m", start + timedelta(minutes=3), 60, 108, 109, 108, 109, 1),
    ], "1m")
    profile = volume_profile(candles)
    assert profile is not None
    assert 104 <= profile["poc"] <= 105
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    inside = sum(b["volume"] for b in profile["bins"] if profile["val"] <= b["low"] and b["high"] <= profile["vah"])
    assert inside >= 0.7 * profile["total_volume"]
    assert volume_profile(candles[:1]) is None


def test_model_bos_needs_close_beyond_confirmed_swing() -> None:
    start = END
    highs = [100, 101, 105, 101, 100, 102, 103, 104, 106]
    rows = [_candle("15m", start + timedelta(minutes=15 * i), 900, h - 1, h, h - 2, h - 0.5) for i, h in enumerate(highs)]
    events = break_of_structure(clean_candles(rows, "15m"), "15m")
    up = [e for e in events if e["direction"] == "UP"]
    assert up and up[-1]["level"] == 105 and up[-1]["break_index"] == 8  # first close above 105 is the last candle
    # A wick above the swing without a close above it is no BOS.
    rows[-1] = _candle("15m", start + timedelta(minutes=15 * 8), 900, 103, 106, 102, 104)
    assert not [e for e in break_of_structure(clean_candles(rows, "15m"), "15m") if e["direction"] == "UP"]


def test_model_profile_uses_finest_timeframe_that_covers_the_window() -> None:
    state = _state()
    series = state.chart_series()
    candles = clean_candles(series["15m"], "15m")[-30:]  # 450 min, inside the 500 kept 1m candles
    finer, source = profile_source(series, candles, "15m")
    assert source == "1m" and len(finer) >= 15 * (len(candles) - 1)
    # Without enough 1m history the next coarser timeframe is used, then the chart's own.
    series["1m"] = series["1m"][-30:]
    assert profile_source(series, candles, "15m")[1] == "5m"
    series["5m"] = series["5m"][-3:]
    assert profile_source(series, candles, "15m")[1] == "15m"


def test_model_contains_levels_bos_scenarios_and_preview_plan() -> None:
    model = build_chart_model(_state().chart_series(), "5m", now=END + timedelta(seconds=30))
    assert model["timeframe"] == "5m" and model["read_only"] is True
    assert len(model["candles"]) == 120
    levels = model["levels"]
    assert levels["range_low"] <= levels["last"] <= levels["range_high"] and levels["age_seconds"] == 30
    profile = model["profile"]
    assert profile["val"] <= profile["poc"] <= profile["vah"] and "geschätzt" in profile["source"]
    assert {b["timeframe"] for b in model["bos"]} <= {"5m", "15m", "1h"}
    analysis = model["analysis"]
    assert analysis["decision"]["status"] == "NO_TRADE"  # no trades in the dashboard: never more than observation
    assert analysis["data_quality"]["missing"] == ["trades"]
    with_zone = [s for s in analysis["scenarios"] if s["entry_low"] is not None]
    assert with_zone, analysis["scenarios"]
    for scenario in with_zone:
        assert scenario["state"] == "PROPOSED"
        preview = scenario["preview"]
        if preview:
            if scenario["direction"] == "LONG":
                assert preview["stop"] < preview["entry"] < preview["targets"][0]
            else:
                assert preview["targets"][0] < preview["entry"] < preview["stop"]
    json.dumps(model)  # JSON-ready


def test_model_with_external_profile_and_empty_series() -> None:
    model = build_chart_model(_state().chart_series(), "15m", profile={"poc": 83000, "vah": 83100, "val": 82900, "source": "OpenMarket"})
    assert model["profile"]["source"] == "OpenMarket" and model["profile"]["poc"] == 83000
    empty = build_chart_model({}, "unbekannt")
    assert empty["timeframe"] == "15m" and empty["candles"] == [] and empty["notes"]


def test_page_draws_svg_with_levels_and_keeps_csp() -> None:
    page = render_chart_page(_state(), "15m")
    assert "<svg viewBox='0 0 1000 520'" in page and "class='tc-body" in page
    for marker in ("VAH ", "VAL ", "POC ", "Range-High", "Kurs "):
        assert marker in page
    assert "Vorschau nach TIMs Regeln" in page and "Keine Order" in page
    assert "aria-current='page'>15m</a>" in page and ">TIM-Chart</a>" in page
    assert "<script src" not in page and " style='" not in page  # nothing the CSP would have to allow
    assert page.count("<script>") == 1  # only the shared auto refresh


def test_page_without_candles_shows_empty_state() -> None:
    page = render_chart_page(DashboardState(), "1h")
    assert "Noch keine Kerzen" in page and "<svg viewBox='0 0 1000 520'" not in page


def test_server_serves_chart_page_and_json() -> None:
    server = DashboardServer(_state(), port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/chart?tf=5m", timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Security-Policy"] == _content_security_policy()
            assert b"TIM-Chart" in response.read()
        with urlopen(f"http://127.0.0.1:{port}/api/chart?tf=1h", timeout=5) as response:
            model = json.loads(response.read())
            assert model["timeframe"] == "1h" and model["candles"]
    finally:
        server.stop()


def test_model_writes_out_plans_invalidation_and_risk() -> None:
    model = build_chart_model(_state().chart_series(), "5m", now=END + timedelta(seconds=30))
    plans = [s for s in model["analysis"]["scenarios"] if s["plan_text"]]
    assert plans
    for scenario in plans:
        assert scenario["plan_text"].startswith(f"PLAN {scenario['id']} {scenario['direction']}  Limit ")
        invalid = scenario["invalidation_level"]
        assert invalid["side"] == ("<" if scenario["direction"] == "LONG" else ">")
        assert invalid["text"].startswith(f"Ungültig {scenario['id']}: 5m-Schluss")
        if scenario["preview"]:
            assert scenario["preview"]["stop_text"].startswith(f"Stop {scenario['id']} ")
    assert model["risk"]["max_leverage"] == 10 and "keine Anlageberatung" in model["risk"]["text"]


def test_ny_open_windows_follow_new_york_time() -> None:
    from src.dashboard.chart_model import ny_open_windows

    summer = ny_open_windows(datetime(2026, 10, 21, 0, tzinfo=timezone.utc), datetime(2026, 10, 21, 23, tzinfo=timezone.utc))
    assert [w["open"] for w in summer] == ["2026-10-21T13:30:00+00:00"]
    assert summer[0]["start"] == "2026-10-21T13:15:00+00:00" and summer[0]["end"] == "2026-10-21T14:00:00+00:00"
    winter = ny_open_windows(datetime(2026, 12, 1, 0, tzinfo=timezone.utc), datetime(2026, 12, 1, 23, tzinfo=timezone.utc))
    assert [w["open"] for w in winter] == ["2026-12-01T14:30:00+00:00"]
    assert ny_open_windows(datetime(2026, 10, 24, 0, tzinfo=timezone.utc), datetime(2026, 10, 25, 23, tzinfo=timezone.utc)) == []  # weekend


def test_setup_path_shows_written_out_plans_from_chart(monkeypatch) -> None:
    from src.dashboard import views
    from src.dashboard.views import render

    # Fixed clock: with the real time the next NY window can be after the weekend, beyond the 24 h look-ahead.
    real_build = views.build_chart_model
    monkeypatch.setattr(views, "build_chart_model", lambda *args, **kwargs: real_build(*args, **{"now": END, **kwargs}))
    page = render(_state(), "Setup Path")
    assert "TIMs Pläne im Chart (15m)" in page and "class='tc-svg'" in page
    assert "PLAN " in page and "Ungültig " in page and "keine Anlageberatung" in page
    assert "class='sp-plan" in page and "Nächste Sperrzeit: NY-Eröffnung" in page
    # Without per-timeframe candles the old close-price line stays.
    assert "setup-chart__line" in render(DashboardState(recent_candles=[{"close": 80_000 + i} for i in range(20)]), "Setup Path")
