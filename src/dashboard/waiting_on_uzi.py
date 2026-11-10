"""Wartet auf Uzi: what in TIM is waiting for Uzi's decision, from TIM's own files.

Paket P6 of ``docs/MULTI_AGENTEN_SYSTEM.md`` (Uzi, 10.11.2026, "go mach alle ps fertig"). Several parts of TIM stop and
wait for Uzi: the watchdog holding its restarts (P2), a F11 filter passed and ready for his decision, the orderflow
shadow or the second opinion reaching the plan count of their judgement. Until now each sat in its own file.
This module collects them as plain German lines for the daily report (``daily_report.facts``).

Only local files are read. Nothing here calls GitHub or any network, decides, or changes a file. Open pull
requests are therefore not listed. A file that cannot be read is named as such, never left out quietly.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.dashboard import orderflow_shadow, plan_opinion
from src.research_lab.workshop import self_improve

WATCHDOG_STATE = Path("data/operational/watchdog_recovery_state.json")


def _read(path: Path) -> Mapping[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, Mapping) else None


def _watchdog(root: Path) -> list[str]:
    path = root / WATCHDOG_STATE
    if not path.is_file():
        return []
    state = _read(path)
    if state is None:
        return [f"Watchdog-Zustand {WATCHDOG_STATE} nicht lesbar."]
    if state.get("restart_hold") is True:
        since = state.get("restart_hold_since") or "unbekannt"
        return [f"Watchdog hat die Neustarts angehalten (seit {since}): Neustart-Budget verbraucht, Ursache prüfen."]
    return []


def _filters(root: Path) -> list[str]:
    try:
        events = self_improve.LearningLog(root / self_improve.LOG_PATH).events()
    except ValueError:
        return ["F11-Lernlog: Hash-Kette gebrochen, nichts davon zählt bis zur Prüfung."]
    except (OSError, AttributeError, TypeError):
        return ["F11-Lernlog nicht lesbar."]
    try:
        answered = self_improve.decided(events)
    except (AttributeError, KeyError, TypeError):
        return ["F11-Lernlog nicht lesbar."]
    latest: dict[str, Any] = {}
    for event in events:  # only the newest verdict per filter counts
        if isinstance(event, Mapping) and event.get("event") == "verdict" and event.get("filter"):
            latest[str(event["filter"])] = event.get("verdict")
    return [f"F11-Filter {name} bestanden: bereit für deine Entscheidung."
            for name, verdict in sorted(latest.items()) if verdict == "bestanden" and name not in answered]


def _judgeable(root: Path, path: Path, summary: Any, name: str) -> list[str]:
    target = root / path
    if not target.is_file():
        return []
    state = orderflow_shadow.load(target)
    try:
        figures = summary(state) if isinstance(state, Mapping) else None
    except (AttributeError, KeyError, TypeError):
        figures = None
    if not isinstance(figures, Mapping):
        return [f"{name}: Datei nicht lesbar."]
    if figures.get("judgeable"):
        return [f"{name}: {figures.get('closed')} geschlossene Pläne erreicht (Ziel {figures.get('target')}), Urteil fällig."]
    return []


def items(root: Path | str = ".") -> list[str]:
    """Everything waiting for Uzi, one line each. An empty list means nothing is waiting."""
    base = Path(root)
    return (_watchdog(base) + _filters(base)
            + _judgeable(base, orderflow_shadow.DEFAULT_PATH, orderflow_shadow.summary, "Orderflow-Schatten")
            + _judgeable(base, plan_opinion.DEFAULT_PATH, plan_opinion.summary, "Hermes-Zweitmeinung"))
