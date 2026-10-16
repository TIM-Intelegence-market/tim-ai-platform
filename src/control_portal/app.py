from __future__ import annotations

import fcntl
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import urlopen

from .security import redact_object, redact_text
from .store import API_SCOPES, CHANGE_CATEGORIES, PortalStore, utc_now


MAX_FORM_BYTES = 64 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
TASK_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{3,120}$")
ROLE_LEVEL = {"viewer": 0, "operator": 1, "admin": 2}


@dataclass(frozen=True, slots=True)
class PortalConfig:
    repo_root: Path
    state_root: Path
    db_path: Path
    host: str = "127.0.0.1"
    port: int = 8090
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")
    cookie_secure: bool = False
    session_hours: int = 12
    allow_bootstrap: bool = False
    ollama_url: str = "http://127.0.0.1:11434"


def _safe(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _task_files(config: PortalConfig) -> list[Path]:
    paths: set[Path] = set()
    roots = [config.state_root, *config.state_root.parent.glob("*-state*"), *config.state_root.parent.glob("smoke-state*")]
    for root in roots:
        for folder in ("tasks", "inbox", "processed", "blockers/requests"):
            directory = root / folder
            if directory.is_dir():
                paths.update(path for path in directory.glob("*.json") if path.is_file())
    return sorted(paths, key=lambda item: item.stat().st_mtime_ns, reverse=True)


def discover_tasks(config: PortalConfig) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for path in _task_files(config):
        value = _read_json(path)
        if not value:
            continue
        task_id = str(value.get("task_id") or path.stem).split(".", 1)[0]
        if task_id in by_id:
            continue
        value = redact_object(value)
        value["task_id"] = task_id
        value["source_path"] = str(path)
        value["source_mtime"] = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        by_id[task_id] = value
    return list(by_id.values())


def task_by_id(config: PortalConfig, task_id: str) -> dict[str, Any] | None:
    return next((task for task in discover_tasks(config) if task["task_id"] == task_id), None)


def create_task(config: PortalConfig, values: dict[str, str], actor: str) -> dict[str, Any]:
    objective = values.get("objective", "").strip()
    next_action = values.get("next_action", "").strip()
    risk = values.get("risk", "A1").strip().upper()
    if not objective or len(objective) > 4000:
        raise ValueError("Das Ziel muss zwischen 1 und 4000 Zeichen enthalten.")
    if not next_action or len(next_action) > 2000:
        raise ValueError("Der nächste Schritt muss zwischen 1 und 2000 Zeichen enthalten.")
    if risk not in {"A0", "A1", "A2"}:
        raise ValueError("Über das Portal sind nur die Risiken A0 bis A2 zulässig.")
    allowed_paths: list[str] = []
    for line in values.get("allowed_paths", "").splitlines():
        candidate = line.strip().replace("\\", "/")
        if not candidate:
            continue
        path = Path(candidate)
        if path.is_absolute() or ".." in path.parts or len(candidate) > 240:
            raise ValueError(f"Ungültiger erlaubter Pfad: {candidate}")
        allowed_paths.append(candidate)
    if len(allowed_paths) > 24:
        raise ValueError("Maximal 24 erlaubte Pfade sind zulässig.")
    task_id = f"portal-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
    payload = {
        "task_id": task_id,
        "objective": redact_text(objective, 4000),
        "next_action": redact_text(next_action, 2000),
        "state": "READY",
        "risk": risk,
        "fingerprint": None,
        "allowed_paths": allowed_paths,
        "evidence": [{"type": "portal_submission", "actor": actor, "at": utc_now()}],
        "blocker_reason": None,
        "updated_at": utc_now(),
    }
    inbox = config.state_root / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    temp = inbox / f".{task_id}.{secrets.token_hex(4)}.tmp"
    target = inbox / f"{task_id}.json"
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.chmod(0o600)
    os.replace(temp, target)
    return payload


def append_approved_experience(config: PortalConfig, task: dict[str, Any], actor: str, notes: str) -> None:
    root = config.state_root / "experience"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "approved.jsonl"
    payload = redact_object(
        {
            "schema_version": 1,
            "task_id": task.get("task_id"),
            "fingerprint": task.get("fingerprint"),
            "risk": task.get("risk"),
            "objective": str(task.get("objective", ""))[:4000],
            "result_state": task.get("state"),
            "next_action": str(task.get("next_action", ""))[:2000],
            "allowed_paths": list(task.get("allowed_paths", []))[:24],
            "human_notes": notes[:4000],
            "approved_by": actor,
            "approved_at": utc_now(),
            "authority": "HUMAN_APPROVED_EXPERIENCE",
        }
    )
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    path.chmod(0o600)


def _command(argv: list[str], cwd: Path | None = None) -> str:
    try:
        completed = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=3, check=False)
        return redact_text((completed.stdout or completed.stderr).strip(), 5000)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"UNAVAILABLE:{type(exc).__name__}"


def system_snapshot(config: PortalConfig) -> dict[str, Any]:
    memory: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable"}:
                memory[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        pass
    disk = shutil.disk_usage(config.state_root)
    services = {
        name: _command(["systemctl", "is-active", name])
        for name in ("ollama", "tim-qwen-worker", "tim-healthcheck.timer", "tim-backup.timer")
    }
    ollama: dict[str, Any] = {"status": "UNAVAILABLE"}
    try:
        with urlopen(config.ollama_url.rstrip("/") + "/api/version", timeout=2) as response:
            ollama = json.loads(response.read(MAX_JSON_BYTES))
            ollama["status"] = "AVAILABLE"
    except Exception:
        pass
    return {
        "hostname": _command(["hostname"]),
        "kernel": _command(["uname", "-r"]),
        "load": [round(value, 2) for value in os.getloadavg()],
        "memory_total": memory.get("MemTotal"),
        "memory_available": memory.get("MemAvailable"),
        "disk_total": disk.total,
        "disk_free": disk.free,
        "services": services,
        "ollama": ollama,
        "git": _command(["git", "status", "--short", "--branch"], config.repo_root),
        "generated_at": utc_now(),
    }


def _bytes(value: int | None) -> str:
    if value is None:
        return "—"
    amount = float(value)
    for suffix in ("B", "KiB", "MiB", "GiB", "TiB"):
        if amount < 1024 or suffix == "TiB":
            return f"{amount:.1f} {suffix}"
        amount /= 1024
    return "—"


def _badge(value: Any) -> str:
    state = str(value or "UNKNOWN").upper()
    level = "green" if state in {"ACTIVE", "AVAILABLE", "READY", "VERIFYING", "PASS"} else "red" if state in {"FAILED", "BLOCKED", "UNAVAILABLE", "REJECTED"} else "yellow"
    return f"<span class='badge badge--{level}'>{_safe(state)}</span>"


def _layout(title: str, user: dict[str, Any] | None, body: str, *, message: str = "") -> str:
    if user:
        admin = "<a href='/users'>Benutzer</a><a href='/audit'>Audit</a>" if user["role"] == "admin" else ""
        navigation = (
            "<nav><a href='/'>Übersicht</a><a href='/tasks'>Qwen-Tasks</a>"
            "<a href='/changes'>Freigaben</a><a href='/training'>Training</a><a href='/system'>System</a><a href='/onboarding'>Start</a>"
            f"{admin}<a href='/account'>Konto</a>"
            "<form method='post' action='/logout' class='inline'><input type='hidden' name='csrf' value='__CSRF__'><button>Abmelden</button></form></nav>"
        )
        identity = f"<div class='identity'>{_safe(user['display_name'])}<small>{_safe(user['role'])}</small></div>"
    else:
        navigation, identity = "", ""
    alert = f"<div class='alert'>{_safe(message)}</div>" if message else ""
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_safe(title)} · T.I.M.E.C.</title><link rel='stylesheet' href='/static/app.css'></head>"
        "<body><header><a class='brand' href='/'><b>T.I.M.E.C.</b><span>TIM ENGINEERING CONSOLE</span></a>"
        f"{navigation}{identity}</header><main><div class='page-head'><div><p class='eyebrow'>LOCAL-FIRST OPERATIONS</p><h1>{_safe(title)}</h1></div>"
        "<div class='safety'>TRADING LOCKED · EXECUTION DISABLED</div></div>"
        f"{alert}{body}</main><footer>T.I.M.E.C. · TIM Engineering Console · Qwen Worker · Governance · Controlled Learning</footer></body></html>"
    )


