"""Idea queue (F1): append-only JSON lines with a hash chain.

Every idea and every status change is one line. Old lines are never edited; an
edit breaks the chain and every later read fails. The same hypothesis cannot be
added twice, and an imported proposal (same ``source_ref``) is added only once.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.research_lab.workshop import charter

GENESIS = "0" * 64
DEFAULT_PATH = Path("docs/research_lab/IDEEN.jsonl")
SCHEMA = "tim_research_ideas/1"

STATUSES = {
    "new": "neu",
    "ready": "bereit für Studien-Entwurf",
    "already_tested": "schon getestet",
    "holdout_locked": "bräuchte den Holdout 2025 (gesperrt)",
    "waiting_data": "wartet auf Daten",
    "waiting_budget": "wartet auf Budget",
    "study_draft": "Studien-Entwurf angelegt",
    "rejected": "abgelehnt",
    "withdrawn": "zurückgezogen",
}
# Only a person may close an idea for good.
HUMAN_ONLY = {"rejected"}


class IdeaError(ValueError):
    pass


def _digest(previous: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode()).hexdigest()


def normalize(text: str) -> str:
    return " ".join(re.findall(r"[0-9a-zäöüß]+", text.lower()))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class IdeaQueue:
    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self.path = Path(path)

    # --- reading -------------------------------------------------------------------------
    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        previous = GENESIS
        for number, event in enumerate(events, 1):
            body = {k: v for k, v in event.items() if k != "hash"}
            if body.get("previous") != previous or event.get("hash") != _digest(previous, body):
                raise IdeaError(f"Hash-Kette in {self.path} bricht in Zeile {number}: die Datei wurde bearbeitet")
            previous = event["hash"]
        return events

    def ideas(self) -> dict[str, dict[str, Any]]:
        """Current state of each idea: the add line plus its latest status and history."""
        result: dict[str, dict[str, Any]] = {}
        for event in self.events():
            if event["kind"] == "add":
                result[event["id"]] = {**event["idea"], "id": event["id"], "created_at": event["at"],
                                       "status": "new", "reasons": [], "history": [("new", event["at"])]}
            elif event["kind"] == "status":
                idea = result[event["id"]]
                idea["status"], idea["reasons"] = event["status"], event.get("reasons", [])
                idea["history"].append((event["status"], event["at"]))
        return result

    # --- writing -------------------------------------------------------------------------
    def _append(self, body: dict[str, Any]) -> dict[str, Any]:
        events = self.events()
        previous = events[-1]["hash"] if events else GENESIS
        body = {**body, "schema": SCHEMA, "charter": charter.CHARTER_VERSION, "previous": previous}
        event = {**body, "hash": _digest(previous, body)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")
        return event

    def add(self, *, source: str, title: str, hypothesis: str, data: Iterable[str] = (), tags: Iterable[str] = (),
            template: str | None = None, period: tuple[str, str] | None = None, derived_from: str | None = None,
            counterargument: str = "", source_ref: str | None = None, at: str | None = None) -> str | None:
        """Adds an idea and returns its id. Returns None if ``source_ref`` was already imported."""
        if source not in charter.SOURCES:
            raise IdeaError(f"Unbekannte Quelle {source!r}; erlaubt: {sorted(charter.SOURCES)}")
        if not title.strip() or not hypothesis.strip():
            raise IdeaError("Titel und Hypothese sind Pflicht")
        if template is not None and template not in charter.TEMPLATES:
            raise IdeaError(f"Unbekannte Vorlage {template!r}; erlaubt: {sorted(charter.TEMPLATES)}")
        if period is not None:
            start, end = (date.fromisoformat(p) for p in period)
            if end < start:
                raise IdeaError("Zeitraum endet vor seinem Beginn")
        at = at or _now()
        known = self.ideas()
        if source_ref and any(i.get("source_ref") == source_ref for i in known.values()):
            return None
        key = normalize(hypothesis)
        twin = next((i for i in known.values() if normalize(i["hypothesis"]) == key), None)
        if twin:
            raise IdeaError(f"Dieselbe Hypothese steht schon als {twin['id']} in der Liste")
        if source == "ki_runde":
            if not counterargument.strip():
                raise IdeaError("Eine Idee der KI-Runde braucht ein Gegenargument")
            week = _iso_week(at)
            same_week = [i for i in known.values() if i["source"] == "ki_runde" and _iso_week(i["created_at"]) == week]
            if len(same_week) >= charter.KI_IDEAS_PER_WEEK:
                raise IdeaError(f"KI-Runde hat in Woche {week} schon {len(same_week)} Ideen (Grenze {charter.KI_IDEAS_PER_WEEK})")
        idea_id = f"I-{len(known) + 1:04d}"
        idea = {"source": source, "title": title.strip(), "hypothesis": hypothesis.strip(),
                "data": sorted(set(data)), "tags": sorted({t.strip().lower() for t in tags if t.strip()}),
                "template": template, "period": list(period) if period else None,
                "derived_from": derived_from, "counterargument": counterargument.strip(), "source_ref": source_ref}
        self._append({"kind": "add", "id": idea_id, "at": at, "idea": idea})
        return idea_id

    def set_status(self, idea_id: str, status: str, reasons: Iterable[str] = (), *, by: str = "tim",
                   at: str | None = None) -> None:
        known = self.ideas()
        if idea_id not in known:
            raise IdeaError(f"{idea_id} steht nicht in der Liste")
        if status not in STATUSES:
            raise IdeaError(f"Unbekannter Status {status!r}")
        if status in HUMAN_ONLY and by != "uzi":
            raise IdeaError(f"Status {status!r} setzt nur Uzi")
        if known[idea_id]["status"] in HUMAN_ONLY | {"study_draft", "withdrawn"}:
            raise IdeaError(f"{idea_id} ist abgeschlossen ({known[idea_id]['status']})")
        self._append({"kind": "status", "id": idea_id, "at": at or _now(), "status": status,
                      "reasons": list(reasons), "by": by})


def _iso_week(timestamp: str) -> str:
    year, week, _ = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).isocalendar()
    return f"{year}-W{week:02d}"
