"""Macro release dates (US-CPI, FOMC) as display-only markers on the interactive chart."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dashboard.chart_live import DEFAULT_GROUPS, GROUP_NAMES, GROUP_STYLE, KlineCache, build_live_chart
from src.dashboard.macro_calendar import SCHEMA, chart_markers, load_calendar, parse_calendar
from src.dashboard.public_en import GROUPS_EN
from tests.test_chart_live import NOW, fake_fetch

UTC = timezone.utc


def _payload(*rows: dict) -> dict:
    return {"schema": SCHEMA, "events": list(rows)}


def test_parse_keeps_only_known_kinds_with_zoned_times() -> None:
    events = parse_calendar(_payload(
        {"kind": "FOMC", "time": "2024-12-18T19:00:00+00:00", "source": "fed"},
        {"kind": "CPI", "time": "2024-12-11T08:30:00-05:00"},
        {"kind": "CPI", "time": "2024-12-11T13:30:00"},  # no zone: ambiguous, dropped
        {"kind": "NFP", "time": "2024-12-06T13:30:00+00:00"},  # unknown kind
        {"kind": "CPI", "time": "kaputt"},
        "keine Zeile",
    ))
    assert [(e["kind"], e["time"]) for e in events] == [
        ("CPI", datetime(2024, 12, 11, 13, 30, tzinfo=UTC)),
        ("FOMC", datetime(2024, 12, 18, 19, 0, tzinfo=UTC)),
    ]
    assert events[0]["label"] == "US-CPI" and events[1]["source"] == "fed"


def test_wrong_schema_or_missing_file_gives_no_markers(tmp_path: Path) -> None:
    assert parse_calendar({"schema": "other", "events": [{"kind": "CPI", "time": "2024-12-11T13:30:00+00:00"}]}) == []
    assert parse_calendar(["CPI"]) == []
    assert load_calendar(tmp_path / "fehlt.json") == []
    broken = tmp_path / "kaputt.json"
    broken.write_text("{nicht json")
    assert load_calendar(broken) == []


def test_markers_snap_to_the_candle_the_release_fell_in() -> None:
    hour = 3600
    times = [int(datetime(2024, 12, 11, h, tzinfo=UTC).timestamp()) for h in range(10, 16)]  # 10:00 .. 15:00 open times
    events = parse_calendar(_payload(
        {"kind": "CPI", "time": "2024-12-11T13:30:00+00:00"},
        {"kind": "FOMC", "time": "2024-12-11T09:59:00+00:00"},  # before the first candle
        {"kind": "FOMC", "time": "2024-12-11T16:00:00+00:00"},  # at the end of the last candle: outside
        {"kind": "FOMC", "time": "2024-12-11T15:59:00+00:00"},  # inside the last, still open candle
    ))
    now = datetime(2024, 12, 11, 15, 30, tzinfo=UTC)
    markers = chart_markers(events, times, hour, now)
    assert [(m["kind"], m["time"], m["upcoming"]) for m in markers] == [
        ("CPI", times[3], False),
        ("FOMC", times[5], True),
    ]
    assert chart_markers(events, [], hour, now) == []


def test_live_chart_carries_macro_markers_as_their_own_layer() -> None:
    inside = NOW - timedelta(hours=10)
    calendar = parse_calendar(_payload({"kind": "FOMC", "time": inside.isoformat()},
                                       {"kind": "CPI", "time": (NOW - timedelta(days=400)).isoformat()}))
    model = build_live_chart("BTCUSDT", "1h", None, cache=KlineCache(fake_fetch()), now=NOW, macro=calendar)
    assert [m["kind"] for m in model["macro"]] == ["FOMC"]
    times = [c["time"] for c in model["candles"]]
    assert model["macro"][0]["time"] in times and model["macro"][0]["time"] <= int(inside.timestamp())
    assert "macro" in GROUP_NAMES and "macro" in GROUPS_EN and "macro" in GROUP_STYLE and "macro" in DEFAULT_GROUPS


def test_live_chart_reads_the_calendar_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps(_payload({"kind": "CPI", "time": (NOW - timedelta(hours=5)).isoformat()})))
    monkeypatch.setenv("TIM_MACRO_CALENDAR", str(path))
    model = build_live_chart("ETHUSDT", "1h", None, cache=KlineCache(fake_fetch()), now=NOW)
    assert [m["kind"] for m in model["macro"]] == ["CPI"]
    monkeypatch.setenv("TIM_MACRO_CALENDAR", str(tmp_path / "fehlt.json"))
    assert build_live_chart("ETHUSDT", "1h", None, cache=KlineCache(fake_fetch()), now=NOW)["macro"] == []


def test_chart_script_draws_macro_markers_only_when_the_layer_is_on() -> None:
    script = Path("src/dashboard/assets/tim_chart.js").read_text()
    assert "groups.has('macro')" in script and "model.macro" in script


def test_export_from_the_fomc_fixture_round_trips_into_chart_markers(tmp_path: Path) -> None:
    from src.research_lab.external import fomc, fomc_live
    from src.research_lab.external.macro_calendar_export import SCHEMA as EXPORT_SCHEMA, fomc_rows

    assert EXPORT_SCHEMA == SCHEMA
    bundle, _ = fomc_live.load_fixture()
    ingest = fomc.parse_fomc_bundle(bundle)
    rows = fomc_rows(ingest.events)
    assert rows and len(rows) == sum(1 for e in ingest.events if e.event_time is not None)
    path = tmp_path / "calendar.json"
    path.write_text(json.dumps({"schema": EXPORT_SCHEMA, "events": rows}))
    events = load_calendar(path)
    assert len(events) == len(rows) and all(e["kind"] == "FOMC" and e["time"].tzinfo is not None for e in events)
