"""Überblick: one page that shows what exists in TIM and what is new (Uzi, 14.11.2026).

"Wenn ich was Neues baue, ist es nicht drauf." Nothing here is kept by hand. The page reads three things that
already change whenever something is built:

* the git history of the checkout (merged pull requests of the last days),
* the study files in ``docs/research_lab/studien`` and the logbook ``LOGBUCH.json`` (a study file without a
  logbook entry is listed as such, so a new study cannot go unseen),
* the Mac and issue-worker state (``build_mac``) and the list of what waits for Uzi.

Display only: nothing is written, started or stopped. A source that fails turns into a grey tile with its reason.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.dashboard.cockpit.areas import (LOGBOOK_PATH, LOGBOOK_STATUS, _cell, _info, _logbook_data, _model, _safe_sections,
                                         _section, _text)
from src.dashboard.cockpit.mac import build_mac
from src.dashboard.cockpit.sources import BudgetedSources
from src.dashboard.cockpit.tiles import Tile, make_tile, unavailable
from src.dashboard.state import DashboardState

ROOT = Path(__file__).resolve().parents[3]
STUDY_DIR = Path("docs/research_lab/studien")
NEW_DAYS = 7
NEW_ROWS = 20
GIT_TIMEOUT = 4.0
STUDY_ID = re.compile(r"^(S\d+[A-Z]?|OF\d+|OFX|K\d+|KI\d+|L\d+|GEX)(?=_)")
MERGE = re.compile(r"^Merge pull request #(\d+) from \S+$")

_SOURCES = BudgetedSources()


def merged_prs(root: Path, now: datetime, days: int = NEW_DAYS) -> list[dict[str, str]]:
    """Merged pull requests of the last ``days`` days, newest first (title = first line of the merge body)."""
    since = f"{days}.days.ago"
    out = subprocess.run(
        ["git", "-C", str(root), "log", "--first-parent", f"--since={since}", "--pretty=format:%cI%x1f%s%x1f%b%x1e"],
        capture_output=True, text=True, timeout=GIT_TIMEOUT, check=True).stdout
    rows = []
    for record in out.split("\x1e"):
        parts = record.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        when, subject, body = parts[0], parts[1], parts[2]
        match = MERGE.match(subject.strip())
        if not match:
            continue
        title = next((line.strip() for line in body.splitlines() if line.strip()), subject)
        rows.append({"when": when.strip(), "pr": match.group(1), "title": title})
    return rows


def _local(value: str) -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.fromisoformat(value).astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m. %H:%M")
    except ValueError:
        return value


def _new_section(root: Path, now: datetime) -> dict[str, Any]:
    try:
        prs = merged_prs(root, now)
    except (OSError, subprocess.SubprocessError) as exc:
        return _section("new", "Neu gebaut", [unavailable("new", "Neu gebaut", f"Git-Verlauf nicht lesbar: {type(exc).__name__}", "git log")])
    tile = _info(make_tile("merged", f"Gemergt in {NEW_DAYS} Tagen", str(len(prs)), state="ok", source="git log --first-parent", now=now))
    rows = [[_cell(_local(p["when"])), _cell(f"#{p['pr']}"), {"text": _text(p["title"], 200), "href": ""}] for p in prs[:NEW_ROWS]]
    return _section("new", "Neu gebaut", [tile], table={"head": ["Wann", "PR", "Was"], "rows": rows},
                    note="Aus dem Git-Verlauf dieses Rechners: sobald ein PR gemergt und nachgezogen ist, steht er hier. Nichts davon wird von Hand gepflegt.",
                    empty="Keine gemergten PRs in diesem Zeitraum.")


def _studies_section(root: Path, now: datetime) -> dict[str, Any]:
    entries = _logbook_data(root / LOGBOOK_PATH)
    logged = {str(e.get("id")) for e in entries}
    files: dict[str, list[str]] = {}
    for path in sorted((root / STUDY_DIR).glob("*")):
        match = STUDY_ID.match(path.name)
        if match:
            files.setdefault(match.group(1), []).append(path.name)
    missing = {sid: names for sid, names in files.items() if sid not in logged}
    counts: dict[str, int] = {}
    for entry in entries:
        label = LOGBOOK_STATUS.get(str(entry.get("status")), (str(entry.get("status") or "—"), "unknown"))[0]
        counts[label] = counts.get(label, 0) + 1
    tiles = [_info(make_tile(f"st_{i}", label, str(n), state="ok", source=str(LOGBOOK_PATH), now=now, href="/forschung"))
             for i, (label, n) in enumerate(sorted(counts.items()))]
    tiles.append(make_tile("unlogged", "Studien ohne Logbuch-Eintrag", str(len(missing)), state="warn" if missing else "ok",
                           reason="Datei in studien/ vorhanden, aber nicht im Logbuch" if missing else "", source=str(STUDY_DIR), now=now))
    rows = [[_cell(sid), {"text": _text(", ".join(names), 240), "href": ""},
             {"text": "Entwurf" if any("ENTWURF" in n for n in names) else "ohne Logbuch-Eintrag", "href": ""}]
            for sid, names in sorted(missing.items())]
    return _section("studies", "Studien", tiles, table={"head": ["Studie", "Dateien", "Stand"], "rows": rows},
                    note="Zählung aus dem Forschungs-Logbuch. Neue Studiendateien ohne Logbuch-Eintrag stehen unten in der Tabelle, damit keine unbemerkt bleibt.")


def _mac_section(state: DashboardState, now: datetime) -> dict[str, Any]:
    model = build_mac(state, now)
    tiles = [Tile(id=f"mac_{i}", label=str(line["label"]), value=str(line["value"]), state=str(line["state"]) if line["state"] in
                  {"ok", "warn", "fail", "unknown"} else "unknown", reason="" if line["state"] == "ok" else str(line.get("detail") or ""),
                  source="Mac & Worker", as_of=line.get("as_of"), age_seconds=line.get("age_seconds"),
                  detail=str(line.get("detail") or "") if line["state"] == "ok" else "", href="/neu/mac")
             for i, line in enumerate(model["now"])]
    return _section("mac", "Mac und Worker", tiles or [unavailable("mac", "Mac und Worker", "Keine Daten vom Worker", "build_mac", "/neu/mac")],
                    note=f"{model['headline']}. Einzelheiten unter „Mac jetzt“.")


def _waiting_section(root: Path, now: datetime) -> dict[str, Any]:
    from src.dashboard import waiting_on_uzi

    lines = waiting_on_uzi.items(root)
    tiles = [make_tile(f"wait_{i}", "Wartet auf dich", line, state="warn", reason=line, source="waiting_on_uzi", now=now)
             for i, line in enumerate(lines)]
    return _section("waiting", "Wartet auf dich", tiles, empty="Nichts wartet auf eine Entscheidung (offene PRs stehen hier nicht, siehe „Neu gebaut“ und GitHub).")


def build_ueberblick(state: DashboardState, now: datetime | None = None, root: Path | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    base = root or ROOT
    sections = _safe_sections([
        ("waiting", "Wartet auf dich", lambda: _waiting_section(base, now)),
        ("new", "Neu gebaut", lambda: _new_section(base, now)),
        ("studies", "Studien", lambda: _studies_section(base, now)),
        ("mac", "Mac und Worker", lambda: _mac_section(state, now)),
    ])
    return _model("ueberblick", "Überblick", sections, {}, now)
