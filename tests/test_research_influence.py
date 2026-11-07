"""Influence research (EINFLUSS_BAROMETER.md 5a-5c): point in time, holdout, descriptive measures."""
from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from src.research_lab.forward import macro_filters
from src.research_lab.influence import __main__ as cli
from src.research_lab.influence import analysis, report, zuordnung
from src.research_lab.influence.catalog import DRIVERS, Driver, all_series, by_key
from src.research_lab.influence.states import (
    HoldoutError,
    btc_weekly_returns,
    change,
    driver_weeks,
    known_at,
    weeks,
)

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
DAILY = Driver("X", "Test", ("X",), "pct", 1, "test")


def daily(values_by_week: dict[date, float]) -> list[tuple[date, float]]:
    """One observation per day, constant within each grid week (Monday..Sunday)."""
    out = []
    for week, value in values_by_week.items():
        out += [(week + timedelta(days=i), value) for i in range(7)]
    return sorted(out)


def test_grid_mondays_and_ends_before_holdout():
    grid = weeks()
    assert all(d.weekday() == 0 for d in grid)
    assert grid[-1] + timedelta(days=7) <= date(2025, 1, 1)
    assert grid[-1] == date(2024, 12, 23)


def test_known_at_respects_lag_and_age():
    series = [(date(2024, 1, 1), 1.0), (date(2024, 1, 8), 2.0)]
    assert known_at(series, date(2024, 1, 8), DAILY) == (date(2024, 1, 1), 1.0)  # 8th not published yet
    assert known_at(series, date(2024, 1, 9), DAILY) == (date(2024, 1, 8), 2.0)
    assert known_at(series, date(2024, 2, 15), DAILY) is None  # older than max_age_days


def test_change_units():
    assert change("bp", 1.0, 1.25) == pytest.approx(25.0)
    assert change("pct", 100.0, 110.0) == pytest.approx(10.0)
    assert change("diff", 5.0, 3.0) == -2.0
    assert change("pct", 0.0, 1.0) is None


def test_state_compares_13_weeks_known_at_week_start():
    grid = weeks(date(2020, 1, 6), date(2020, 6, 1))
    values = {w: 100.0 + i for i, w in enumerate(grid)}
    rows = driver_weeks(DAILY, {"X": daily(values)}, grid)
    assert rows[14].state == "gestiegen"
    assert rows[13].state is None  # the value 13 weeks before is not published yet at the first week
    # change_week of week i is known at week i+1 (lag 1 day: Sunday value), never later data
    assert rows[13].change_week == pytest.approx(change("pct", values[grid[12]], values[grid[13]]))


def test_btc_holdout_refused():
    with pytest.raises(HoldoutError):
        btc_weekly_returns({date(2025, 1, 1): 1.0}, weeks())


def test_btc_weekly_returns():
    grid = [date(2024, 1, 8)]
    closes = {date(2024, 1, 7): 100.0, date(2024, 1, 14): 110.0}
    assert btc_weekly_returns(closes, grid)[date(2024, 1, 8)] == pytest.approx(10.0)


def _synthetic(lead: bool):
    rng = random.Random(7)
    grid = weeks()
    btc = {w: rng.gauss(0, 5) for w in grid}
    level, values = 100.0, {}
    for i, w in enumerate(grid):
        if lead:  # the driver's weekly move predicts BTC one week later
            nxt = grid[i + 2] if i + 2 < len(grid) else None
            move = btc[nxt] if nxt else 0.0
        else:  # the driver follows BTC one week later
            prev = grid[i - 1] if i else None
            move = btc[prev] if prev else 0.0
        values[w] = level
        level *= 1 + move / 1000
    return grid, btc, values


@pytest.mark.parametrize("lead", [True, False])
def test_lead_and_follow_detected(lead):
    grid, btc, values = _synthetic(lead)
    rows = driver_weeks(DAILY, {"X": daily(values)}, grid)
    info = analysis.describe(rows, btc)
    # change_week(t) is the move published during week t: for "lead" it equals btc(t+1)
    if lead:
        assert info["vorlauf_wochen"][1] > 0.9
        assert info["folgt_dem_kurs"] is False
    else:
        assert info["nachlauf_wochen"][1] is not None
        assert info["folgt_dem_kurs"] is True


def test_joint_separates_driver_from_noise():
    rng = random.Random(3)
    grid = weeks(date(2018, 1, 1))
    x = {w: rng.gauss(0, 1) for w in grid}
    z = {w: rng.gauss(0, 1) for w in grid}
    btc = {w: 2 * x[w] + 0.1 * rng.gauss(0, 1) for w in grid}
    from src.research_lab.influence.states import WeekRow

    rows = {"A": [WeekRow(w, None, None, x[w]) for w in grid], "B": [WeekRow(w, None, None, z[w]) for w in grid]}
    res = analysis.joint(rows, btc)["ergebnis"]
    assert res["r2"] > 0.95
    assert res["r2_beitrag"]["A"] > 0.9
    assert res["r2_beitrag"]["B"] < 0.01


