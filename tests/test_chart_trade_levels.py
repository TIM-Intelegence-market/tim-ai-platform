"""Chart levels from TIM's own trades instead of the candle estimate (Beirat 29.10.2026).

Day/week value, running POCs and naked POCs of the days the aggTrades store covers come
from the trades; naked POCs are marked as vPOC (volume) and tPOC (time) like Broncx does.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.dashboard.chart_live import trade_levels
from src.dashboard.footprint_data import DAYS_KEPT, profile_from_rows, volume_profiles

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)  # Thursday
TICK = 5.0


def _day_rows(day: date, poc: float, others: list[float], hours: int = 24) -> list[list[float]]:
    """One row per hour: heavy volume at ``poc``, light volume at the other levels."""
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
    rows = []
    for hour in range(hours):
        t = start + hour * 3600
        rows.append([t, poc, 5.0, 6.0])
        rows.extend([t, level, 0.5, 0.5] for level in others)
    return rows


def _store() -> dict:
    """15.10. .. 29.10.: every day trades 80.000-81.000 with its POC at 80.500, except 22.10.
    (POC 82.800, range 82.500-83.000, never traded again). Today (running) trades 80.000-81.000."""
    days, complete = {}, {}
    day = NOW.date() - timedelta(days=DAYS_KEPT)
    while day <= NOW.date():
        if day == date(2026, 10, 22):
            rows = _day_rows(day, 82800.0, [82500.0, 82600.0, 82700.0, 82900.0, 83000.0])
        elif day == NOW.date():
            rows = _day_rows(day, 80500.0, [80000.0, 80250.0, 80750.0, 81000.0], hours=10)
        else:
            rows = _day_rows(day, 80500.0, [80000.0, 80250.0, 80750.0, 81000.0])
        days[day.isoformat()] = rows
        if day != NOW.date():
            complete[day.isoformat()] = int(NOW.timestamp())
        day += timedelta(days=1)
    return {"symbol": "BTCUSDT", "tick": TICK, "bucket_seconds": 300, "days": days, "complete": complete}


ESTIMATE = [
    {"group": "day", "tf": "1D", "name": "POC", "label": "1D POC", "price": 80912.5, "start": "2026-10-28T00:00:00+00:00", "note": "Vortag 28.10."},
    {"group": "day", "tf": "1D", "name": "High", "label": "1D High", "price": 81823.0, "start": "2026-10-28T13:00:00+00:00", "note": "Vortag 28.10."},
    {"group": "week", "tf": "1W", "name": "POC", "label": "1W POC", "price": 81750.0, "start": "2026-10-19T00:00:00+00:00", "note": "Vorwoche ab 19.10."},
    {"group": "naked", "tf": "1D", "name": "nPOC 23.10.", "label": "1D nPOC 23.10.", "price": 81675.0, "start": "2026-10-23T00:00:00+00:00", "note": "unberührter Tages-POC"},
    {"group": "naked", "tf": "1D", "name": "nPOC 10.10.", "label": "1D nPOC 10.10.", "price": 90000.0, "start": "2026-10-10T00:00:00+00:00", "note": "unberührter Tages-POC"},
    {"group": "running", "tf": "1D", "name": "POC lfd.", "label": "1D POC lfd.", "price": 79925.0, "start": "2026-10-29T00:00:00+00:00", "note": "laufendes Tagesprofil"},
]


def test_store_keeps_two_weeks_so_the_previous_week_is_always_complete() -> None:
    # Sunday is the worst case: the previous week started 13 days ago.
    assert DAYS_KEPT >= 13


def test_profile_from_rows_matches_the_day_profiles_and_marks_the_row_centre() -> None:
    store = _store()
    rows = store["days"]["2026-10-22"]
    profile = profile_from_rows(rows, TICK)
    assert profile["poc"] <= 82800.0 < profile["poc"] + profile["step"]
    assert profile["poc_mid"] == pytest.approx(profile["poc"] + profile["step"] / 2)
    day = next(p for p in volume_profiles(store, NOW) if p["day"] == "2026-10-22")
    assert (day["poc"], day["vah"], day["val"], day["complete"]) == (profile["poc"], profile["vah"], profile["val"], True)


def test_previous_day_and_week_value_come_from_the_trades() -> None:
    out = trade_levels(ESTIMATE, _store(), {}, NOW)
    by_label = {d["label"]: d for d in out}
    poc = by_label["1D POC"]
    assert poc["source"] == "trades" and poc["note"] == "Vortag 28.10., echte Trades"
    assert poc["price"] != 80912.5 and abs(poc["price"] - 80500.0) <= 50
    assert {"1D VAH", "1D VAL", "1W VAH", "1W POC", "1W VAL"} <= set(by_label)
    assert by_label["1W POC"]["note"].startswith("Vorwoche ab 19.10.") and by_label["1W POC"]["source"] == "trades"
    # Highs and lows stay as they were (exact from the candles).
    assert by_label["1D High"]["price"] == 81823.0
    # The running day POC comes from today's trades.
    running = [d for d in out if d["group"] == "running" and d["tf"] == "1D"]
    assert len(running) == 1 and running[0]["source"] == "trades"


def test_untouched_volume_poc_is_shown_even_when_the_candle_estimate_said_touched() -> None:
    out = trade_levels(ESTIMATE, _store(), {}, NOW)
    naked = {d["name"]: d for d in out if d["group"] == "naked"}
    # 22.10.: POC row 82.800 was never traded again -> naked vPOC (the case measured on 29.10.).
    assert "nPOC 22.10." in naked and 82800.0 <= naked["nPOC 22.10."]["price"] <= 82850.0
    assert "vPOC" in naked["nPOC 22.10."]["note"]
    # Days whose POC was traded later are not naked; the estimate's 23.10. entry is replaced.
    assert "nPOC 23.10." not in naked
    # A day older than the store keeps the estimate, marked as such.
    assert naked["nPOC 10.10."]["note"] == "unberührter Tages-POC (Schätzung aus Kerzen)"


def test_without_trades_nothing_changes() -> None:
    assert trade_levels(ESTIMATE, {"symbol": "BTCUSDT", "tick": TICK, "days": {}}, {}, NOW) == ESTIMATE


def _half_hours(day: date, low: float, high: float) -> list[dict]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return [{"symbol": "BTCUSDT", "timeframe": "30m", "open_time": start + timedelta(minutes=30 * i),
             "close_time": start + timedelta(minutes=30 * (i + 1)), "open": low, "high": high, "low": low, "close": high, "volume": 1.0}
            for i in range(48)]


def test_untouched_tpo_poc_is_marked_as_tpoc() -> None:
    candles = []
    for offset in range(6, 0, -1):
        day = NOW.date() - timedelta(days=offset)
        candles += _half_hours(day, 90000.0, 90400.0) if day == date(2026, 10, 25) else _half_hours(day, 80000.0, 81000.0)
    out = trade_levels(ESTIMATE, _store(), {"30m": candles}, NOW)
    tpocs = {d["name"]: d for d in out if d["group"] == "naked" and d["name"].startswith("tPOC")}
    assert "tPOC 25.10." in tpocs and 90000.0 <= tpocs["tPOC 25.10."]["price"] <= 90400.0
    assert "Zeit" in tpocs["tPOC 25.10."]["note"]
    assert "tPOC 26.10." not in tpocs  # its POC was traded the next day


def test_tpoc_reaches_back_as_far_as_the_longer_30m_history() -> None:
    # The runtime keeps about ten days of 30m candles; a day older than that (here 17.10., untouched)
    # only gets its tPOC when the chart passes the longer Binance 30m history (Prüfung 31.10.2026).
    old = date(2026, 10, 17)
    recent = []
    for offset in range(6, 0, -1):
        recent += _half_hours(NOW.date() - timedelta(days=offset), 80000.0, 81000.0)
    longer = []
    day = old
    while day < NOW.date():
        longer += _half_hours(day, 95000.0, 95400.0) if day == old else _half_hours(day, 80000.0, 81000.0)
        day += timedelta(days=1)
    short = trade_levels(ESTIMATE, _store(), {"30m": recent}, NOW)
    assert not any(d["name"] == "tPOC 17.10." for d in short)
    full = trade_levels(ESTIMATE, _store(), {"30m": recent}, NOW, {"30m": longer})
    tpoc = next(d for d in full if d["name"] == "tPOC 17.10.")
    assert 95000.0 <= tpoc["price"] <= 95400.0
