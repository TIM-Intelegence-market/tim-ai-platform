"""Macro release dates (US CPI, FOMC statements) as markers on the interactive chart.

Display only: a marker says "a scheduled US release happened (or happens) here", nothing
about direction, size or any trading rule. The chart reads a small JSON file

    {"schema": "tim_macro_calendar/1", "events": [
        {"kind": "CPI", "time": "2024-12-11T13:30:00+00:00", "label": "US-CPI", "source": "..."},
        {"kind": "FOMC", "time": "2024-12-18T19:00:00+00:00", "label": "FOMC", "source": "..."}]}

from ``TIM_MACRO_CALENDAR`` or ``data/macro/calendar.json`` (relative to the runtime's
working directory). A missing or unreadable file means no markers, never an error.

Past dates come from the research lab's point-in-time data (FOMC statements V1.2,
ALFRED CPI V1.1): ``python -m src.research_lab.external.macro_calendar_export --cpi-bundle ID
--fomc-bundle ID``. The research lab writes the file, the dashboard only reads it, so the
FOMC modules stay inside the research lab. Only release instants that the source documents
are used; nothing is guessed. Upcoming dates are not fetched yet: they can be added to the file by hand
(``kind``, ``time`` in UTC, ``source``) until a calendar source is wired in.
"""
from __future__ import annotations

import json
import os
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "tim_macro_calendar/1"
DEFAULT_PATH = Path("data/macro/calendar.json")
ENV_PATH = "TIM_MACRO_CALENDAR"
KINDS = {"CPI": "US-CPI", "FOMC": "FOMC"}
MAX_EVENTS = 5000


def calendar_path() -> Path:
    return Path(os.environ.get(ENV_PATH) or DEFAULT_PATH)


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None  # a release time without zone is ambiguous: skip it
    return moment.astimezone(timezone.utc)


def parse_calendar(payload: Any) -> list[dict[str, Any]]:
    """Valid events sorted by time; rows with an unknown kind or without a zoned time are dropped."""
    if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA or not isinstance(payload.get("events"), list):
        return []
    events = []
    for row in payload["events"][:MAX_EVENTS]:
        if not isinstance(row, Mapping) or row.get("kind") not in KINDS:
            continue
        moment = _instant(row.get("time"))
        if moment is None:
            continue
        label = row.get("label") if isinstance(row.get("label"), str) and row.get("label") else KINDS[row["kind"]]
        source = row.get("source") if isinstance(row.get("source"), str) else ""
        events.append({"kind": row["kind"], "time": moment, "label": label[:40], "source": source[:200]})
    events.sort(key=lambda e: (e["time"], e["kind"]))
    return events


def load_calendar(path: Path | None = None) -> list[dict[str, Any]]:
    try:
        return parse_calendar(json.loads((path or calendar_path()).read_text()))
    except (OSError, ValueError):
        return []


def chart_markers(events: Sequence[Mapping[str, Any]], times: Sequence[int], interval_seconds: int, now: datetime) -> list[dict[str, Any]]:
    """Markers for the candles on screen: each event snaps to the candle it falls in.

    ``times`` are candle open times (epoch seconds, ascending). Events before the first
    candle or after the last candle's end are left out."""
    if not times:
        return []
    first, end = times[0], times[-1] + interval_seconds
    markers = []
    for event in events:
        moment = int(event["time"].timestamp())
        if moment < first or moment >= end:
            continue
        markers.append({"time": times[bisect_right(times, moment) - 1], "kind": event["kind"], "label": event["label"],
                        "at": event["time"].isoformat(), "upcoming": event["time"] > now})
    return markers
