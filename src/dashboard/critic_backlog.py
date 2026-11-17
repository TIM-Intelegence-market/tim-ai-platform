"""Kritik-Backlog: aus den täglichen Kritiken wird eine Liste offener Punkte mit Alter.

Uzi, 17.11.2026 ("Punkt 1 danach Punkt 2 go"). Ohne Gedächtnis wiederholt sich der Kritiker. Er schreibt seine Punkte
als Zeilen ``- [Projekt] Titel: Vorschlag`` (oder ``[Chart]``) und ``ERLEDIGT: Titel`` für Punkte, die nach den Merge-
Fakten gelöst scheinen. TIM führt die Punkte in einer eigenen Datei: gleiche Punkte werden zusammengeführt (Wortüberlappung),
das Alter zählt ab dem ersten Nennen, ein Punkt, der sieben Tage nicht mehr genannt wird, gilt als "nicht mehr genannt".
Der Kritiker bekommt die offenen Punkte am nächsten Tag zurück und entscheidet nur, ob sie noch gelten.

Nur lesend gegenüber TIM: schreibt allein ``data/hermes/critic_backlog.json``. Ob ein Punkt wirklich erledigt ist,
prüft Uzi; "erledigt" heißt hier: der Kritiker hält ihn nach den Merge-Fakten für gelöst.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from src.dashboard.daily_report import LOCAL
from src.dashboard.orderflow_shadow import _iso, _save, load

SCHEMA = "tim_critic_backlog/1"
DEFAULT_PATH = Path("data/hermes/critic_backlog.json")
KEEP = 60
STALE_DAYS = 7
MATCH = 0.6  # share of the shorter title's words that must recur for "same point"
MAX_LINES = 10
AREAS = {"projekt": "Projekt", "chart": "Chart"}
POINT = re.compile(r"^\s*[-*•]\s*\**\[(projekt|chart)\]\**\s*(.+?)\s*:\s*(.*)$", re.IGNORECASE)
DONE = re.compile(r"^\s*[-*•]?\s*\**ERLEDIGT\**\s*:\s*(.+?)\s*$", re.IGNORECASE)


def _words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß0-9]+", title.lower()) if len(w) > 3}


def same(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return a.strip().lower() == b.strip().lower()
    return len(wa & wb) / min(len(wa), len(wb)) >= MATCH


def parse(text: str) -> tuple[list[dict[str, str]], list[str]]:
    """New or repeated points and the titles the critic calls done, from the critic's answer."""
    points, done = [], []
    for raw in text.splitlines():
        line = raw.replace("**", "").strip()
        if match := DONE.match(line):
            done.append(match.group(1)[:120])
        elif match := POINT.match(line):
            points.append({"area": AREAS[match.group(1).lower()], "title": match.group(2)[:120], "proposal": match.group(3)[:300]})
    return points, done


def apply(path: Path, text: str, now: datetime) -> dict[str, int]:
    """Merge one critique into the backlog. Returns counts: added, repeated, done."""
    path = Path(path)
    state = load(path) or {"schema": SCHEMA, "points": []}
    items: list[dict[str, Any]] = state.setdefault("points", [])
    day = now.astimezone(LOCAL).strftime("%Y-%m-%d")
    points, done = parse(text)
    counts = {"added": 0, "repeated": 0, "done": 0}
    for title in done:
        for item in items:
            if item["status"] == "offen" and same(item["title"], title):
                item.update(status="erledigt", closed_at=_iso(now))
                counts["done"] += 1
                break
    for point in points:
        found = next((i for i in items if i["status"] == "offen" and i["area"] == point["area"] and same(i["title"], point["title"])), None)
        if found:
            found.update(last_seen=day, times_seen=int(found.get("times_seen", 1)) + 1, proposal=point["proposal"] or found.get("proposal", ""))
            counts["repeated"] += 1
        else:
            items.append({**point, "first_seen": day, "last_seen": day, "times_seen": 1, "status": "offen"})
            counts["added"] += 1
    for item in items:  # not named for a week: the critic dropped it by himself
        if item["status"] == "offen" and (datetime.fromisoformat(day) - datetime.fromisoformat(item["last_seen"])).days >= STALE_DAYS:
            item.update(status="nicht mehr genannt", closed_at=_iso(now))
    state["points"] = items[-KEEP:]
    _save(state, path)
    return counts


def open_points(path: Path | None, now: datetime) -> list[dict[str, Any]]:
    """Open points, oldest first, each with ``days`` since first named."""
    day = datetime.fromisoformat(now.astimezone(LOCAL).strftime("%Y-%m-%d"))
    items = [i for i in (load(Path(path or DEFAULT_PATH)) or {}).get("points") or [] if i.get("status") == "offen"]
    return sorted(({**i, "days": (day - datetime.fromisoformat(i["first_seen"])).days} for i in items), key=lambda i: -i["days"])


def lines(path: Path | None, now: datetime, limit: int = MAX_LINES) -> list[str]:
    """Open points as prompt lines for tomorrow's critic."""
    return [f"[{i['area']}] {i['title']} (offen seit {i['days']} Tag(en), {i.get('times_seen', 1)}x genannt)" for i in open_points(path, now)[:limit]]


def summary(path: Path | None, now: datetime) -> dict[str, Any]:
    stored = (load(Path(path or DEFAULT_PATH)) or {}).get("points") or []
    counts = {s: sum(1 for i in stored if i.get("status") == s) for s in ("offen", "erledigt", "nicht mehr genannt")}
    return {"open": open_points(path, now), "counts": counts}


def prompt_part(backlog_lines: Sequence[str]) -> str:
    return ("\nBacklog der offenen Punkte (deine Kritik von früher):\n" + "\n".join(f"- {line}" for line in backlog_lines)
            + "\nWiederhole einen Backlog-Punkt nur, wenn er noch gilt: dann nenne ihn mit seinem Titel in der Zeile. "
              "Scheint er nach den Merge-Fakten gelöst, schreibe 'ERLEDIGT: <Titel>'. Erfinde keine Erledigungen.")


FORMAT = ("Schreibe jeden Punkt als eigene Zeile im Format '- [Projekt] Kurztitel: Vorschlag, Begründung' beziehungsweise "
          "'- [Chart] Kurztitel: ...'.")