def _login_page(message: str = "") -> str:
    return _layout(
        "Anmelden",
        None,
        "<section class='auth card'><h2>Mitgliedskonto</h2><form method='post' action='/login'>"
        "<label>Benutzername<input name='username' autocomplete='username' required></label>"
        "<label>Passwort<input type='password' name='password' autocomplete='current-password' required></label>"
        "<button class='primary'>Anmelden</button></form></section>",
        message=message,
    )


def _bootstrap_page(message: str = "") -> str:
    return _layout(
        "Ersten Administrator anlegen",
        None,
        "<section class='auth card'><p>Diese Seite funktioniert nur lokal und nur solange kein Konto existiert.</p>"
        "<form method='post' action='/bootstrap'>"
        "<label>Benutzername<input name='username' autocomplete='username' required></label>"
        "<label>Anzeigename<input name='display_name' required></label>"
        "<label>Passwort<input type='password' name='password' autocomplete='new-password' minlength='14' required></label>"
        "<label>Passwort wiederholen<input type='password' name='confirm' autocomplete='new-password' minlength='14' required></label>"
        "<button class='primary'>Administratorkonto anlegen</button></form></section>",
        message=message,
    )


def _overview(config: PortalConfig, user: dict[str, Any], store: PortalStore) -> str:
    tasks = discover_tasks(config)
    states: dict[str, int] = {}
    for task in tasks:
        key = str(task.get("state", "UNKNOWN")).upper()
        states[key] = states.get(key, 0) + 1
    approved_path = config.state_root / "experience/approved.jsonl"
    approved = 0
    try:
        approved = sum(1 for line in approved_path.read_text().splitlines() if line.strip())
    except OSError:
        pass
    campaigns = store.list_campaigns()
    pending_changes = sum(1 for item in store.list_change_requests() if item["status"] == "PENDING")
    cards = (
        f"<article class='metric'><span>Tasks gesamt</span><strong>{len(tasks)}</strong></article>"
        f"<article class='metric'><span>Bereit</span><strong>{states.get('READY', 0)}</strong></article>"
        f"<article class='metric'><span>Blockiert</span><strong>{states.get('BLOCKED', 0)}</strong></article>"
        f"<article class='metric'><span>Freigegebene Erfahrungen</span><strong>{approved}</strong></article>"
        f"<article class='metric'><span>Offene Freigaben</span><strong>{pending_changes}</strong></article>"
    )
    recent = "".join(
        f"<tr><td><a href='/tasks/{quote(str(task['task_id']))}'>{_safe(task['task_id'])}</a></td>"
        f"<td>{_badge(task.get('state'))}</td><td>{_safe(task.get('risk'))}</td><td>{_safe(str(task.get('objective',''))[:120])}</td>"
        f"<td>{_safe(task.get('updated_at') or task.get('source_mtime'))}</td></tr>"
        for task in tasks[:12]
    ) or "<tr><td colspan='5'>Noch keine Tasks vorhanden.</td></tr>"
    return _layout(
        "Übersicht",
        user,
        "<section class='grid metrics'>" + cards + "</section>"
        "<section class='card'><div class='section-head'><h2>Letzte Qwen-Tasks</h2><a class='button' href='/tasks'>Alle anzeigen</a></div>"
        "<div class='table-wrap'><table><thead><tr><th>ID</th><th>Status</th><th>Risiko</th><th>Ziel</th><th>Aktualisiert</th></tr></thead>"
        f"<tbody>{recent}</tbody></table></div></section>"
        "<section class='card'><h2>Kontrollierter Lernweg</h2><div class='flow'>"
        "<span>Hypothese</span><b>→</b><span>Datensatz</span><b>→</b><span>Simulation</span><b>→</b><span>Evaluation</span><b>→</b><span>Freigabe</span><b>→</b><span>LoRA-Kandidat</span></div>"
        "<p>Keine Modellgewichte werden automatisch verändert. Nur menschlich freigegebene Erfahrungen stehen dem Worker als begrenzter Kontext zur Verfügung.</p></section>",
    )


def _tasks_page(config: PortalConfig, user: dict[str, Any]) -> str:
    tasks = discover_tasks(config)
    rows = "".join(
        f"<tr><td><a href='/tasks/{quote(str(task['task_id']))}'>{_safe(task['task_id'])}</a></td>"
        f"<td>{_badge(task.get('state'))}</td><td>{_safe(task.get('risk'))}</td>"
        f"<td>{_safe(str(task.get('objective',''))[:160])}</td><td>{len(task.get('evidence', []))}</td>"
        f"<td>{_safe(task.get('updated_at') or task.get('source_mtime'))}</td></tr>"
        for task in tasks
    ) or "<tr><td colspan='6'>Keine Tasks vorhanden.</td></tr>"
    submit = "<a class='button primary' href='/submit'>Task anlegen</a>" if ROLE_LEVEL[user["role"]] >= 1 else ""
    return _layout(
        "Qwen-Tasks",
        user,
        f"<section class='card'><div class='section-head'><div><h2>Persistierte Aufgaben</h2><p>Ziel, Status, technische Evidenz und Ergebnis des lokalen Workers.</p></div>{submit}</div>"
        "<div class='table-wrap'><table><thead><tr><th>ID</th><th>Status</th><th>Risiko</th><th>Ziel</th><th>Evidenz</th><th>Aktualisiert</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>",
    )


