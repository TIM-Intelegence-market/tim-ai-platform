"""F3/F5 forward log and barometer (src/research_lab/forward/macro_filters.py): point in time, units, no network."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.research_lab.forward import macro_filters as mf

TODAY = date(2026, 11, 4)  # a Wednesday


def _daily(start: date, end: date, first: float, step: float) -> mf.Series:
    out, day, value = [], start, first
    while day <= end:
        if day.weekday() < 5:
            out.append((day, round(value, 4)))
            value += step
        day += timedelta(days=1)
    return out


def _weekly(wednesdays: int, last: date, first: float, step: float) -> mf.Series:
    return [(last - timedelta(weeks=wednesdays - 1 - i), first + step * i) for i in range(wednesdays)]


def test_f5_blocks_long_when_real_yield_rose_and_uses_only_earlier_days():
    series = _daily(date(2026, 6, 1), TODAY, 2.40, 0.002)
    t = mf.f5_state(series, TODAY)
    assert t is not None and t.rose
    assert t.day < TODAY  # the value of today itself is not known yet
    assert 91 <= (t.day - t.day_before).days <= 98
    falling = [(d, -v) for d, v in series]
    assert not mf.f5_state(falling, TODAY).rose


def test_f5_gives_no_state_for_stale_or_short_series():
    series = _daily(date(2026, 6, 1), date(2026, 10, 20), 2.40, 0.001)
    assert mf.f5_state(series, TODAY) is None  # latest value 15 days old
    assert mf.f5_state(_daily(date(2026, 9, 1), TODAY, 2.4, 0.001), TODAY) is None  # no value 13 weeks back


def test_f3_net_liquidity_uses_latest_complete_wednesday_and_rrp_lag():
    last_wed = date(2026, 10, 28)
    walcl = _weekly(20, last_wed, 6_700.0, -2.0)
    tga = _weekly(20, last_wed, 800.0, 3.0)
    rrp = _daily(date(2026, 5, 1), last_wed, 50.0, 0.0)
    t = mf.f3_state(walcl, tga, rrp, TODAY)
    assert t is not None and t.day == last_wed and t.day_before == last_wed - timedelta(weeks=13)
    assert t.value == pytest.approx(6_700.0 - 2.0 * 19 - (800.0 + 3.0 * 19) - 50.0)
    assert t.fell
    # without an RRP value within four days of the Wednesday there is no state for that week
    assert mf.net_liquidity_at(walcl, tga, [(last_wed - timedelta(days=6), 50.0)], last_wed) is None


def test_f3_falls_back_one_week_when_the_latest_week_is_incomplete():
    last_wed = date(2026, 10, 28)
    walcl = _weekly(20, last_wed, 6_700.0, 1.0)
    tga = _weekly(19, last_wed - timedelta(weeks=1), 800.0, 0.0)  # TGA for the last Wednesday not published yet
    rrp = _daily(date(2026, 5, 1), last_wed, 50.0, 0.0)
    t = mf.f3_state(walcl, tga, rrp, TODAY)
    assert t.day == last_wed - timedelta(weeks=1) and not t.fell


def test_units_are_scaled_to_billions_and_unknown_units_refused():
    assert mf.scale_to_billions("WTREGEN", "Millions of U.S. Dollars") == pytest.approx(0.001)
    assert mf.scale_to_billions("WTREGEN", "Billions of U.S. Dollars") == 1.0
    assert mf.scale_to_billions("DFII10", "Percent") == 1.0
    with pytest.raises(mf.MacroDataError):
        mf.scale_to_billions("WALCL", "Index 2015=100")


def _fake_fred(series: dict[str, tuple[str, mf.Series]]):
    seen = []

    def fetch(url: str) -> bytes:
        query = parse_qs(urlsplit(url).query)
        seen.append(url)
        sid = query["series_id"][0]
        units, rows = series[sid]
        if urlsplit(url).path.endswith("/series"):
            return json.dumps({"seriess": [{"units": units}]}).encode()
        return json.dumps({"observations": [{"date": d.isoformat(), "value": str(v)} for d, v in rows]
                           + [{"date": "2026-11-03", "value": "."}]}).encode()

    return fetch, seen


def test_fetch_reads_units_per_series_and_skips_missing_values():
    tga_millions = [(date(2026, 10, 28), 850_000.0)]
    fetch, seen = _fake_fred({"WTREGEN": ("Millions of U.S. Dollars", tga_millions),
                              "DFII10": ("Percent", [(date(2026, 10, 30), 2.6)])})
    data, raw = mf.fetch_series(("WTREGEN", "DFII10"), TODAY, fetch, "k" * 32)
    assert data["WTREGEN"] == [(date(2026, 10, 28), pytest.approx(850.0))]
    assert data["DFII10"] == [(date(2026, 10, 30), 2.6)]
    assert all(b"api_key" not in payload for payload in raw.values())  # stored answers never contain the URL or key
    assert all(u.startswith("https://api.stlouisfed.org/fred/") for u in seen)


def _full_data() -> dict[str, mf.Series]:
    last_wed = date(2026, 10, 28)
    return {"DFII10": _daily(date(2026, 5, 1), TODAY, 2.40, 0.002),
            "WALCL": _weekly(26, last_wed, 6_700.0, -2.0), "WTREGEN": _weekly(26, last_wed, 800.0, 3.0),
            "RRPONTSYD": _daily(date(2026, 5, 1), last_wed, 50.0, 0.0)}


def test_log_appends_once_per_utc_day(tmp_path: Path):
    path = tmp_path / mf.LOG_NAME
    now = datetime(2026, 11, 4, 8, 0, 3, 12, tzinfo=timezone.utc)
    row = mf.log_row(TODAY, now, _full_data(), "ab" * 32)
    assert row["f5_sperre_long"] == "ja" and row["f3_sperre_long"] == "ja"
    assert mf.append_log(path, row) is True
    assert mf.append_log(path, row) is False
    rows = mf.read_log(path)
    assert len(rows) == 1 and rows[0]["abruf_utc"] == "2026-11-04T08:00:03+00:00"


def test_unknown_state_is_logged_as_unknown_not_as_a_block():
    data = _full_data()
    data["DFII10"] = []
    row = mf.log_row(TODAY, datetime(2026, 11, 4, 8, tzinfo=timezone.utc), data, "0" * 64)
    assert row["f5_sperre_long"] == "unbekannt" and row["f3_sperre_long"] == "ja"


def test_state_at_uses_only_rows_fetched_before_the_signal():
    rows = [{"abruf_utc": "2026-11-03T08:00:00+00:00", "f5_sperre_long": "nein"},
            {"abruf_utc": "2026-11-04T08:00:00+00:00", "f5_sperre_long": "ja"}]
    early = mf.state_at(rows, datetime(2026, 11, 4, 4, tzinfo=timezone.utc))
    late = mf.state_at(rows, datetime(2026, 11, 4, 12, tzinfo=timezone.utc))
    assert early["f5_sperre_long"] == "nein" and late["f5_sperre_long"] == "ja"
    assert mf.state_at(rows, datetime(2026, 11, 2, tzinfo=timezone.utc)) is None


def test_barometer_is_descriptive_and_marks_unevaluated_drivers():
    data = _full_data()
    for _, sid, _ in mf.DRIVERS:
        data.setdefault(sid, _daily(date(2026, 5, 1), TODAY, 100.0, 0.1))
    text = mf.barometer_markdown(TODAY, data)
    assert "Woche 2026-45" in text and "keine Prognose" in text
    assert "| Realzins 10J |" in text and "gestiegen | -0.19 % | +1.49 % | -0.20 |" in text
    assert "noch nicht ausgewertet" in text  # breakeven inflation has no historical reading yet
    assert "| Netto-Liquidität (Mrd. USD) |" in text and "gefallen | +0.30 % | +1.05 %" in text
    assert "Keine BTC-Daten ab 2025" in text


def test_module_loads_no_archive_or_btc_data():
    source = Path(mf.__file__).read_text()
    assert "ArchiveStore" not in source and "data.store" not in source and "binance" not in source.lower()
