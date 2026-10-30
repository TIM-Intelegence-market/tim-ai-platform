"""Plan notes: one line from the trader for each plan TIM wrote down.

The plan journals record what TIM would do. They do not record what the
trader did with it. A note closes that loop: for every plan the trader says
whether he took it, skipped it or only watched it, and why. Without that line
a negative journal result cannot be explained.

Paper and self-report only: a note never changes a plan, a stop or a count.
Every save appends; the newest note for a plan counts, older ones stay as
history.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "tim_plan_notes/1"
SOURCE = "Trader-Eingabe im Control Center (Journal), nur Papier"
DECISIONS = {"TAKEN": "genommen", "SKIPPED": "nicht genommen", "WATCHED": "nur beobachtet"}
MIN_REASON = 5
MAX_REASON = 500
MAX_NOTES = 20000
OPEN_DAYS = 7  # plans older than this no longer ask for a note
_PLAN_ID = re.compile(r"[0-9a-f]{12}")
_LOCK = threading.Lock()


class NoteError(ValueError):
    """Invalid trader input; the message is shown on the page."""


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_log() -> dict[str, Any]:
    return {"schema": SCHEMA, "source": SOURCE, "notes": []}


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_log()
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not isinstance(data.get("notes"), list):
        return empty_log()
    return data


def save(log: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(log, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def key(rule: Any, plan_id: Any) -> str:
    """Plans are unique per journal rule; the same id may exist in two rules."""
    return f"{rule}|{plan_id}"


def latest(log: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The newest note per (rule, plan id)."""
    out: dict[str, dict[str, Any]] = {}
    for note in log.get("notes") or []:
        if isinstance(note, dict) and note.get("plan_id"):
            out[key(note.get("rule"), note["plan_id"])] = note
    return out


def add_note(path: Path, form: Mapping[str, str], known: Iterable[str], now: datetime | None = None) -> dict[str, Any]:
    """``known`` holds ``key(rule, id)`` of every plan in the journals."""
    plan_id = str(form.get("plan_id") or "").strip()
    rule = str(form.get("rule") or "").strip()[:40]
    decision = str(form.get("decision") or "").strip().upper()
    reason = " ".join(str(form.get("reason") or "").split())
    if not _PLAN_ID.fullmatch(plan_id) or key(rule, plan_id) not in set(known):
        raise NoteError("Diesen Plan gibt es im Journal nicht.")
    if decision not in DECISIONS:
        raise NoteError("Bitte wählen: genommen, nicht genommen oder nur beobachtet.")
    if len(reason) < MIN_REASON:
        raise NoteError(f"Bitte kurz begründen (mindestens {MIN_REASON} Zeichen).")
    if len(reason) > MAX_REASON:
        raise NoteError(f"Die Begründung ist zu lang (höchstens {MAX_REASON} Zeichen).")
    now = now or datetime.now(timezone.utc)
    with _LOCK:
        log = load(path)
        notes = log["notes"]
        if len(notes) >= MAX_NOTES:
            raise NoteError(f"Log voll ({MAX_NOTES} Notizen).")
        note = {"id": f"PN-{len(notes) + 1:05d}", "plan_id": plan_id, "rule": rule, "decision": decision,
                "reason": reason, "created_at": _iso(now)}
        notes.append(note)
        log["updated_at"] = note["created_at"]
        save(log, path)
    return note


def _parse(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def missing(entries: Iterable[Mapping[str, Any]], rule: str, notes: Mapping[str, Any], now: datetime | None = None,
            days: int = OPEN_DAYS) -> list[Mapping[str, Any]]:
    """Counted plans of the last ``days`` days that have no note yet, newest first."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    out = []
    for entry in entries:
        created = _parse(entry.get("created_at"))
        if entry.get("excluded") or created is None or created < since:
            continue
        if key(rule, entry.get("id")) not in notes:
            out.append(entry)
    return sorted(out, key=lambda e: str(e.get("created_at")), reverse=True)
