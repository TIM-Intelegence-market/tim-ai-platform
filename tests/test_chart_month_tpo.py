"""Month TPO (Uzi 26.11.2026): time at price per calendar month, 4h blocks, fixed rows, levels in the row middle."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.dashboard import chart_live, legend, public_en
from src.dashboard.chart_live import level_drawings, month_tpo_profiles

NOW = datetime(2026, 11, 26, 13, 36, tzinfo=timezone.utc)


def _candles(start: datetime, end: datetime, hours: float, price_at) -> list[dict]:
    rows, moment = [], start
    while moment + timedelta(hours=hours) <= end:
        low, high = price_at(moment)
        rows.append({"open_time": moment.isoformat(), "close_time": (moment + timedelta(hours=hours)).isoformat(),
                     "open": low, "high": high, "low": low, "close": high, "volume": 1.0})
        moment += timedelta(hours=hours)
    return rows


def _two_levels(moment: datetime) -> tuple[float, float]:
    # Ten days around 75,000, then the rest of the month around 64,900: the second plateau is longer.
    if datetime(2026, 11, 1, tzinfo=timezone.utc) <= moment < datetime(2026, 11, 11, tzinfo=timezone.utc):
        return 75_010.0, 75_040.0
    return 64_910.0, 64_940.0


def test_month_tpo_finds_the_longer_plateau_in_the_row_middle():
    series = {"1h": _candles(datetime(2026, 10, 1, tzinfo=timezone.utc), NOW, 1, _two_levels)}
    profiles = month_tpo_profiles(series, NOW)
    assert [p["month"] for p in profiles] == ["2026-10", "2026-11"]
    month = profiles[-1]
    assert month["running"] and month["step"] == 50 and month["block_hours"] == 4
    assert month["tpoc"] == 64_925.0  # row 64,900-64,950, middle as on the reference
    assert month["tval"] == 64_925.0 and month["tvah"] == 75_025.0  # the gap rows are empty, the VA jumps over them
    assert month["blocks"] == (25 * 24 + 12) // 4 + 1  # the running 4h block counts with its closed hours


def test_month_tpo_needs_the_month_start_and_ignores_open_candles():
    late = {"1h": _candles(datetime(2026, 11, 5, tzinfo=timezone.utc), NOW, 1, _two_levels)}
    assert month_tpo_profiles(late, NOW) == []
    series = {"4h": _candles(datetime(2026, 10, 1, tzinfo=timezone.utc), NOW + timedelta(hours=8), 4, _two_levels)}
    month = month_tpo_profiles(series, NOW)[-1]
    assert month["blocks"] == 25 * 6 + 3  # 4h candles closed by 13:36: 00-04, 04-08, 08-12


def test_month_tpo_levels_are_drawn_as_own_layer():
    series = {"1h": _candles(datetime(2026, 10, 1, tzinfo=timezone.utc), NOW, 1, _two_levels)}
    drawings = [d for d in level_drawings(series, NOW) if d["group"] == "tpo_month"]
    labels = {d["label"]: d["price"] for d in drawings}
    assert labels["1M TPOC lfd."] == 64_925.0 and labels["1M TVAH lfd."] == 75_025.0
    assert "1M TPOC 10.26" in labels
    assert "tpo_month" in chart_live.DEFAULT_GROUPS and "tpo_month" in chart_live.GROUP_STYLE
    assert "tpo_month" in legend.LAYERS and "tpo_month" in public_en.GROUPS_EN


def test_month_tpo_names_a_second_peak_of_almost_equal_length():
    def even(moment: datetime) -> tuple[float, float]:
        # Two plateaus of almost the same length (November 2026 on Binance Perp: 22 vs 21 blocks).
        if moment < datetime(2026, 11, 13, 4, tzinfo=timezone.utc):
            return 75_860.0, 75_890.0
        return 64_910.0, 64_940.0

    series = {"1h": _candles(datetime(2026, 10, 1, tzinfo=timezone.utc), NOW, 1, even)}
    month = month_tpo_profiles(series, NOW)[-1]
    assert {month["tpoc"], month["tpoc2"]} == {75_875.0, 64_925.0}
    labels = {d["label"] for d in level_drawings(series, NOW) if d["group"] == "tpo_month"}
    assert "1M TPOC 2 lfd." in labels
    clear = month_tpo_profiles({"1h": _candles(datetime(2026, 10, 1, tzinfo=timezone.utc), NOW, 1, _two_levels)}, NOW)[-1]
    assert clear["tpoc2"] is None  # 60 against 94 blocks: one clear peak