def _task_page(config: PortalConfig, store: PortalStore, user: dict[str, Any], task: dict[str, Any]) -> str:
    feedback = store.feedback_for(str(task["task_id"]))
    feedback_rows = "".join(
        f"<tr><td>{_safe(item['created_at'])}</td><td>{_safe(item['username'])}</td><td>{_badge(item['verdict'])}</td><td>{_safe(item['notes'])}</td></tr>"
        for item in feedback
    ) or "<tr><td colspan='4'>Noch keine menschliche Bewertung.</td></tr>"
    form = ""
    if ROLE_LEVEL[user["role"]] >= 1:
        form = (
            "<section class='card'><h2>Menschliche Bewertung</h2><form method='post' action='/tasks/"
            + quote(str(task["task_id"]))
            + "/feedback'><input type='hidden' name='csrf' value='__CSRF__'>"
            "<label>Bewertung<select name='verdict'><option>USEFUL</option><option>NEEDS_WORK</option><option>REJECTED</option>"
            "<option>APPROVED_FOR_LEARNING</option></select></label>"
            "<label>Technische Notiz<textarea name='notes' maxlength='4000'></textarea></label>"
            "<button class='primary'>Bewertung speichern</button></form>"
            "<p class='warning'>APPROVED_FOR_LEARNING nimmt diese Erfahrung in den begrenzten, menschlich freigegebenen Kontext auf. Es startet kein Gewichtstraining.</p></section>"
        )
    detail = (
        "<section class='grid detail-grid'>"
        f"<article class='metric'><span>Status</span>{_badge(task.get('state'))}</article>"
        f"<article class='metric'><span>Risiko</span><strong>{_safe(task.get('risk'))}</strong></article>"
        f"<article class='metric'><span>Evidenz</span><strong>{len(task.get('evidence', []))}</strong></article>"
        "</section><section class='card'><h2>Ziel</h2><p>" + _safe(task.get("objective")) + "</p>"
        "<h3>Nächster Schritt</h3><p>" + _safe(task.get("next_action")) + "</p>"
        "<h3>Blocker</h3><p>" + _safe(task.get("blocker_reason")) + "</p></section>"
        "<section class='card'><h2>Technische Rohdaten</h2><pre>" + _safe(json.dumps(task, indent=2, ensure_ascii=False, sort_keys=True)) + "</pre></section>"
        "<section class='card'><h2>Bewertungsverlauf</h2><div class='table-wrap'><table><thead><tr><th>Zeit</th><th>Benutzer</th><th>Bewertung</th><th>Notiz</th></tr></thead>"
        f"<tbody>{feedback_rows}</tbody></table></div></section>{form}"
    )
    return _layout(f"Task {task['task_id']}", user, detail)


def _submit_page(user: dict[str, Any], message: str = "") -> str:
    return _layout(
        "Neuen Qwen-Task anlegen",
        user,
        "<section class='card'><form method='post' action='/submit'><input type='hidden' name='csrf' value='__CSRF__'>"
        "<label>Ziel<textarea name='objective' maxlength='4000' required></textarea></label>"
        "<label>Nächster technischer Schritt<textarea name='next_action' maxlength='2000' required></textarea></label>"
        "<label>Risiko<select name='risk'><option>A0</option><option selected>A1</option><option>A2</option></select></label>"
        "<label>Erlaubte Repository-Pfade, einer pro Zeile<textarea name='allowed_paths' placeholder='src/modul.py&#10;tests/test_modul.py'></textarea></label>"
        "<button class='primary'>In lokale Queue stellen</button></form>"
        "<p class='warning'>A3, Produktion, Live-Trading, Secrets und destruktive Aktionen werden weiterhin von den lokalen Sicherheitsregeln blockiert.</p></section>",
        message=message,
    )


def _training_page(store: PortalStore, user: dict[str, Any], message: str = "") -> str:
    campaigns = store.list_campaigns()
    rows = "".join(
        f"<tr><td>{item['id']}</td><td>{_safe(item['name'])}</td><td>{_badge(item['status'])}</td>"
        f"<td>{_safe(item['hypothesis'])}</td><td>{_safe(item['target_metrics'])}</td><td>{_safe(item['requested_by_name'])}</td><td>{_safe(item['created_at'])}</td></tr>"
        for item in campaigns
    ) or "<tr><td colspan='7'>Noch keine Trainingskampagne angefordert.</td></tr>"
    form = ""
    if ROLE_LEVEL[user["role"]] >= 1:
        form = (
            "<section class='card'><h2>Trainingskampagne anfordern</h2><form method='post' action='/training'>"
            "<input type='hidden' name='csrf' value='__CSRF__'>"
            "<label>Name<input name='name' maxlength='120' required></label>"
            "<label>Hypothese<textarea name='hypothesis' maxlength='4000' required placeholder='Wenn wir freigegebene Bugfix-Beispiele verwenden, verbessert sich …'></textarea></label>"
            "<label>Zielmetriken<textarea name='metrics' maxlength='2000' required placeholder='Patch-Erfolgsrate, Tests bestanden, keine Sicherheitsverletzung …'></textarea></label>"
            "<label>Datensatzauswahl<textarea name='dataset_query' maxlength='2000' placeholder='Nur APPROVED_FOR_LEARNING, Risiko A0–A2 …'></textarea></label>"
            "<button class='primary'>Kampagne anfordern</button></form></section>"
        )
    return _layout(
        "Kontrolliertes Training",
        user,
        "<section class='card'><h2>Unveränderliche Freigabekette</h2><div class='flow'><span>Hypothese</span><b>→</b><span>Datensatzprüfung</span><b>→</b><span>Simulation</span><b>→</b><span>Holdout-Evaluation</span><b>→</b><span>Menschliche Freigabe</span><b>→</b><span>LoRA-Training</span><b>→</b><span>Shadow-Test</span><b>→</b><span>Aktivierung</span></div>"
        "<p>Der T330 sammelt, prüft und bewertet Daten. Für das 7B-Finetuning wird ein separater GPU-Runner benötigt. Bis dieser ausdrücklich eingerichtet ist, bleiben Kampagnen reine, auditierbare Anforderungen.</p></section>"
        "<section class='card'><h2>Was sich verändern darf</h2><p>Bevorzugt werden kleine LoRA-Adapter für ausgewählte Attention- und MLP-Projektionen trainiert. Das Grundmodell bleibt unverändert. Gemessen werden unter anderem technische Korrektheit, Patch-Erfolgsrate, JSON-/Tool-Konformität, Regressionen und Sicherheitsverstöße.</p></section>"
        "<section class='card'><h2>Kampagnen</h2><div class='table-wrap'><table><thead><tr><th>ID</th><th>Name</th><th>Status</th><th>Hypothese</th><th>Metriken</th><th>Beantragt von</th><th>Zeit</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>{form}",
        message=message,
    )


def _changes_page(store: PortalStore, user: dict[str, Any], message: str = "") -> str:
    rows = "".join(
        f"<tr><td><a href='/changes/{item['id']}'>#{item['id']}</a></td><td>{_badge(item['status'])}</td>"
        f"<td>{_safe(item['category'])}</td><td>{_safe(item['title'])}</td><td>{_safe(item['requested_by_name'])}</td>"
        f"<td>{item['support_count']} / {item['object_count']}</td><td>{_safe(item['created_at'])}</td></tr>"
        for item in store.list_change_requests()
    ) or "<tr><td colspan='7'>Noch keine Änderungsanträge.</td></tr>"
    form = ""
    if ROLE_LEVEL[user["role"]] >= 1:
        options = "".join(f"<option>{value}</option>" for value in sorted(CHANGE_CATEGORIES))
        form = (
            "<section class='card'><h2>Änderung beantragen</h2><form method='post' action='/changes'>"
            "<input type='hidden' name='csrf' value='__CSRF__'>"
            "<label>Titel<input name='title' maxlength='160' required></label>"
            f"<label>Bereich<select name='category'>{options}</select></label>"
            "<label>Grund<textarea name='reason' maxlength='4000' required></textarea></label>"
            "<label>Geplante Änderung<textarea name='proposed_change' maxlength='8000' required></textarea></label>"
            "<label>Auswirkung auf Hardware, RAM, Speicher, Modelle und Dienste<textarea name='resource_impact' maxlength='4000' required></textarea></label>"
            "<label>Rollback-Plan<textarea name='rollback_plan' maxlength='4000' required></textarea></label>"
            "<button class='primary'>Antrag zur Prüfung stellen</button></form></section>"
        )
    return _layout(
        "Änderungen und Freigaben", user,
        "<section class='card'><p>Änderungen an Quellen, Modellen, Speicher, Hardware, Zugriff, Netzwerk und Sicherheit werden zuerst hier begründet und bewertet. Eine Freigabe führt die Änderung nicht automatisch aus.</p>"
        "<p class='warning'>Für SECURITY, NETWORK, HARDWARE und ACCESS gilt bei eigenen Administratoranträgen das Vier-Augen-Prinzip.</p></section>"
        "<section class='card'><div class='table-wrap'><table><thead><tr><th>ID</th><th>Status</th><th>Bereich</th><th>Titel</th><th>Antragsteller</th><th>Dafür / Einwand</th><th>Zeit</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>{form}", message=message,
    )