def test_corr_needs_ten_pairs_and_variation():
    assert analysis.corr([(1.0, 2.0)] * 9) is None
    assert analysis.corr([(1.0, float(i)) for i in range(20)]) is None


def _report():
    _, btc, values = _synthetic(True)
    data = {"X": daily(values)}
    return report.build(data, btc, now=NOW, drivers=(DAILY,), inputs={"X": "abc"})


def test_report_roundtrip_and_markdown(tmp_path):
    rep = _report()
    js, md = report.write(rep, tmp_path)
    loaded = json.loads(js.read_text())
    assert loaded["schema"] == report.SCHEMA and loaded["angeschaute_treiber"] == 1
    text = md.read_text()
    assert "kein Handelssignal" in text and "Test" in text and "2025-01-01" in text
    assert report.markdown(loaded)  # renders from JSON (string keys) too
    hist = report.history_for_barometer(loaded)["X"]
    assert set(hist) == {"gestiegen", "gefallen", "vorlauf"}


def test_barometer_reads_history_from_report(tmp_path):
    rep = {"treiber": {"DFII10": {"zustaende": {"gestiegen": {"btc_woche_mittel": -9.0}, "gefallen": {"btc_woche_mittel": 9.0}},
                                  "vorlauf_13w_auf_4w": -0.5},
                       "NETLIQ": {"zustaende": {"gestiegen": {"btc_woche_mittel": 1.0}, "gefallen": {"btc_woche_mittel": None}},
                                  "vorlauf_13w_auf_4w": 0.1}}}
    path = tmp_path / "r.json"
    path.write_text(json.dumps(rep))
    table = macro_filters.history_from_report(path)
    assert table["DFII10"]["gestiegen"] == -9.0
    assert table[macro_filters.LIQUIDITY]["gestiegen"] == 1.0
    assert table["DTWEXBGS"] == macro_filters.HISTORY["DTWEXBGS"]  # not in the report: fixed numbers stay
    today = date(2026, 11, 2)
    series = sorted((today - timedelta(days=i), 2.0 - i / 100) for i in range(1, 120))
    text = macro_filters.barometer_markdown(today, {"DFII10": series}, table)
    assert "-9.00 %" in text


def test_zuordnung_states_history_and_events():
    rep = _report()
    today = date(2026, 11, 9)
    series = sorted((today - timedelta(days=i), 100.0 - i / 10) for i in range(1, 150))  # risen over 13 weeks
    events = [{"kind": "CPI", "time": datetime(2026, 11, 12, 13, 30, tzinfo=timezone.utc), "label": "US-CPI"},
              {"kind": "FOMC", "time": datetime(2026, 12, 9, 19, tzinfo=timezone.utc), "label": "FOMC"}]
    res = zuordnung.build({"X": series}, rep, events, today, drivers=(DAILY,))
    row = res["treiber"][0]
    assert row["zustand"] == "gestiegen" and "btc_so" in row
    assert [e["kind"] for e in res["termine"]] == ["CPI"]  # FOMC is more than 7 days ahead
    assert "1,40" in res["termine"][0]["historisch"]
    text = zuordnung.markdown(res)
    assert "kein Handelssignal" in text and "US-CPI" in text


def test_catalog_unique_and_complete():
    keys = [d.key for d in DRIVERS]
    assert len(keys) == len(set(keys))
    assert by_key("SP500").family == "aktien"
    assert {"WALCL", "WTREGEN", "RRPONTSYD", "SP500", "DEXJPUS"} <= set(all_series())
    assert {d.key for d in DRIVERS if d.needs_lead} == {"BTCD", "USDTD"}  # crypto-internal: lead rule (5b)


def test_stored_history_hash_checked(tmp_path):
    payload = json.dumps({"observations": [{"date": "2024-12-30", "value": "1.5"},
                                           {"date": "2025-01-02", "value": "1.6"}]}).encode()
    answers = {"series": json.dumps({"seriess": [{"units": "Percent"}]}).encode(), "obs": payload}

    def fetch(url: str) -> bytes:
        assert "observation_end=2024-12-31" in url or "/series?" in url
        return answers["obs" if "observations" in url else "series"]

    cli.fetch_history(tmp_path, fetch, "KEY", ("DFII10",))
    raw = (tmp_path / "roh" / "DFII10.json").read_bytes()
    assert b"KEY" not in raw
    data, _ = cli.load_history(tmp_path)
    assert data["DFII10"] == [(date(2024, 12, 30), 1.5)]  # nothing after 2024 is used
    (tmp_path / "roh" / "DFII10.json").write_bytes(raw + b" ")
    with pytest.raises(macro_filters.MacroDataError):
        cli.load_history(tmp_path)
