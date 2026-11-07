"""Shadow journal of the MID plan journal: last third as a runner (src/dashboard/exit_shadow.py)."""
from __future__ import annotations

import json
from datetime import timedelta

from src.dashboard import exit_shadow as shadow
from src.dashboard.plan_journal import SCHEMA
from src.research_lab import exit_variants as ev
from tests.test_research_lab_exit_variants import PATH, T0, candles_for, long_entry


def series_until(candles: list[dict], end) -> dict:
    shown = [c for c in candles if c["close_time"] <= end]
    iso = lambda rows, tf: [{**c, "timeframe": tf, "open_time": c["open_time"].isoformat(), "close_time": c["close_time"].isoformat()} for c in rows]  # noqa: E731
    return {"1m": iso(shown[-500:], "1m"), "15m": iso(ev.aggregate(shown, "15m"), "15m"), "1h": iso(ev.aggregate(shown, "1h"), "1h")}


def write_journal(path, entry) -> None:
    path.write_text(json.dumps({"schema": SCHEMA, "entries": [{**entry, "symbol": "BTCUSDT"}]}))


def test_shadow_is_resumable_and_matches_one_pass(tmp_path) -> None:
    candles = candles_for(PATH + [112, 106, 100, 96, 95, 94])
    entry = long_entry(candles)
    journal, out = tmp_path / "mid.json", tmp_path / "shadow.json"
    write_journal(journal, {**entry, "status": "FILLED"})
    shadow.update(out, journal, series_until(candles, T0), now=T0)  # starts before the TP2 hit
    middle = T0 + timedelta(minutes=150)
    shadow.update(out, journal, series_until(candles, middle), now=middle)
    state = shadow.update(out, journal, series_until(candles, candles[-1]["close_time"]), now=candles[-1]["close_time"])
    plan, higher = ev.aggregate(candles, "15m"), ev.aggregate(candles, "1h")
    run = state["runs"]["x"]["variants"]
    for name in ev.VARIANTS:
        once = ev.follow_rest(entry, candles, plan, higher, name)
        assert (run[name]["exit_reason"], run[name]["exit_price"]) == (once["exit_reason"], once["exit_price"]), name
        assert "data_gap" not in run[name]
    summary = state["summary"]
    assert summary["LAEUFER"]["closed"] == 1 and summary["LAEUFER"]["vs_fest"] > 0
    assert summary["FEST"]["vs_fest"] == 0


def test_shadow_only_counts_tp2_after_start_and_never_writes_the_journal(tmp_path) -> None:
    candles = candles_for(PATH)
    journal, out = tmp_path / "mid.json", tmp_path / "shadow.json"
    write_journal(journal, long_entry(candles))
    before = journal.read_text()
    end = candles[-1]["close_time"]
    state = shadow.update(out, journal, series_until(candles, end), now=end)
    assert state["runs"] == {} and journal.read_text() == before


def test_shadow_uses_spot_delta_and_notes_gaps(tmp_path) -> None:
    candles = candles_for(PATH)
    journal, out = tmp_path / "mid.json", tmp_path / "shadow.json"
    write_journal(journal, long_entry(candles))
    rows = [[int(c["open_time"].timestamp()), 100.0, 0.0, 5.0] for c in candles]
    spot = {"symbol": "BTCUSDT", "days": {"2026-11-04": rows}}
    shadow.update(out, journal, series_until(candles, T0), now=T0)
    late = candles[-1]["close_time"]
    gapped = series_until(candles, late)
    gapped["1m"] = gapped["1m"][-150:]  # the runtime was down: the first minutes after TP2 are gone
    state = shadow.update(out, journal, gapped, spot=spot, now=late)
    run = state["runs"]["x"]["variants"]["OF_LAEUFER"]
    assert run["data_gap"].startswith("1m-Kerzen fehlen")
    shadow.update(tmp_path / "s2.json", journal, series_until(candles, T0), now=T0)
    state = shadow.update(tmp_path / "s2.json", journal, series_until(candles, late), spot=spot, now=late)
    assert state["runs"]["x"]["variants"]["OF_LAEUFER"]["of_verdict"] is True


def test_weekly_report_shows_the_shadow() -> None:
    from datetime import datetime, timezone

    from src.research_lab.workshop import weekly_report

    state = {"runs": {}}
    state["summary"] = shadow.summary(state)
    week = weekly_report.build({}, {"filters": {}}, [], datetime(2026, 11, 8, tzinfo=timezone.utc), state)
    text = weekly_report.render(week)
    assert "Schatten-Journal Läufer (MID 1h): 0 von 30 Trades mit TP2" in text
    assert "Schatten-Journal" not in weekly_report.render(weekly_report.build({}, {"filters": {}}, [], datetime(2026, 11, 8, tzinfo=timezone.utc)))