def _change_page(store: PortalStore, user: dict[str, Any], change_id: int) -> str:
    item = store.get_change_request(change_id)
    votes = store.votes_for_change(change_id)
    vote_rows = "".join(
        f"<tr><td>{_safe(v['created_at'])}</td><td>{_safe(v['username'])}</td><td>{_badge(v['vote'])}</td><td>{_safe(v['reason'])}</td></tr>" for v in votes
    ) or "<tr><td colspan='4'>Noch keine Bewertung.</td></tr>"
    controls = ""
    if item["status"] == "PENDING" and ROLE_LEVEL[user["role"]] >= 1:
        controls += (
            f"<section class='card'><h2>Bewerten</h2><form method='post' action='/changes/{change_id}/vote'><input type='hidden' name='csrf' value='__CSRF__'>"
            "<label>Stimme<select name='vote'><option>SUPPORT</option><option>OBJECT</option><option>ABSTAIN</option></select></label>"
            "<label>Begründung<textarea name='reason' maxlength='2000' required></textarea></label><button>Stimme speichern</button></form></section>"
        )
    if item["status"] == "PENDING" and user["role"] == "admin":
        controls += (
            f"<section class='card'><h2>Administratorentscheidung</h2><form method='post' action='/changes/{change_id}/decide'><input type='hidden' name='csrf' value='__CSRF__'>"
            "<label>Entscheidung<select name='decision'><option>APPROVED</option><option>REJECTED</option></select></label>"
            "<label>Prüfgrund<textarea name='reason' maxlength='4000' required></textarea></label><button class='primary'>Entscheidung protokollieren</button></form>"
            "<p class='warning'>APPROVED bedeutet nur: fachlich freigegeben. Es führt keine Befehle aus und ändert weder pfSense noch den Server.</p></section>"
        )
    body = (
        "<section class='grid detail-grid'>"
        f"<article class='metric'><span>Status</span>{_badge(item['status'])}</article><article class='metric'><span>Bereich</span><strong>{_safe(item['category'])}</strong></article>"
        f"<article class='metric'><span>Antragsteller</span><strong>{_safe(item['requested_by_name'])}</strong></article></section>"
        f"<section class='card'><h2>{_safe(item['title'])}</h2><h3>Grund</h3><p>{_safe(item['reason'])}</p><h3>Geplante Änderung</h3><pre>{_safe(item['proposed_change'])}</pre>"
        f"<h3>Ressourcenwirkung</h3><p>{_safe(item['resource_impact'])}</p><h3>Rollback</h3><p>{_safe(item['rollback_plan'])}</p>"
        f"<h3>Entscheidung</h3><p>{_safe(item.get('decision_reason'))}</p></section>"
        "<section class='card'><h2>Bewertungen</h2><table><thead><tr><th>Zeit</th><th>Mitglied</th><th>Stimme</th><th>Grund</th></tr></thead>"
        f"<tbody>{vote_rows}</tbody></table></section>{controls}"
    )
    return _layout(f"Änderungsantrag #{change_id}", user, body)


def _system_page(config: PortalConfig, user: dict[str, Any]) -> str:
    value = system_snapshot(config)
    services = "".join(
        f"<tr><td>{_safe(name)}</td><td>{_badge(state)}</td></tr>" for name, state in value["services"].items()
    )


def _onboarding_page(user: dict[str, Any]) -> str:
    return _layout(
        "Mitgliederstart", user,
        "<section class='card'><h2>Zugangsstatus</h2><p>Der Eigentümerzugang funktioniert derzeit über <code>http://127.0.0.1:8090/</code>. "
        "Der geplante Mitgliederlink <code>http://console.timec.home.arpa/</code> wird erst nach der OpenVPN- und DNS-Einrichtung aktiv.</p>"
        "<p class='warning'>Portal, SSH, Ollama und pfSense werden nicht direkt ins Internet gestellt.</p></section>"
        "<section class='card'><h2>Persönlicher Zugang</h2><ol><li>Persönliches OpenVPN-Konto und Clientzertifikat</li>"
        "<li>Einmaliger T.I.M.E.C.-Einladungslink</li><li>Eigenes Passwort</li><li>Viewer- oder Operatorrolle</li>"
        "<li>Optionaler, persönlicher API-Schlüssel unter Konto</li><li>Eigenes GitHub-Konto und eigener Branch für Quellarbeit</li></ol>"
        "<p>Alle Mitglieder verwenden denselben VPN-Dienst, aber niemals dasselbe Konto, Zertifikat, Passwort oder denselben API-Schlüssel.</p></section>"
        "<section class='card'><h2>ChatGPT/API</h2><p>Für Beobachtung reicht die Weboberfläche. Automatisierung nutzt einen zeitlich begrenzten Schlüssel. "
        "Die API kann Tasks lesen und als Operator begrenzte A0–A2-Tasks einreichen. Sie kann keine Benutzer verwalten, Freigaben erteilen oder Routereinstellungen ändern.</p>"
        "<pre>GET  /api/v1/me\nGET  /api/v1/tasks\nPOST /api/v1/tasks\nGET  /api/v1/changes</pre></section>"
        "<section class='card'><h2>Arbeitsweg</h2><div class='flow'><span>VPN</span><b>→</b><span>Anmeldung</span><b>→</b><span>Task</span><b>→</b>"
        "<span>Branch</span><b>→</b><span>Tests</span><b>→</b><span>Freigabe</span><b>→</b><span>Deployment</span></div></section>",
    )
    return _layout(
        "System",
        user,
        "<section class='grid metrics'>"
        f"<article class='metric'><span>Host</span><strong>{_safe(value['hostname'])}</strong></article>"
        f"<article class='metric'><span>Kernel</span><strong>{_safe(value['kernel'])}</strong></article>"
        f"<article class='metric'><span>RAM frei</span><strong>{_bytes(value['memory_available'])}</strong></article>"
        f"<article class='metric'><span>/srv frei</span><strong>{_bytes(value['disk_free'])}</strong></article>"
        f"<article class='metric'><span>Ollama</span>{_badge(value['ollama'].get('status'))}</article></section>"
        "<section class='card'><h2>Dienste</h2><table><thead><tr><th>Dienst</th><th>Status</th></tr></thead>"
        f"<tbody>{services}</tbody></table></section>"
        f"<section class='card'><h2>Git-Arbeitsstand</h2><pre>{_safe(value['git'])}</pre></section>"
        f"<section class='card'><h2>Technischer Snapshot</h2><pre>{_safe(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))}</pre></section>",
    )


