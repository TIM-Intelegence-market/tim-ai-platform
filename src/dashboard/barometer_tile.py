"""Macro barometer tile for the Control Center, read-only.

Reads the summary the weekly barometer writes next to its Markdown
(``python -m src.research_lab.forward.macro_filters barometer``, file ``barometer_latest.json``).
It shows how many drivers are tailwind or headwind for BTC by their history up to 2024 and the next
scheduled release. Descriptive only: nothing here is a signal or reaches a trade.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.dashboard.cockpit.tiles import Tile, make_tile

ENV_PATH = "TIM_BAROMETER_JSON"
DEFAULT_PATH = Path("data/research/forward/S7b-makro/barometer/barometer_latest.json")
MAX_AGE_SECONDS = 8 * 86400  # weekly run on Mondays plus a day of slack
HREF = "/prep"
LOCAL = ZoneInfo("Europe/Berlin")
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def barometer_path() -> Path:
    return Path(os.environ.get(ENV_PATH) or DEFAULT_PATH)


def load(path: Path | None = None) -> dict[str, Any] | None:
    try:
        value = json.loads((path or barometer_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("schema") == "tim_barometer/1" else None


def _when(iso: str) -> str:
    moment = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(LOCAL)
    return f"{WEEKDAYS[moment.weekday()]} {moment:%d.%m. %H:%M}"


def tile(summary: Mapping[str, Any] | None, now: datetime | None = None) -> Tile:
    now = now or datetime.now(timezone.utc)
    if not summary:
        return make_tile("barometer", "Makro-Barometer", "—", state="unknown",
                         reason="Noch kein Barometer mit Zusammenfassung geschrieben (läuft montags)",
                         source=str(barometer_path()), href=HREF, now=now, extra={"kind": "info"})
    tail, head = int(summary.get("rueckenwind") or 0), int(summary.get("gegenwind") or 0)
    events = summary.get("termine") or []
    detail = ", ".join(f"{d['label']} {d['richtung']}" for d in summary.get("treiber") or [] if d.get("wind") == "Gegenwind")
    detail = f"Gegenwind: {detail}" if detail else "Kein Treiber mit Gegenwind"
    if events:
        detail += f" · nächster Termin: {events[0]['label']} {_when(events[0]['time'])}"
    return make_tile("barometer", "Makro-Barometer", f"{tail} Rückenwind · {head} Gegenwind", "PASS",
                     source=str(barometer_path()), as_of=summary.get("erstellt_utc"), max_age_seconds=MAX_AGE_SECONDS,
                     detail=detail, href=HREF, now=now,
                     extra={"kind": "info", "hinweis": summary.get("hinweis"), "termine": events[:3]})
