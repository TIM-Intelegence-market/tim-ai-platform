"""Study generator (F3): turns a ready idea plus a study spec into a pre-registration draft.

The draft is a Markdown file under docs/research_lab/studien/ with every
mandatory field filled. Missing fields stop the generator; nothing is computed
and nothing is written to REGISTER.jsonl. At stage 1 a draft needs Uzi's
approval before any data are loaded; registration itself still follows
PROTOKOLL.md by hand. The spec hash in the draft lets a later run prove that it
used exactly these rules.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.research_lab.protocol import MAX_REGISTER_ENTRIES, PROTOCOL_VERSION
from src.research_lab.stats.register import HypothesisRegister
from src.research_lab.workshop import charter
from src.research_lab.workshop.check import HOLDOUT_START, _holdout, _local_month
from src.research_lab.workshop.ideas import IdeaQueue

STUDIES_DIR = Path("docs/research_lab/studien")
REGISTER_PATH = Path("docs/research_lab/REGISTER.jsonl")
LOGBOOK_PATH = Path("docs/research_lab/LOGBUCH.json")

COMMON = ("question", "data", "metric", "min_effect", "min_cases", "stop_rule", "limits")
REQUIRED = {
    "regel_backtest": COMMON + ("variants", "costs", "random_baseline"),
    "ereignis_studie": COMMON + ("events", "comparison"),
    "modellvergleich": COMMON + ("model", "features", "label", "prospective_window"),
}
# Templates whose variants take register slots (protocol section 6).
USES_REGISTER = {"regel_backtest"}


class DraftError(ValueError):
    pass


def _filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple)):
        return len(value) > 0
    return True


def spec_hash(spec: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def used_study_ids(studies_dir: Path = STUDIES_DIR, logbook: Path = LOGBOOK_PATH) -> set[int]:
    """Every S-number that appears anywhere, including rejected names in logbook lessons."""
    text = logbook.read_text(encoding="utf-8") if logbook.exists() else ""
    names = " ".join(p.name for p in studies_dir.glob("*")) if studies_dir.exists() else ""
    return {int(n) for n in re.findall(r"\bS(\d+)", f"{text} {names}")}


def next_study_id(studies_dir: Path = STUDIES_DIR, logbook: Path = LOGBOOK_PATH) -> str:
    return f"S{max(used_study_ids(studies_dir, logbook) | {0}) + 1}"


def validate(idea: Mapping[str, Any], spec: Mapping[str, Any]) -> list[str]:
    problems = []
    template = spec.get("template") or idea.get("template")
    if template not in REQUIRED:
        return [f"Vorlage fehlt oder unbekannt ({template!r}); erlaubt: {', '.join(sorted(REQUIRED))}"]
    for field in REQUIRED[template]:
        if not _filled(spec.get(field)):
            problems.append(f"Pflichtfeld {field!r} fehlt")
    if idea.get("derived_from") and not _filled(spec.get("prior_burden")):
        problems.append(f"Idee ist Ableitung von {idea['derived_from']}: Pflichtfeld 'prior_burden' (Vorbelastung) fehlt")
    for variant in spec.get("variants") or []:
        if not all(_filled(variant.get(k)) for k in ("id", "rule", "params")):
            problems.append(f"Variante {variant.get('id', '?')}: id, rule und params sind Pflicht")
    ids = [v.get("id") for v in spec.get("variants") or []]
    if len(ids) != len(set(ids)):
        problems.append("Varianten-IDs sind nicht eindeutig")
    period = spec.get("period") or idea.get("period")
    if period and date.fromisoformat(period[1]) >= HOLDOUT_START:
        archive = _holdout({**idea, "period": period, "data": spec.get("data") or idea.get("data")})
        problems.extend(archive)
    if template == "modellvergleich":
        window = spec.get("prospective_window") or {}
        if not _filled(window.get("start")) or not _filled(window.get("days")):
            problems.append("prospective_window braucht start und days")
    return problems


def _register_line(template: str, n_variants: int, register: HypothesisRegister) -> tuple[str, int, int]:
    if template not in USES_REGISTER:
        return ("Eigene Familie außerhalb des Holdout-Registers (wie S1/S8); belegt keine Registerplätze.", -1, -1)
    m = register.m
    after = m + n_variants
    if after > MAX_REGISTER_ENTRIES:
        raise DraftError(f"Register voll: m = {m}, {n_variants} neue Varianten, Grenze {MAX_REGISTER_ENTRIES}. "
                         "Ein neuer Holdout-Zeitraum ist nötig (Uzis Entscheidung).")
    return (f"{n_variants} Varianten im Holdout-Register: m = {m} → {after} von {MAX_REGISTER_ENTRIES}.", m, after)


def _bullets(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {item}" for item in value)
    if isinstance(value, dict):
        return "\n".join(f"- {k}: {v}" for k, v in value.items())
    return str(value)


def render(study_id: str, idea: Mapping[str, Any], spec: Mapping[str, Any], *, register_text: str,
           created: str, digest: str) -> str:
    template = spec.get("template") or idea["template"]
    variants = spec.get("variants") or []
    snooping = template == "regel_backtest" and len(variants) >= charter.SNOOPING_TEST_FROM_VARIANTS
    lines = [
        f"# {study_id}: {spec.get('title') or idea['title']} (Präregistrierung, Entwurf)",
        "",
        "| Feld | Wert |",
        "|---|---|",
        f"| Studie | {study_id} |",
        f"| Version | **Entwurf 0.1 – wartet auf Uzis Freigabe (Forschungsbereich Stufe {charter.STAGE}); vorher werden keine Daten geladen** |",
        f"| Erzeugt | {created} Ortszeit vom Studien-Generator (`src/research_lab/workshop/generator.py`) |",
        f"| Idee | {idea['id']} aus Quelle „{charter.SOURCES[idea['source']]}“ (`docs/research_lab/IDEEN.jsonl`) |",
        f"| Vorlage | {charter.TEMPLATES[template]} |",
        f"| Spezifikation | SHA-256 `{digest}` |",
        f"| Protokoll | `../PROTOKOLL.md` Version {PROTOCOL_VERSION} |",
        f"| Holdout | ab {HOLDOUT_START.isoformat()}, wird nur mit Uzis ausdrücklichem Wort geladen |",
        f"| Register | {register_text} |",
        "",
        "## 1. Fragestellung", "", str(spec["question"]), "",
        "## 2. Hypothese und Herkunft", "", idea["hypothesis"], "",
    ]
    if idea.get("counterargument"):
        lines += [f"Gegenargument: {idea['counterargument']}", ""]
    lines += ["## 3. Vorbelastung", "",
              str(spec.get("prior_burden") or "Keine bekannte Vorbelastung angegeben; Ideen-Prüfung fand keine ähnliche Studie."), "",
              "## 4. Daten", "", _bullets(spec["data"]), ""]
    if spec.get("period"):
        lines += [f"Zeitraum: {spec['period'][0]} bis {spec['period'][1]}.", ""]
    if template == "regel_backtest":
        lines += ["## 5. Varianten und Regeln", "", "| Variante | Regel | Parameter (fest) |", "|---|---|---|"]
        lines += [f"| {v['id']} | {v['rule']} | `{json.dumps(v['params'], sort_keys=True, ensure_ascii=False)}` |" for v in variants]
        lines += ["", f"Kosten: {spec['costs']}", "", f"Zufallsvergleich: {spec['random_baseline']}", ""]
    elif template == "ereignis_studie":
        lines += ["## 5. Ereignisse und Vergleich", "", _bullets(spec["events"]), "", f"Vergleich: {spec['comparison']}", ""]
    else:
        window = spec["prospective_window"]
        lines += ["## 5. Modell, Merkmale, Zielwert", "", f"- Modell: {spec['model']}", f"- Merkmale: {spec['features']}",
                  f"- Zielwert: {spec['label']}",
                  f"- Prospektives Fenster: ab {window['start']} für {window['days']} Tage, genau einmal benutzt", ""]
    lines += ["## 6. Messgröße und Entscheidung", "", f"- Messgröße: {spec['metric']}", f"- Kleinster Effekt: {spec['min_effect']}",
              f"- Mindestzahl Fälle: {spec['min_cases']} (sonst „nicht prüfbar“; Zähllauf vor jeder Auswertung)",
              f"- Stoppregel: {spec['stop_rule']}"]
    if snooping:
        lines.append(f"- Glückstest SPA/StepM Pflicht ({len(variants)} Varianten, ab {charter.SNOOPING_TEST_FROM_VARIANTS})")
    lines += ["", "## 7. Bekannte Grenzen", "", _bullets(spec["limits"]), "",
              "## 8. Feste Grenzen", "", _bullets(list(charter.FIXED_LIMITS)), "",
              "## Änderungsprotokoll", "", "| Datum | Version | Änderung |", "|---|---|---|",
              f"| {created[:10]} | 0.1 | Entwurf vom Studien-Generator aus Idee {idea['id']} |", ""]
    return "\n".join(lines)


def _slug(text: str) -> str:
    table = str.maketrans({"ä": "AE", "ö": "OE", "ü": "UE", "ß": "SS"})
    words = re.findall(r"[A-Z0-9]+", text.upper().translate(table))
    return "_".join(words[:5]) or "STUDIE"


def create_draft(queue: IdeaQueue, idea_id: str, spec: Mapping[str, Any], *, now: str,
                 studies_dir: Path = STUDIES_DIR, register_path: Path = REGISTER_PATH,
                 logbook_path: Path = LOGBOOK_PATH, write: bool = True) -> tuple[Path, str]:
    ideas = queue.ideas()
    if idea_id not in ideas:
        raise DraftError(f"{idea_id} steht nicht in der Ideen-Liste")
    idea = ideas[idea_id]
    if idea["status"] != "ready":
        raise DraftError(f"{idea_id} ist nicht bereit (Status {idea['status']}); erst `check --record`")
    month = _local_month(now)
    used = sum(1 for i in ideas.values() for status, at in i["history"] if status == "study_draft" and _local_month(at) == month)
    if used >= charter.MONTHLY_STUDY_BUDGET:
        raise DraftError(f"Budget {charter.MONTHLY_STUDY_BUDGET} Studien im Monat {month} ist verbraucht")
    problems = validate(idea, spec)
    if problems:
        raise DraftError("Entwurf unvollständig:\n- " + "\n- ".join(problems))
    template = spec.get("template") or idea["template"]
    register_text, _, _ = _register_line(template, len(spec.get("variants") or []), HypothesisRegister(register_path))
    study_id = spec.get("study_id") or next_study_id(studies_dir, logbook_path)
    if int(study_id.lstrip("S")) in used_study_ids(studies_dir, logbook_path):
        raise DraftError(f"Studien-Name {study_id} ist schon vergeben")
    created = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(ZoneInfo(charter.LOCAL_TIMEZONE)).strftime("%Y-%m-%d %H:%M")
    digest = spec_hash({**spec, "study_id": study_id, "idea": idea_id})
    text = render(study_id, idea, {**spec, "template": template}, register_text=register_text, created=created, digest=digest)
    path = studies_dir / f"{study_id}_{_slug(spec.get('title') or idea['title'])}_PRAEREGISTRIERUNG_ENTWURF.md"
    if write:
        if path.exists():
            raise DraftError(f"{path} gibt es schon")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        queue.set_status(idea_id, "study_draft", [f"{study_id}: {path.as_posix()}", f"spec {digest}"], at=now)
    return path, text