def _users_page(store: PortalStore, user: dict[str, Any], message: str = "") -> str:
    rows = "".join(
        f"<tr><td>{_safe(item['username'])}{' · Eigentümer' if item['is_owner'] else ''}</td><td>{_safe(item['display_name'])}</td><td>{_safe(item['role'])}</td>"
        f"<td>{_badge('ACTIVE' if item['active'] else 'DISABLED')}</td><td>{_safe(item['created_at'])}</td><td>{_safe(item['last_login_at'])}</td>"
        "<td><form class='inline' method='post' action='/admin/user-status'><input type='hidden' name='csrf' value='__CSRF__'>"
        f"<input type='hidden' name='user_id' value='{item['id']}'><input type='hidden' name='active' value='{'0' if item['active'] else '1'}'>"
        f"<button>{'Deaktivieren' if item['active'] else 'Aktivieren'}</button></form></td></tr>"
        for item in store.list_users()
    )
    role_rows = "".join(
        f"<tr><td>#{item['id']}</td><td>{_safe(item['username'])}</td><td>{_safe(item['current_role'])} → {_safe(item['requested_role'])}</td>"
        f"<td>{_safe(item['reason'])}</td><td>{_safe(item['created_at'])}</td><td><form method='post' action='/admin/role-request'>"
        "<input type='hidden' name='csrf' value='__CSRF__'>"
        f"<input type='hidden' name='request_id' value='{item['id']}'><label>Entscheidung<select name='decision'><option>APPROVED</option><option>REJECTED</option></select></label>"
        "<label>Begründung<input name='reason' maxlength='2000' required></label><button>Entscheiden</button></form></td></tr>"
        for item in store.list_role_requests(pending_only=True)
    ) or "<tr><td colspan='6'>Keine offenen Rollenanträge.</td></tr>"
    api_rows = "".join(
        f"<tr><td>{_safe(item['username'])}</td><td>{_safe(item['name'])}</td><td><code>{_safe(item['prefix'])}…</code></td>"
        f"<td>{_safe(item['scopes'])}</td><td>{_safe(item['expires_at'])}</td><td>{_safe(item['last_used_at'])}</td><td>{_badge('REVOKED' if item['revoked_at'] else 'ACTIVE')}</td>"
        "<td><form class='inline' method='post' action='/admin/api-key/revoke'><input type='hidden' name='csrf' value='__CSRF__'>"
        f"<input type='hidden' name='key_id' value='{item['id']}'><button>Widerrufen</button></form></td></tr>"
        for item in store.list_all_api_keys()
    ) or "<tr><td colspan='8'>Keine API-Schlüssel.</td></tr>"
    return _layout(
        "Benutzerverwaltung",
        user,
        "<section class='grid two'><article class='card'><h2>Mitglied einladen</h2><form method='post' action='/admin/invite'>"
        "<input type='hidden' name='csrf' value='__CSRF__'><p>Neue Konten starten immer als Viewer. Höhere Rollen werden danach beantragt.</p>"
        "<button class='primary'>Viewer-Einladungslink erzeugen</button></form></article>"
        "<article class='card'><h2>Passwort-Reset</h2><form method='post' action='/admin/reset'>"
        "<input type='hidden' name='csrf' value='__CSRF__'><label>Benutzername<input name='username' required></label>"
        "<button>Reset-Link erzeugen</button></form></article></section>"
        "<section class='card'><h2>Konten</h2><div class='table-wrap'><table><thead><tr><th>Benutzer</th><th>Name</th><th>Rolle</th><th>Status</th><th>Angelegt</th><th>Letzte Anmeldung</th><th>Aktion</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
        "<section class='card'><h2>Offene Rollenanträge</h2><div class='table-wrap'><table><thead><tr><th>ID</th><th>Benutzer</th><th>Rollenwechsel</th><th>Grund</th><th>Zeit</th><th>Entscheidung</th></tr></thead>"
        f"<tbody>{role_rows}</tbody></table></div><p class='warning'>Nur der Eigentümer darf Administratorrechte vergeben oder Administratorkonten deaktivieren.</p></section>"
        "<section class='card'><h2>API-Schlüsselkontrolle</h2><div class='table-wrap'><table><thead><tr><th>Benutzer</th><th>Name</th><th>Präfix</th><th>Rechte</th><th>Läuft ab</th><th>Zuletzt genutzt</th><th>Status</th><th>Aktion</th></tr></thead>"
        f"<tbody>{api_rows}</tbody></table></div></section>",
        message=message,
    )


def _account_page(store: PortalStore, user: dict[str, Any], message: str = "") -> str:
    key_rows = "".join(
        f"<tr><td>{_safe(item['name'])}</td><td><code>{_safe(item['prefix'])}…</code></td><td>{_safe(item['scopes'])}</td>"
        f"<td>{_safe(item['expires_at'])}</td><td>{_safe(item['last_used_at'])}</td><td>{_badge('REVOKED' if item['revoked_at'] else 'ACTIVE')}</td>"
        "<td><form class='inline' method='post' action='/account/api-key/revoke'><input type='hidden' name='csrf' value='__CSRF__'>"
        f"<input type='hidden' name='key_id' value='{item['id']}'><button>Widerrufen</button></form></td></tr>"
        for item in store.list_api_keys(int(user["id"]))
    ) or "<tr><td colspan='7'>Keine API-Schlüssel.</td></tr>"
    scope_boxes = "".join(
        f"<label class='check'><input type='checkbox' name='scope_{scope}' value='1'>{scope}</label>" for scope in sorted(API_SCOPES)
    )
    return _layout(
        "Eigenes Konto",
        user,
        f"<section class='card'><dl><dt>Benutzer</dt><dd>{_safe(user['username'])}</dd><dt>Rolle</dt><dd>{_safe(user['role'])}</dd><dt>Eigentümer</dt><dd>{'Ja' if user.get('is_owner') else 'Nein'}</dd></dl>"
        "<h2>Passwort ändern</h2><form method='post' action='/account/password'><input type='hidden' name='csrf' value='__CSRF__'>"
        "<label>Aktuelles Passwort<input type='password' name='current' autocomplete='current-password' required></label>"
        "<label>Neues Passwort<input type='password' name='password' autocomplete='new-password' minlength='14' required></label>"
        "<label>Wiederholen<input type='password' name='confirm' autocomplete='new-password' minlength='14' required></label>"
        "<button class='primary'>Passwort ändern</button></form></section>"
        "<section class='card'><h2>Höhere Rolle beantragen</h2><p>Die gewünschte Rolle wird erst nach einer begründeten Administratorfreigabe wirksam. Danach ist eine neue Anmeldung erforderlich.</p>"
        "<form method='post' action='/account/role-request'><input type='hidden' name='csrf' value='__CSRF__'>"
        "<label>Gewünschte Rolle<select name='requested_role'><option>operator</option><option>admin</option></select></label>"
        "<label>Begründung<textarea name='reason' maxlength='2000' required></textarea></label><button>Rolle beantragen</button></form></section>"
        "<section class='card'><h2>Persönliche API-Schlüssel</h2><p>Schlüssel werden nur einmal vollständig angezeigt, gehasht gespeichert und können keine Freigaben erteilen.</p>"
        "<form method='post' action='/account/api-key'><input type='hidden' name='csrf' value='__CSRF__'>"
        "<label>Name<input name='name' maxlength='120' required></label><label>Gültigkeit in Tagen<input type='number' name='days' min='1' max='365' value='30' required></label>"
        f"<div class='scope-grid'>{scope_boxes}</div><button>API-Schlüssel erzeugen</button></form></section>"
        "<section class='card'><div class='table-wrap'><table><thead><tr><th>Name</th><th>Präfix</th><th>Rechte</th><th>Läuft ab</th><th>Zuletzt genutzt</th><th>Status</th><th>Aktion</th></tr></thead>"
        f"<tbody>{key_rows}</tbody></table></div></section>",
        message=message,
    )


