"""Reports, logbook and monthly reflection (F5).

``report_from_bundle`` turns a verified result bundle into a study report and
one logbook entry. Every study ends there, also a failed or untestable one,
and the lesson is mandatory. ``monthly_reflection`` looks at the research
itself: where ideas came from, what became of them, what blocked them, which
lessons repeat in the paper trades, and how many trading edges after costs
were found. It proposes at most three things; it decides nothing.

Result contract: a study writes ``out/result.json`` into its bundle with
``status`` (one of RESULT_STATUSES), ``result`` (text), ``lesson`` (text) and
optional ``metrics`` (dict) and ``edge`` (true only for a trading edge after
costs that passed its pre-registered test).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from src.research_lab.workshop import charter
from src.research_lab.workshop.check import DATA_CATALOGUE
from src.research_lab.workshop.ideas import STATUSES as IDEA_STATUSES, IdeaQueue
from src.research_lab.workshop.runner import JobError, verify_bundle

LOGBOOK_PATH = Path("docs/research_lab/LOGBUCH.json")
REPORTS_DIR = Path("docs/research_lab/reports")
RESULT_STATUSES = {"confirmed", "candidate", "failed", "not_testable", "waiting", "aborted"}
STATUS_WORDS = {"running": "läuft", "waiting": "wartet auf Daten", "confirmed": "bestätigt",
                "candidate": "Kandidat", "failed": "nicht bestanden", "not_testable": "nicht testbar",
                "aborted": "abgebrochen"}


class ReportError(ValueError):
    pass


def _local(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(ZoneInfo(charter.LOCAL_TIMEZONE))


def read_result(bundle_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        manifest = verify_bundle(bundle_dir)
    except JobError as error:
        raise ReportError(str(error)) from error
    if manifest["exit_code"] != 0:
        raise ReportError(f"{manifest['job']}: Lauf endete mit Exit {manifest['exit_code']}; kein Urteil, Logbuch unverändert")
    path = bundle_dir / "out" / "result.json"
    if not path.exists():
        raise ReportError(f"{manifest['job']}: out/result.json fehlt (Ergebnisvertrag in report.py)")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") not in RESULT_STATUSES:
        raise ReportError(f"Status {result.get('status')!r} unbekannt; erlaubt: {sorted(RESULT_STATUSES)}")
    for field in ("result", "lesson"):
        if not str(result.get(field) or "").strip():
            raise ReportError(f"Pflichtfeld {field!r} im Ergebnis fehlt (auch ein Nullergebnis braucht eine Lehre)")
    if result.get("edge") and result["status"] != "confirmed":
        raise ReportError("edge = true nur bei bestätigtem Ergebnis")
    return manifest, result


def render_report(manifest: Mapping[str, Any], result: Mapping[str, Any], *, title: str, draft: str | None) -> str:
    finished = _local(manifest["finished_at"]).strftime("%Y-%m-%d %H:%M")
    lines = [f"# {manifest['study']}: {title} – Bericht", "",
             "| Feld | Wert |", "|---|---|",
             f"| Ergebnis | **{STATUS_WORDS[result['status']]}** |",
             f"| Auftrag | {manifest['job']}, fertig {finished} Ortszeit auf {manifest['host']} |",
             f"| Code | Commit `{manifest['commit']}` |",
             f"| Befehl | `{' '.join(manifest['command'])}` |",
             f"| Inhalts-Hash | `{manifest['content_hash']}` |"]
    if draft:
        lines.append(f"| Präregistrierung | `{draft}` |")
    lines += ["", "## Ergebnis", "", str(result["result"]), "", "## Lehre", "", str(result["lesson"]), ""]
    if result.get("metrics"):
        lines += ["## Kennzahlen", "", "| Kennzahl | Wert |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in sorted(result["metrics"].items())]
        lines.append("")
    lines += ["## Eingaben und Ausgaben", "", "| Datei | SHA-256 |", "|---|---|"]
    lines += [f"| in: {k} | `{v[:16]}…` |" for k, v in sorted(manifest["inputs"].items())]
    lines += [f"| out: {k} | `{v[:16]}…` |" for k, v in sorted(manifest["outputs"].items())]
    lines += ["", "Erzeugt von `src/research_lab/workshop/report.py` aus dem geprüften Bündel. "
              "Holdout ab 2025-01-01 nicht geladen; keine Regel, kein Risiko und kein Kostenmodell geändert.", ""]
    return "\n".join(lines)


def update_logbook(path: Path, entry: Mapping[str, Any], *, today: str) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = [e for e in data["entries"] if e.get("id") != entry["id"]]
    old = next((e for e in data["entries"] if e.get("id") == entry["id"]), {})
    merged = {**old, **entry, "started": old.get("started") or entry.get("started")}
    data["entries"] = [merged, *entries]
    data["updated"] = today
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def report_from_bundle(bundle_dir: Path, *, title: str, draft: str | None = None, logbook: Path = LOGBOOK_PATH,
                       reports_dir: Path = REPORTS_DIR, started: str | None = None) -> Path:
    manifest, result = read_result(bundle_dir)
    finished = _local(manifest["finished_at"])
    report = reports_dir / f"{manifest['study'].lower()}_{manifest['job'].lower()}_{finished:%Y-%m-%dT%H%M}.md"
    if report.exists():
        raise ReportError(f"{report} gibt es schon")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(manifest, result, title=title, draft=draft), encoding="utf-8")
    entry = {"id": manifest["study"], "title": title, "started": started or finished.date().isoformat(),
             "status": result["status"], "result": str(result["result"]), "lesson": str(result["lesson"]),
             "doc": report.as_posix(), "bundle": manifest["content_hash"]}
    if result.get("edge"):
        entry["edge"] = True
    update_logbook(logbook, entry, today=finished.date().isoformat())
    return report


# --- monthly reflection --------------------------------------------------------------------------
def _in_month(timestamp: str | None, month: str) -> bool:
    return bool(timestamp) and _local(timestamp).strftime("%Y-%m") == month


def monthly_reflection(month: str, *, queue: IdeaQueue, logbook: Iterable[Mapping[str, Any]],
                       trade_records: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    ideas = list(queue.ideas().values())
    entries = list(logbook)
    new = [i for i in ideas if _in_month(i["created_at"], month)]
    by_source = Counter(i["source"] for i in new)
    statuses = Counter(i["status"] for i in ideas)
    drafts = [i for i in ideas for s, at in i["history"] if s == "study_draft" and _in_month(at, month)]
    study_source = {i["reasons"][0].split(":")[0]: i["source"] for i in ideas
                    if i["status"] == "study_draft" and i["reasons"]}
    outcomes: dict[str, Counter] = defaultdict(Counter)
    for entry in entries:
        if entry.get("id") in study_source:
            outcomes[study_source[entry["id"]]][entry.get("status")] += 1
    waiting_data = Counter(d for i in ideas if i["status"] == "waiting_data" for d in i.get("data") or []
                           if d in DATA_CATALOGUE and not DATA_CATALOGUE[d].ready)
    edges = [e["id"] for e in entries if e.get("edge")]
    confirmed = [e["id"] for e in entries if e.get("status") == "confirmed"]
    records = list(trade_records)
    lessons = Counter(lesson for r in records for lesson in r.get("lessons") or [] if lesson != "FULL_TARGET")
    proposals = []
    for data, count in waiting_data.most_common(1):
        proposals.append(f"Daten „{DATA_CATALOGUE[data].label}“ würden {count} wartende Idee(n) freischalten "
                         f"({DATA_CATALOGUE[data].note}).")
    for source, count in sorted(by_source.items()):
        mine = [i for i in new if i["source"] == source]
        useless = sum(i["status"] in {"already_tested", "holdout_locked"} for i in mine)
        if count >= 3 and useless == count:
            proposals.append(f"Quelle „{charter.SOURCES[source]}“ brachte {count} Ideen, alle schon getestet oder gesperrt: "
                             "Quelle prüfen oder Hinweis an die Quelle.")
            break
    if records and lessons:
        lesson, count = lessons.most_common(1)[0]
        if count / len(records) >= 0.3:
            from src.research_lab.workshop.trade_reflection import LESSONS
            proposals.append(f"Häufigste Lehre der Papier-Trades: {LESSONS[lesson]} ({count} von {len(records)} Trades).")
    return {
        "month": month, "charter": charter.CHARTER_VERSION, "stage": charter.STAGE,
        "ideas_new": len(new), "ideas_by_source": dict(sorted(by_source.items())),
        "ideas_by_status": dict(sorted(statuses.items())), "drafts": len(drafts),
        "budget": charter.MONTHLY_STUDY_BUDGET, "source_outcomes": {k: dict(v) for k, v in sorted(outcomes.items())},
        "studies_by_status": dict(sorted(Counter(e.get("status") for e in entries).items())),
        "confirmed": confirmed, "edges_after_costs": edges,
        "trades_reflected": len(records), "trade_lessons": dict(sorted(lessons.items())),
        "proposals": proposals[:3], "automatic_rule_change": False,
    }


def render_reflection(data: Mapping[str, Any]) -> str:
    lines = [f"# Forschung im {data['month']}: Monats-Reflexion", "",
             f"Satzung {data['charter']}, Stufe {data['stage']}. Nur Bericht: nichts hier ändert eine Regel.", "",
             "## Ehrliche Zahl", "",
             f"- Handelsvorteile nach Kosten belegt: **{len(data['edges_after_costs'])}**"
             + (f" ({', '.join(data['edges_after_costs'])})" if data["edges_after_costs"] else ""),
             f"- Bestätigte Ergebnisse insgesamt (auch Markteffekte ohne Handelsregel): {', '.join(data['confirmed']) or 'keine'}",
             "", "## Ideen", "",
             f"- Neu im Monat: {data['ideas_new']}; Studien-Entwürfe: {data['drafts']} von {data['budget']} (Budget)"]
    for source, count in data["ideas_by_source"].items():
        lines.append(f"- {charter.SOURCES.get(source, source)}: {count}")
    lines += ["", "Stand aller Ideen: " + ", ".join(f"{IDEA_STATUSES.get(k, k)} {v}" for k, v in data["ideas_by_status"].items()) if data["ideas_by_status"] else "Noch keine Ideen.", ""]
    if data["source_outcomes"]:
        lines += ["## Was aus den Quellen wurde", ""]
        lines += [f"- {charter.SOURCES.get(s, s)}: " + ", ".join(f"{STATUS_WORDS.get(k, k)} {v}" for k, v in o.items())
                  for s, o in data["source_outcomes"].items()]
        lines.append("")
    lines += ["## Studien", "", ", ".join(f"{STATUS_WORDS.get(k, k)} {v}" for k, v in data["studies_by_status"].items()), "",
              "## Papier-Trades", "", f"Reflektierte Trades: {data['trades_reflected']}"]
    lines += [f"- {k}: {v}" for k, v in data["trade_lessons"].items()]
    lines += ["", "## Vorschläge (höchstens drei)", ""]
    lines += [f"{n}. {p}" for n, p in enumerate(data["proposals"], 1)] or ["Keine."]
    return "\n".join(lines) + "\n"
