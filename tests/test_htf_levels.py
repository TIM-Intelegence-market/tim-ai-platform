"""Higher-timeframe prep levels: month/quarter/year value, anchored VWAPs, prep page and live chart."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import pytest

from src.dashboard.chart_live import KlineCache, build_live_chart, place_drawings, vwap_drawings
from src.dashboard.htf_levels import (anchored_vwap, build_htf_levels, period_profile, previous_periods, vwap,
                                      vwap_curve)
from src.dashboard.pages.prep import _prep_page
from src.dashboard.public_en import english_chart_model
from src.dashboard.session_map import build_session_map

NOW = datetime(2026, 10, 27, 14, 0, tzinfo=timezone.utc)  # Tuesday


def _c(opened: datetime, seconds: int, high: float, low: float, close: float, volume: float = 10.0, tf: str = "1d") -> dict:
    return {"symbol": "BTCUSDT", "timeframe": tf, "open_time": opened, "close_time": opened + timedelta(seconds=seconds),
            "open": close, "high": high, "low": low, "close": close, "volume": volume}


def _days(start: date, end: date, price=lambda i: 100.0 + i % 10) -> list[dict]:
    out, day, i = [], start, 0
    while day < end:
        p = price(i)
        out.append(_c(datetime(day.year, day.month, day.day, tzinfo=timezone.utc), 86400, p + 1, p - 1, p))
        day += timedelta(days=1)
        i += 1
    return out


def _weeks(start: date, end: date) -> list[dict]:
    first = start - timedelta(days=start.weekday())
    return [_c(datetime(d.year, d.month, d.day, tzinfo=timezone.utc), 7 * 86400, 120.0, 80.0, 100.0, 70.0, "1w")
            for d in (first + timedelta(weeks=i) for i in range((end - first).days // 7 + 1))]


def _months(start: date, end: date) -> list[dict]:
    out, d = [], start
    while d < end:
        nxt = d.replace(year=d.year + (d.month == 12), month=d.month % 12 + 1)
        out.append({**_c(datetime(d.year, d.month, d.day, tzinfo=timezone.utc), 0, 130.0, 70.0, 100.0, tf="1M"),
                    "close_time": datetime(nxt.year, nxt.month, nxt.day, tzinfo=timezone.utc)})
        d = nxt
    return out


def test_previous_periods_cover_the_last_finished_month_quarter_and_year() -> None:
    month, quarter, year = previous_periods(date(2026, 10, 27))
    assert (month["start"], month["end"], month["name"]) == (date(2026, 9, 1), date(2026, 10, 1), "Vormonat 09.2026")
    assert (quarter["start"], quarter["end"], quarter["name"]) == (date(2026, 7, 1), date(2026, 10, 1), "Vorquartal Q3 2026")
    assert (year["start"], year["end"], year["name"]) == (date(2025, 1, 1), date(2026, 1, 1), "Vorjahr 2025")
    month, quarter, year = previous_periods(date(2026, 1, 15))
    assert (month["start"], quarter["start"], year["start"]) == (date(2025, 12, 1), date(2025, 10, 1), date(2025, 1, 1))
    assert quarter["name"] == "Vorquartal Q4 2025"


def test_vwap_is_the_volume_weighted_typical_price_with_sigma() -> None:
    t = datetime(2026, 10, 26, tzinfo=timezone.utc)
    candles = [_c(t, 3600, 12, 8, 10, 1, "1h"), _c(t + timedelta(hours=1), 3600, 22, 18, 20, 3, "1h")]
    result = vwap(candles)
    assert result["value"] == pytest.approx(17.5)  # (10 * 1 + 20 * 3) / 4
    assert result["sigma"] == pytest.approx(math.sqrt((7.5 ** 2 + 3 * 2.5 ** 2) / 4))
    assert result["upper"] == pytest.approx(17.5 + result["sigma"])
    assert [round(v, 6) for _, v in vwap_curve(candles)] == [10.0, 17.5]
    assert vwap([_c(t, 3600, 12, 8, 10, 0, "1h")]) is None


def test_anchored_vwap_takes_the_finest_source_that_reaches_the_anchor() -> None:
    anchor = datetime(2026, 10, 26, tzinfo=timezone.utc)
    hours = [_c(anchor + timedelta(hours=i), 3600, 101, 99, 100, 1, "1h") for i in range(38)]
    days = _days(date(2026, 10, 1), date(2026, 10, 27))
    item = anchored_vwap("week", "1W", "VWAP Woche", anchor, (("1h", hours), ("1d", days)), NOW)
    assert (item["source"], item["candles"], item["value"]) == ("1h", 38, pytest.approx(100.0))
    # Hours start too late (a gap at the anchor): fall back to daily candles.
    item = anchored_vwap("week", "1W", "VWAP Woche", anchor, (("1h", hours[5:]), ("1d", days)), NOW)
    assert (item["source"], item["candles"]) == ("1d", 1)
    assert anchored_vwap("week", "1W", "VWAP Woche", anchor, (("1h", hours[5:]),), NOW) is None


def test_period_profile_uses_days_then_weeks_and_takes_edges_from_months() -> None:
    year = previous_periods(NOW.date())[2]
    days = _days(date(2025, 1, 1), date(2026, 10, 27))
    profile = period_profile(year, days, [], _months(date(2025, 1, 1), date(2026, 10, 1)))
    assert (profile["source"], profile["candles"]) == ("1d", 365)
    assert (profile["high"], profile["low"]) == (130.0, 70.0)  # exact edges from the twelve monthly candles
    assert profile["val"] <= profile["poc"] <= profile["vah"]
    # Days only from June 2025 (as with 500 daily candles): the year comes from weekly candles.
    late = [c for c in days if c["open_time"] >= datetime(2025, 6, 14, tzinfo=timezone.utc)]
    profile = period_profile(year, late, _weeks(date(2025, 1, 1), date(2026, 1, 1)), [])
    assert profile["source"] == "1w" and "Wochenkerzen" in profile["estimate"]
    assert profile["low"] <= profile["val"] <= profile["poc"] <= profile["vah"] <= profile["high"]
    assert period_profile(year, late, [], []) is None


def _series() -> dict[str, list[dict]]:
    days = _days(date(2025, 6, 14), date(2026, 10, 27), price=lambda i: 100.0 + 5 * math.sin(i / 9))
    hours = [_c(NOW - timedelta(hours=500 - i), 3600, 104, 98, 101, 1 + i % 3, "1h") for i in range(500)]
    halves = [_c(NOW - timedelta(minutes=30 * (500 - i)), 1800, 104, 98, 101, 1, "30m") for i in range(500)]
    return {"1d": days, "1w": _weeks(date(2016, 1, 1), date(2026, 10, 19)), "1M": _months(date(2020, 1, 1), date(2026, 10, 1)),
            "1h": hours, "30m": halves}


def test_build_htf_levels_lists_profiles_vwaps_and_sorted_levels() -> None:
    model = build_htf_levels(_series(), NOW, last=101.0)
    assert [p["tf"] for p in model["profiles"]] == ["1M", "1Q", "1Y"]
    # Anchored like Broncx: week, month, year; the quarter starts with the month in October (same line).
    assert [v["key"] for v in model["vwaps"]] == ["week", "month", "year"]
    week, month, year = model["vwaps"]
    assert week["source"] == "1h" and week["anchor"] == "2026-10-26T00:00:00+00:00"
    assert month["anchor"] == "2026-10-01T00:00:00+00:00"
    assert year["source"] == "1d" and year["anchor"] == "2026-01-01T00:00:00+00:00" and year["candles"] == 299
    assert week["upper2"] == pytest.approx(week["value"] + 2 * week["sigma"]) and week["lower2"] == pytest.approx(week["value"] - 2 * week["sigma"])
    prices = [level["price"] for level in model["levels"]]
    assert prices == sorted(prices, reverse=True)
    labels = {level["label"] for level in model["levels"]}
    assert {"1M VAL", "1Q POC", "1Y VAH", "1W VWAP", "1Y VWAP"} <= labels and "12M VWAP" not in labels
    assert all("distance_pct" in level and level["side"] in ("über", "unter", "am Kurs") for level in model["levels"])
    assert model["notes"] == ["VWAP Quartal ab 01.10. = VWAP Monat (gleicher Anker)."]


def test_quarter_vwap_has_its_own_anchor_once_the_month_moves_on() -> None:
    later = NOW + timedelta(days=10)  # 06.11.: month from 01.11., quarter from 01.10.
    series = _series()
    series["1d"] = series["1d"] + _days(date(2026, 10, 27), date(2026, 11, 6))
    model = build_htf_levels(series, later)
    keys = {v["key"]: v for v in model["vwaps"]}
    assert keys["quarter"]["anchor"] == "2026-10-01T00:00:00+00:00" and keys["quarter"]["tf"] == "1Q"
    assert keys["month"]["anchor"] == "2026-11-01T00:00:00+00:00"


def test_empty_series_gives_notes_not_errors() -> None:
    model = build_htf_levels({}, NOW)
    assert model["profiles"] == [] and model["vwaps"] == [] and model["levels"] == []
    assert any("Vorjahr 2025" in note for note in model["notes"])


def test_plan_journal_levels_stay_untouched() -> None:
    series = _series()
    prep = build_session_map(series, NOW)
    assert prep["htf_levels"]["profiles"]
    without = build_session_map({tf: rows for tf, rows in series.items() if tf in ("1h", "30m")}, NOW)
    # The plan journals read prep["levels"]: the new higher-timeframe levels must never show up there.
    assert all("VWAP" not in level["label"] and not level["label"].startswith(("1M ", "1Q ", "1Y ")) for level in prep["levels"])
    assert [level["label"] for level in prep["levels"]] == [level["label"] for level in without["levels"]]


def test_prep_page_shows_the_higher_timeframes_and_merges_them_into_the_level_map() -> None:
    html = _prep_page({}, build_session_map(_series(), NOW))
    assert "2b · Höhere Zeitebenen" in html and "Vorjahr 2025" in html and "VWAP Jahr ab 01.01.2026" in html
    assert "1Y VAH" in html and "1Y VWAP" in html


def test_live_chart_draws_vwap_as_a_line_when_the_anchor_is_in_view() -> None:
    start = datetime(2026, 10, 25, tzinfo=timezone.utc)
    candles = [_c(start + timedelta(hours=i), 3600, 101 + i % 3, 99, 100 + i % 2, 1 + i % 4, "1h") for i in range(60)]
    vwaps = build_htf_levels({"1h": candles}, NOW)["vwaps"]
    assert [v["key"] for v in vwaps] == ["week"]
    drawn = vwap_drawings(vwaps, candles, "1h", NOW)
    assert drawn[0]["curve"] and drawn[0]["start"] == "2026-10-26T00:00:00+00:00"
    times = [int(c["open_time"].timestamp()) for c in candles]
    placed = place_drawings(drawn, times)[0]
    assert placed["t1"] == int(datetime(2026, 10, 26, tzinfo=timezone.utc).timestamp()) and placed["t2"] == times[-1]
    assert placed["p2"] == pytest.approx(placed["curve"][-1][1]) and placed["bars"] == len(placed["curve"]) - 1
    # The weekly VWAP brings ±1σ/±2σ bands that run with the line (Broncx: weekly VWAP ±2σ).
    bands = [d for d in drawn if d["group"] == "vwap_bands"]
    assert [d["name"] for d in bands] == ["VWAP +2σ", "VWAP +1σ", "VWAP −1σ", "VWAP −2σ"]
    line = drawn[0]["curve"]
    for band, factor in zip(bands, (2, 1, -1, -2)):
        assert len(band["curve"]) == len(line)
        assert (band["curve"][-1][1] - line[-1][1]) * factor > 0
    assert bands[0]["curve"][-1][1] - line[-1][1] == pytest.approx(2 * (bands[1]["curve"][-1][1] - line[-1][1]))
    # Anchor not in the shown candles: only the current value is shown, the bands at their current values.
    flat = vwap_drawings(vwaps, candles[-5:], "1h", NOW)
    assert "curve" not in flat[0] and flat[0]["start"] == NOW.isoformat()
    flat_bands = [d for d in flat if d["group"] == "vwap_bands"]
    assert [d["price"] for d in flat_bands] == pytest.approx([vwaps[0]["upper2"], vwaps[0]["upper"], vwaps[0]["lower"], vwaps[0]["lower2"]])


def test_running_sigma_matches_the_closed_formula() -> None:
    from src.dashboard.htf_levels import vwap_band_curve

    start = datetime(2026, 10, 26, tzinfo=timezone.utc)
    candles = [_c(start + timedelta(hours=i), 3600, 80100 + 37 * (i % 7), 79900 - 11 * (i % 5), 80000 + 13 * (i % 9), 1 + i % 4, "1h") for i in range(48)]
    _, value, sigma = vwap_band_curve(candles)[-1]
    closed = vwap(candles)
    assert value == pytest.approx(closed["value"]) and sigma == pytest.approx(closed["sigma"], rel=1e-6)


def test_live_chart_and_public_view_carry_the_new_groups_in_english() -> None:
    from tests.test_chart_live import NOW as CHART_NOW, fake_fetch

    model = build_live_chart("ETHUSDT", "4h", None, cache=KlineCache(fake_fetch()), now=CHART_NOW)
    groups = {d["group"] for d in model["drawings"]}
    assert {"quarter", "year", "vwap"} <= groups
    english = english_chart_model(model)
    assert {"quarter", "year", "vwap"} <= set(english["groups"])
    text = " ".join(f"{d['label']} {d['note']}" for d in english["drawings"] if d["group"] in ("month", "quarter", "year", "vwap"))
    assert "Prior quarter Q3 2026" in text and "Prior year 2025" in text and "VWAP week from" in text
    for word in ("Vorquartal", "Vorjahr", "Kerzen", "geschätzt", "Woche ab", "Monat ab"):
        assert word not in text