def _audit_page(store: PortalStore, user: dict[str, Any]) -> str:
    rows = "".join(
        f"<tr><td>{_safe(item['created_at'])}</td><td>{_safe(item['username'] or 'system')}</td><td>{_safe(item['event'])}</td>"
        f"<td>{_safe(item['subject'])}</td><td><code>{_safe(item['details_json'])}</code></td></tr>"
        for item in store.audit_events()
    ) or "<tr><td colspan='5'>Keine Ereignisse.</td></tr>"
    return _layout(
        "Auditprotokoll",
        user,
        "<section class='card'><div class='table-wrap'><table><thead><tr><th>Zeit</th><th>Akteur</th><th>Ereignis</th><th>Objekt</th><th>Details</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>",
    )


def _register_page(info: dict[str, Any] | None, token: str, message: str = "") -> str:
    if not info:
        return _layout("Einladung", None, "<section class='auth card'><p>Diese Einladung ist ungültig oder abgelaufen.</p></section>")
    reset = info["kind"] == "reset"
    username = str(info.get("target_username") or "")
    username_field = f"<input name='username' value='{_safe(username)}' readonly>" if reset else "<input name='username' autocomplete='username' required>"
    return _layout(
        "Passwort zurücksetzen" if reset else "Mitgliedskonto anlegen",
        None,
        "<section class='auth card'><form method='post' action='/register'>"
        f"<input type='hidden' name='token' value='{_safe(token)}'><label>Benutzername{username_field}</label>"
        "<label>Anzeigename<input name='display_name'></label>"
        "<label>Eigenes Passwort<input type='password' name='password' autocomplete='new-password' minlength='14' required></label>"
        "<label>Wiederholen<input type='password' name='confirm' autocomplete='new-password' minlength='14' required></label>"
        "<button class='primary'>Speichern</button></form></section>",
        message=message,
    )


def _css() -> str:
    return """
:root{color-scheme:dark;--bg:#071019;--panel:#0d1824;--line:#223447;--text:#e8f0f7;--muted:#91a4b7;--blue:#60a5fa;--green:#42d392;--yellow:#f7c76b;--red:#ff7373}*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#071019,#09131e 55%,#071623);color:var(--text);font:14px Inter,Segoe UI,sans-serif}a{color:#8fc5ff;text-decoration:none}a:hover{text-decoration:underline}header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:22px;padding:13px 24px;background:rgba(7,16,25,.96);border-bottom:1px solid var(--line)}.brand{display:flex;align-items:center;gap:9px;color:var(--text)}.brand b{font-size:20px}.brand span{font-size:10px;letter-spacing:.18em;color:var(--muted)}nav{display:flex;align-items:center;gap:13px;flex:1;overflow-x:auto}nav a{white-space:nowrap}.identity{text-align:right}.identity small{display:block;color:var(--muted)}main{max-width:1500px;margin:auto;padding:30px 24px 60px}.page-head,.section-head{display:flex;justify-content:space-between;gap:18px;align-items:center;margin-bottom:20px}.eyebrow{color:var(--blue);font-size:11px;font-weight:800;letter-spacing:.15em}.page-head h1{margin:4px 0;font-size:30px}.safety{padding:9px 12px;border:1px solid #28624b;border-radius:8px;background:#10261f;color:var(--green);font-size:11px;font-weight:800}.card,.metric{padding:20px;background:rgba(13,24,36,.96);border:1px solid var(--line);border-radius:12px;box-shadow:0 12px 36px rgba(0,0,0,.18);margin-bottom:18px}.grid{display:grid;gap:14px}.metrics{grid-template-columns:repeat(5,minmax(0,1fr))}.two{grid-template-columns:repeat(2,minmax(0,1fr))}.detail-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.metric span{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.metric strong{display:block;margin-top:9px;font-size:22px}.badge{display:inline-block;padding:5px 8px;border-radius:999px;border:1px solid var(--line);font:700 11px ui-monospace,monospace}.badge--green{color:var(--green);background:#0d2a21}.badge--yellow{color:var(--yellow);background:#2a2414}.badge--red{color:var(--red);background:#30191c}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:11px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}label{display:block;margin:13px 0;color:var(--muted);font-size:12px}input,textarea,select{display:block;width:100%;margin-top:6px;padding:11px;border:1px solid var(--line);border-radius:7px;background:#07111b;color:var(--text)}textarea{min-height:105px;resize:vertical}button,.button{display:inline-block;padding:9px 12px;border:1px solid var(--line);border-radius:7px;background:#142438;color:var(--text);cursor:pointer}.primary{background:#1769aa;border-color:#2b82c8}.inline{display:inline}.inline button{padding:6px 8px}.check{display:flex;align-items:center;gap:8px;margin:6px 0}.check input{width:auto;margin:0}.scope-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5px}.auth{max-width:520px;margin:50px auto}.alert{margin-bottom:18px;padding:12px;border:1px solid var(--yellow);border-radius:8px;background:#2a2414}.warning{color:var(--yellow)}pre{overflow:auto;max-height:650px;padding:15px;background:#060c12;border:1px solid var(--line);border-radius:8px;white-space:pre-wrap;word-break:break-word;font:12px ui-monospace,monospace}.flow{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.flow span{padding:8px 10px;border:1px solid var(--line);border-radius:7px;background:#08121d}.flow b{color:var(--blue)}dl{display:grid;grid-template-columns:140px 1fr;gap:8px}dt{color:var(--muted)}dd{margin:0}footer{padding:20px;text-align:center;color:var(--muted);font-size:10px;border-top:1px solid var(--line)}@media(max-width:1000px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:720px){header{align-items:flex-start;flex-wrap:wrap}.identity{display:none}nav{order:3;width:100%}.page-head,.section-head{align-items:flex-start;flex-direction:column}.metrics,.two,.detail-grid,.scope-grid{grid-template-columns:1fr}.safety{font-size:9px}main{padding:22px 14px}.card,.metric{padding:15px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""


def _handler(config: PortalConfig, store: PortalStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "TIMControl/1.0"
        login_attempts: dict[str, list[float]] = {}

        def log_message(self, format: str, *args: Any) -> None:
            print(f"{self.address_string()} {redact_text(format % args, 1000)}", flush=True)

        def _host_allowed(self) -> bool:
            value = self.headers.get("Host", "")
            if not value or any(character in value for character in "@/?#\\\r\n"):
                return False
            host = value.rsplit(":", 1)[0].strip("[]").lower()
            return host in {item.lower() for item in config.allowed_hosts}

        def _headers(self, status: int, content_type: str, length: int, *, cookie: str | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()

        def _send(self, body: str, status: int = 200, *, content_type: str = "text/html; charset=utf-8", cookie: str | None = None, csrf: str | None = None) -> None:
            if csrf:
                body = body.replace("__CSRF__", _safe(csrf))
            payload = body.encode("utf-8")
            self._headers(status, content_type, len(payload), cookie=cookie)
            self.wfile.write(payload)

        def _send_json(self, value: Any, status: int = 200) -> None:
            self._send(json.dumps(value, ensure_ascii=False, sort_keys=True), status, content_type="application/json; charset=utf-8")

        def _redirect(self, location: str, *, cookie: str | None = None) -> None:
            self.send_response(303)
            self.send_header("Location", location)
            self.send_header("Cache-Control", "no-store")
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()

        def _cookie(self, name: str) -> str | None:
            value = SimpleCookie(self.headers.get("Cookie", ""))
            return value[name].value if name in value else None

        def _auth(self) -> tuple[dict[str, Any], str, str] | None:
            raw = self._cookie("tim_session")
            result = store.session_user(raw)
            return (result[0], result[1], raw or "") if result else None

        def _api_auth(self, scope: str) -> dict[str, Any] | None:
            authorization = self.headers.get("Authorization", "")
            if not authorization.startswith("Bearer "):
                return None
            raw = authorization.removeprefix("Bearer ").strip()
            return store.authenticate_api_key(raw, scope) if raw else None

        def _form(self) -> dict[str, str]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Ungültige Anfrage.") from exc
            if length <= 0 or length > MAX_FORM_BYTES:
                raise ValueError("Ungültige Formulargröße.")
            raw = self.rfile.read(length).decode("utf-8")
            return {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}

        def _json_body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Ungültige Anfrage.") from exc
            if length <= 0 or length > MAX_FORM_BYTES:
                raise ValueError("Ungültige JSON-Größe.")
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("Ein JSON-Objekt ist erforderlich.")
            return value

        @staticmethod
        def _require_role(user: dict[str, Any], role: str) -> None:
            if ROLE_LEVEL.get(str(user.get("role")), -1) < ROLE_LEVEL[role]:
                raise PermissionError("Diese Rolle darf die Aktion nicht ausführen.")

        def _require_csrf(self, values: dict[str, str], expected: str) -> None:
            if not secrets.compare_digest(values.get("csrf", ""), expected):
                raise PermissionError("Ungültiger CSRF-Schutzwert.")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/healthz":
                self._send('{"status":"ok"}', content_type="application/json")
                return
            if parsed.path == "/static/app.css":
                self._send(_css(), content_type="text/css; charset=utf-8")
                return
            if not self._host_allowed():
                self._send("Misdirected Request", 421, content_type="text/plain; charset=utf-8")
                return
            if parsed.path.startswith("/api/v1/"):
                if parsed.path == "/api/v1/me":
                    api_user = self._api_auth("system:read")
                    if not api_user:
                        self._send_json({"error": "unauthorized"}, 401)
                    else:
                        self._send_json({"username": api_user["username"], "display_name": api_user["display_name"], "role": api_user["role"]})
                    return
                if parsed.path == "/api/v1/changes":
                    api_user = self._api_auth("changes:read")
                    if not api_user:
                        self._send_json({"error": "unauthorized"}, 401)
                    else:
                        self._send_json({"changes": store.list_change_requests()})
                    return
                if parsed.path == "/api/v1/tasks":
                    api_user = self._api_auth("tasks:read")
                    if not api_user:
                        self._send_json({"error": "unauthorized"}, 401)
                    else:
                        self._send_json({"tasks": discover_tasks(config)})
                    return
                self._send_json({"error": "not_found"}, 404)
                return
            if parsed.path == "/bootstrap":
                if not config.allow_bootstrap or store.user_count() or self.client_address[0] not in {"127.0.0.1", "::1"}:
                    self._send("Nicht verfügbar", 403, content_type="text/plain; charset=utf-8")
                else:
                    self._send(_bootstrap_page())
                return
            if parsed.path == "/register":
                token = parse_qs(parsed.query).get("token", [""])[-1]
                self._send(_register_page(store.invite_info(token), token))
                return
            if parsed.path == "/login":
                self._send(_login_page())
                return
            auth = self._auth()
            if not auth:
                self._redirect("/bootstrap" if store.user_count() == 0 else "/login")
                return
            user, csrf, _ = auth
            try:
                if parsed.path == "/":
                    page = _overview(config, user, store)
                elif parsed.path == "/tasks":
                    page = _tasks_page(config, user)
                elif parsed.path.startswith("/tasks/"):
                    task_id = parsed.path.removeprefix("/tasks/")
                    task = task_by_id(config, task_id)
                    if not task:
                        self._send("Task nicht gefunden", 404, content_type="text/plain; charset=utf-8")
                        return
                    page = _task_page(config, store, user, task)
                elif parsed.path == "/submit":
                    self._require_role(user, "operator")
                    page = _submit_page(user)
                elif parsed.path == "/training":
                    page = _training_page(store, user)
                elif parsed.path == "/changes":
                    page = _changes_page(store, user)
                elif parsed.path.startswith("/changes/"):
                    page = _change_page(store, user, int(parsed.path.removeprefix("/changes/")))
                elif parsed.path == "/system":
                    page = _system_page(config, user)
                elif parsed.path == "/onboarding":
                    page = _onboarding_page(user)
                elif parsed.path == "/users":
                    self._require_role(user, "admin")
                    page = _users_page(store, user)
                elif parsed.path == "/audit":
                    self._require_role(user, "admin")
                    page = _audit_page(store, user)
                elif parsed.path == "/account":
                    page = _account_page(store, user)
                else:
                    self._send("Nicht gefunden", 404, content_type="text/plain; charset=utf-8")
                    return
                self._send(page, csrf=csrf)
            except PermissionError as exc:
                self._send(_layout("Zugriff verweigert", user, f"<section class='card'><p>{_safe(exc)}</p></section>"), 403, csrf=csrf)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._host_allowed():
                self._send("Misdirected Request", 421, content_type="text/plain; charset=utf-8")
                return
            try:
                if parsed.path == "/api/v1/tasks":
                    api_user = self._api_auth("tasks:submit")
                    if not api_user or ROLE_LEVEL.get(str(api_user.get("role")), -1) < ROLE_LEVEL["operator"]:
                        self._send_json({"error": "unauthorized"}, 401)
                        return
                    payload = self._json_body()
                    allowed_paths = payload.get("allowed_paths", [])
                    if not isinstance(allowed_paths, list) or not all(isinstance(item, str) for item in allowed_paths):
                        raise ValueError("allowed_paths muss eine Liste aus Pfaden sein.")
                    values = {
                        "objective": str(payload.get("objective", "")),
                        "next_action": str(payload.get("next_action", "")),
                        "risk": str(payload.get("risk", "A1")),
                        "allowed_paths": "\n".join(allowed_paths),
                    }
                    task = create_task(config, values, f"api:{api_user['username']}")
                    store.audit(int(api_user["user_id"]), "API_TASK_SUBMITTED", str(task["task_id"]), {"risk": task["risk"]})
                    self._send_json({"task": task}, 201)
                    return
                values = self._form()
                if parsed.path == "/bootstrap":
                    if not config.allow_bootstrap or store.user_count() or self.client_address[0] not in {"127.0.0.1", "::1"}:
                        raise PermissionError("Bootstrap ist nicht verfügbar.")
                    if values.get("password") != values.get("confirm"):
                        raise ValueError("Die Passwörter stimmen nicht überein.")
                    user = store.create_first_admin(values.get("username", ""), values.get("display_name", ""), values.get("password", ""))
                    raw, _ = store.create_session(int(user["id"]), config.session_hours)
                    self._redirect("/", cookie=self._session_cookie(raw))
                    return
                if parsed.path == "/login":
                    source = self.client_address[0]
                    now = time.monotonic()
                    attempts = [item for item in self.login_attempts.get(source, []) if now - item < 900]
                    if len(attempts) >= 8:
                        self._send(_login_page("Zu viele Versuche. Bitte später erneut versuchen."), 429)
                        return
                    user = store.authenticate(values.get("username", ""), values.get("password", ""))
                    if not user:
                        attempts.append(now)
                        self.login_attempts[source] = attempts
                        self._send(_login_page("Anmeldung fehlgeschlagen."), 401)
                        return
                    self.login_attempts.pop(source, None)
                    raw, _ = store.create_session(int(user["id"]), config.session_hours)
                    self._redirect("/", cookie=self._session_cookie(raw))
                    return
                if parsed.path == "/register":
                    token = values.get("token", "")
                    if values.get("password") != values.get("confirm"):
                        raise ValueError("Die Passwörter stimmen nicht überein.")
                    user = store.redeem_invite(token, values.get("username", ""), values.get("display_name", ""), values.get("password", ""))
                    raw, _ = store.create_session(int(user["id"]), config.session_hours)
                    self._redirect("/", cookie=self._session_cookie(raw))
                    return
                auth = self._auth()
                if not auth:
                    self._redirect("/login")
                    return
                user, csrf, raw = auth
                self._require_csrf(values, csrf)
                if parsed.path == "/logout":
                    store.delete_session(raw)
                    self._redirect("/login", cookie=self._expired_cookie())
                elif parsed.path == "/account/password":
                    if values.get("password") != values.get("confirm"):
                        raise ValueError("Die Passwörter stimmen nicht überein.")
                    store.change_password(int(user["id"]), values.get("current", ""), values.get("password", ""))
                    self._redirect("/login", cookie=self._expired_cookie())
                elif parsed.path == "/account/role-request":
                    store.create_role_request(int(user["id"]), values.get("requested_role", ""), values.get("reason", ""))
                    self._send(_account_page(store, user, "Rollenantrag wurde zur Administratorprüfung eingereicht."), csrf=csrf)
                elif parsed.path == "/submit":
                    self._require_role(user, "operator")
                    task = create_task(config, values, str(user["username"]))
                    store.audit(int(user["id"]), "TASK_SUBMITTED", str(task["task_id"]), {"risk": task["risk"]})
                    self._redirect(f"/tasks/{quote(str(task['task_id']))}")
                elif parsed.path.startswith("/tasks/") and parsed.path.endswith("/feedback"):
                    self._require_role(user, "operator")
                    task_id = parsed.path.removeprefix("/tasks/").removesuffix("/feedback").rstrip("/")
                    task = task_by_id(config, task_id)
                    if not task:
                        raise ValueError("Task nicht gefunden.")
                    verdict, notes = values.get("verdict", ""), values.get("notes", "")
                    if verdict == "APPROVED_FOR_LEARNING":
                        self._require_role(user, "admin")
                    store.add_feedback(task_id, int(user["id"]), verdict, notes)
                    if verdict == "APPROVED_FOR_LEARNING":
                        append_approved_experience(config, task, str(user["username"]), notes)
                    self._redirect(f"/tasks/{quote(task_id)}")
                elif parsed.path == "/training":
                    self._require_role(user, "operator")
                    store.create_campaign(int(user["id"]), values.get("name", ""), values.get("hypothesis", ""), values.get("metrics", ""), values.get("dataset_query", ""))
                    self._redirect("/training")
                elif parsed.path == "/changes":
                    self._require_role(user, "operator")
                    change_id = store.create_change_request(
                        int(user["id"]), values.get("title", ""), values.get("category", ""), values.get("reason", ""),
                        values.get("proposed_change", ""), values.get("resource_impact", ""), values.get("rollback_plan", ""),
                    )
                    self._redirect(f"/changes/{change_id}")
                elif parsed.path.startswith("/changes/") and parsed.path.endswith("/vote"):
                    self._require_role(user, "operator")
                    change_id = int(parsed.path.removeprefix("/changes/").removesuffix("/vote").rstrip("/"))
                    store.vote_change(change_id, int(user["id"]), values.get("vote", ""), values.get("reason", ""))
                    self._redirect(f"/changes/{change_id}")
                elif parsed.path.startswith("/changes/") and parsed.path.endswith("/decide"):
                    self._require_role(user, "admin")
                    change_id = int(parsed.path.removeprefix("/changes/").removesuffix("/decide").rstrip("/"))
                    store.decide_change(change_id, int(user["id"]), values.get("decision", ""), values.get("reason", ""))
                    self._redirect(f"/changes/{change_id}")
                elif parsed.path == "/account/api-key":
                    scopes = {scope for scope in API_SCOPES if values.get(f"scope_{scope}") == "1"}
                    raw_key = store.create_api_key(int(user["id"]), values.get("name", ""), scopes, int(values.get("days", "30")))
                    self._send(_account_page(store, user, f"API-Schlüssel – nur jetzt kopieren: {raw_key}"), csrf=csrf)
                elif parsed.path == "/account/api-key/revoke":
                    store.revoke_api_key(int(user["id"]), int(values.get("key_id", "0")))
                    self._redirect("/account")
                elif parsed.path == "/admin/invite":
                    self._require_role(user, "admin")
                    token = store.create_invite(int(user["id"]), "viewer")
                    message = f"Einmaliger Link: /register?token={token}"
                    self._send(_users_page(store, user, message), csrf=csrf)
                elif parsed.path == "/admin/reset":
                    self._require_role(user, "admin")
                    token = store.create_invite(int(user["id"]), "viewer", kind="reset", target_username=values.get("username", ""))
                    message = f"Einmaliger Reset-Link: /register?token={token}"
                    self._send(_users_page(store, user, message), csrf=csrf)
                elif parsed.path == "/admin/user-status":
                    self._require_role(user, "admin")
                    store.set_user_active(int(user["id"]), int(values.get("user_id", "0")), values.get("active") == "1")
                    self._redirect("/users")
                elif parsed.path == "/admin/role-request":
                    self._require_role(user, "admin")
                    store.decide_role_request(int(values.get("request_id", "0")), int(user["id"]), values.get("decision", ""), values.get("reason", ""))
                    self._redirect("/users")
                elif parsed.path == "/admin/api-key/revoke":
                    self._require_role(user, "admin")
                    store.admin_revoke_api_key(int(user["id"]), int(values.get("key_id", "0")))
                    self._redirect("/users")
                else:
                    self._send("Nicht gefunden", 404, content_type="text/plain; charset=utf-8")
            except PermissionError as exc:
                self._send(str(exc), 403, content_type="text/plain; charset=utf-8")
            except (ValueError, sqlite3.IntegrityError) as exc:
                self._send(_layout("Eingabe prüfen", None, f"<section class='auth card'><p>{_safe(exc)}</p><p><a href='/'>Zurück</a></p></section>"), 400)

        def _session_cookie(self, raw: str) -> str:
            secure = "; Secure" if config.cookie_secure else ""
            return f"tim_session={raw}; Path=/; HttpOnly; SameSite=Strict; Max-Age={config.session_hours * 3600}{secure}"

        def _expired_cookie(self) -> str:
            secure = "; Secure" if config.cookie_secure else ""
            return f"tim_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure}"

    return Handler


class PortalServer:
    def __init__(self, config: PortalConfig) -> None:
        if config.host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Das Portal muss hinter einem Reverse Proxy an Loopback gebunden bleiben.")
        if config.allow_bootstrap and (config.cookie_secure or
                any(host not in {"127.0.0.1", "localhost", "::1"} for host in config.allowed_hosts)):
            raise ValueError("Bootstrap is allowed only for explicit local setup without a proxy hostname.")
        target = urlparse(config.ollama_url)
        if (target.scheme != "http" or target.hostname not in {"127.0.0.1", "127.0.0.2", "localhost", "::1"}
                or target.username or target.password or target.path not in {"", "/"}
                or target.query or target.fragment):
            raise ValueError("Ollama monitoring must use a loopback HTTP endpoint.")
        self.config = config
        self.store = PortalStore(config.db_path)
        self.server = ThreadingHTTPServer((config.host, config.port), _handler(config, self.store))
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        if self.thread:
            self.thread.join(timeout=3)
