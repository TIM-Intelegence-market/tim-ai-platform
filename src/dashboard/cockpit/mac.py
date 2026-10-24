"""Data model of the cockpit area "Mac jetzt": what the Mac mini is working on.

Read only. Sources are what the Mac already writes or serves:

* the issue worker's own dashboard (``/api/status`` on 127.0.0.1:8767),
* the status files of the background services in ``data/operational/``,
* the trading team's state in ``~/TIM-trading-team/state/trading-team/``.

Nothing here starts, stops or changes a service. A service without a fresh
status file is shown with its age, not guessed as running.
"""

from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from src.dashboard.cockpit.lage import _broken, _read_json, _system_tiles
from src.dashboard.cockpit.sources import BudgetedSources, SourceResult
from src.dashboard.cockpit.tiles import Tile, attention, human_age, make_tile, state_of, unavailable, worst
from src.dashboard.state import DashboardState

SCHEMA = "tim_cockpit_mac/1"
LOCAL = ZoneInfo("Europe/Berlin")
WORKER_STATUS_URL = "http://127.0.0.1:8767/api/status"
WORKER_TIMEOUT = 1.2
WORKER_MAX_BYTES = 4_000_000
WORKER_MAX_AGE = 180
WORKER_ERROR_RECENT = 3600  # an older worker error is history, not a current problem
TRADING_TEAM_DIR = Path.home() / "TIM-trading-team" / "state" / "trading-team"
OPEN_ISSUES_SHOWN = 8
DONE_SHOWN = 6
EVENTS_SHOWN = 8
GITHUB = "https://github.com/"
ISSUE_URL = "https://github.com/TIM-Intelegence-market/tim-ai-platform/issues/{}"

# (file, label, timestamp key, freshness limit in seconds, href). Limits are the
# launchd interval plus slack: readiness and server health every 60 s, history
# recovery every 30 s, the validator cycle every 60 s, the dashboard agent every 10 min.
SERVICES = (
    ("research_cycle_latest.json", "validator", "Validator", "check_timestamp", 300, "/health"),
    ("server_health.json", "server_health", "Server-Health", "timestamp", 300, "/health"),
    ("history_recovery.json", "history_recovery", "Lückenreparatur", "checked_at", 180, "/gaps"),
    ("readiness_inputs.json", "readiness_inputs", "Readiness-Eingaben", "checked_at", 300, "/v2-readiness"),
    ("dashboard_refresh.json", "dashboard_refresh", "Dashboard-Agent", "checked_at_utc", 1800, "/audit-evidence"),
)
SERVICE_STATUS = {"GREEN": "PASS", "HEALTHY": "PASS", "CRITICAL": "FAIL", "AMBER": "WARN", "YELLOW": "WARN", "RED": "FAIL", "DEGRADED": "WARN"}
AGENT_FAIL = {"ci_failed", "previous_attempt_failed"}

_SOURCES = BudgetedSources()


def worker_url() -> str:
    return os.environ.get("TIM_WORKER_STATUS_URL") or WORKER_STATUS_URL


def trading_team_dir() -> Path:
    value = os.environ.get("TIM_TRADING_TEAM_STATE")
    return Path(value).expanduser() if value else TRADING_TEAM_DIR


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - urllib API
        raise ValueError(f"Worker-Status leitet um ({code}), wird nicht verfolgt")


def fetch_worker(url: str | None = None, timeout: float = WORKER_TIMEOUT) -> dict[str, Any]:
    """GET the worker dashboard status. Loopback only, never through a proxy."""
    url = url or worker_url()
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Worker-Status nur über 127.0.0.1")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
        value = json.loads(response.read(WORKER_MAX_BYTES))
    if not isinstance(value, dict):
        raise ValueError("Worker-Status ist kein JSON-Objekt")
    return value


def _epoch_iso(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    try:
        moment = datetime.fromtimestamp(float(value), timezone.utc)
        return moment.isoformat() if moment.year < 9999 else None
    except (OverflowError, OSError, ValueError):
        return None


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _seconds(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return int(value)


def _link(url: Any) -> str:
    text = str(url or "")
    return text if text.startswith(GITHUB) else ""


def _issue_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"#?[0-9]{1,9}", value.strip()):
        return int(value.strip().lstrip("#"))
    if isinstance(value, dict):
        for key in ("issue", "number", "issue_number"):
            number = _issue_number(value.get(key))
            if number is not None:
                return number
    return None


def _trading_team(directory: Path) -> dict[str, Any]:
    state_path = directory / "state.json"
    if not state_path.exists():
        return {"exists": False, "directory": str(directory)}
    state = _read_json(state_path)
    last_run, summary = None, ""
    log = directory / "run.log"
    try:
        with log.open("rb") as handle:
            handle.seek(max(0, log.stat().st_size - 8000))
            tail = handle.read().decode("utf-8", "replace").splitlines()
    except OSError:
        tail = []
    for line in reversed(tail):
        match = re.match(r"--- Lauf (\S+) ---", line.strip())
        if match:
            last_run = match.group(1)
            break
    for line in reversed(tail):
        if line.startswith("Papier-Bot:"):
            summary = line.removeprefix("Papier-Bot:").strip()
            break
    try:
        written = datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        written = None
    return {"exists": True, "state": state, "last_run": last_run, "state_written": written, "summary": summary}


def _jobs(state: DashboardState) -> dict[str, Any]:
    operational = state.operational_watchdog_path.parent
    jobs: dict[str, Any] = {
        "worker": fetch_worker,
        "snapshot": state.snapshot,
        "backup": lambda: _read_json(operational / "backup_last_run.json"),
        "server_health_raw": lambda: _read_json(operational / "server_health.json"),
        "trading_team": lambda: _trading_team(trading_team_dir()),
    }
    for filename, key, *_ in SERVICES:
        jobs[f"svc_{key}"] = (lambda path=operational / filename: _read_json(path))
    return jobs


# --- issue worker -----------------------------------------------------------

def _current(data: dict[str, Any]) -> dict[str, Any] | None:
    worker = data.get("worker") if isinstance(data.get("worker"), dict) else {}
    current = data.get("current")
    if isinstance(current, dict) and current:
        return current
    issue = worker.get("current_issue")
    if issue not in (None, "", {}):
        return issue if isinstance(issue, dict) else {"issue": issue}
    return None


def worker_tiles(result: SourceResult, now: datetime) -> tuple[list[Tile], dict[str, Any]]:
    """Tiles and lists of the issue worker. Returns (tiles, details)."""
    source = "Issue-Worker-Dashboard 127.0.0.1:8767/api/status"
    href = "/neu/mac#worker"
    if not result.ok:
        reason = f"Worker-Dashboard antwortet nicht: {result.reason()}"
        return ([unavailable("worker", "Issue-Worker", reason, source, href),
                 unavailable("ci_runner", "CI-Runner", "Unbekannt: der Issue-Worker meldet, ob ein CI-Lauf läuft", source, href)],
                {"reachable": False, "error": reason})
    data = result.value or {}
    if not isinstance(data.get("worker"), dict):
        reason = "Worker-Dashboard liefert ein unbekanntes Format (Feld worker fehlt)"
        return ([unavailable("worker", "Issue-Worker", reason, source, href),
                 unavailable("ci_runner", "CI-Runner", reason, source, href)], {"reachable": False, "error": reason})
    worker = data["worker"]
    agent = worker.get("agent") if isinstance(worker.get("agent"), dict) else {}
    log = data.get("log") if isinstance(data.get("log"), dict) else {}
    as_of = _epoch_iso(data.get("generated_at"))
    current = _current(data)
    number = _issue_number(current) if current else None
    paused_ci = worker.get("paused_ci") is True
    open_items = _list(data.get("open"))
    match = next((item for item in open_items if number is not None and _issue_number(item.get("number")) == number), {})
    developer = worker.get("developer") if isinstance(worker.get("developer"), dict) else {}
    phase = str(developer.get("phase") or (current or {}).get("phase") or "")
    title = str((current or {}).get("title") or match.get("title") or "")
    url = _link(match.get("url")) or (ISSUE_URL.format(number) if number is not None else "")
    if current:
        value = f"arbeitet an #{number}" if number is not None else "arbeitet an einem Issue"
        since = _epoch_iso((current or {}).get("worktree_created_at") or (current or {}).get("started_at"))
        started = f"seit {datetime.fromisoformat(since).astimezone(LOCAL):%H:%M} Uhr" if since else ""
        detail = " · ".join(part for part in (title[:120], phase, started) if part)
    elif paused_ci:
        value, detail = "pausiert", "Ein CI-Testlauf läuft auf dem Mac; der nächste Auftrag startet danach"
    elif worker.get("run_active") is True:
        value, detail = "arbeitet", phase or "Lauf aktiv"
    else:
        interval = log.get("intake_interval_secs")
        value = "wartet auf Aufgaben"
        detail = f"prüft alle {round(interval / 60)} min auf neue Issues" if isinstance(interval, (int, float)) and interval > 0 else ""
    problems = []
    raw = "PASS"
    if agent.get("running") is not True:
        if agent.get("loaded") is True:
            raw = "WARN"
            problems.append("Worker-Prozess ist geladen, läuft aber gerade nicht")
        else:
            raw = "FAIL"
            problems.append("Worker-Prozess ist nicht geladen (launchd com.tim.local-qwen-worker)")
    github = data.get("github") if isinstance(data.get("github"), dict) else {}
    if worker.get("process_observation_ok") is False:
        raw = "FAIL" if raw == "FAIL" else "WARN"
        problems.append("Prozessstatus nicht abrufbar: ob ein Issue oder CI läuft, ist unbekannt")
    if github and github.get("ok") is False and not github.get("loading"):
        raw = "FAIL" if raw == "FAIL" else "WARN"
        problems.append(f"GitHub nicht erreichbar: {github.get('error') or 'ohne Grund'}")
    error = log.get("last_error") if isinstance(log.get("last_error"), dict) else {}
    error_age = _seconds(error.get("age_estimate_secs"))
    recent_error = error_age is not None and 0 <= error_age <= WORKER_ERROR_RECENT
    if recent_error and error.get("text"):
        raw = "FAIL" if raw == "FAIL" else "WARN"
        problems.append(f"Fehler {human_age(error_age)}: {str(error['text'])[:160]}")
    stalled = _list(data.get("stalled"))
    tiles = [make_tile("worker", "Issue-Worker", value, raw, reason=" · ".join(problems), source=source, as_of=as_of,
                       max_age_seconds=WORKER_MAX_AGE, detail=detail, href=href, now=now)]
    ci_source = "Issue-Worker (paused_ci), Runner mac-mini-tim"
    if paused_ci:
        tiles.append(make_tile("ci_runner", "CI-Runner", "Testlauf läuft", "PASS", source=ci_source, as_of=as_of, max_age_seconds=WORKER_MAX_AGE,
                               href=href, now=now, detail="Während des Laufs keine schwere Arbeit auf dem Mac", extra={"kind": "info"}))
    elif current or agent.get("running") is not True or worker.get("process_observation_ok") is False:
        # The worker only reports a CI run while it is idle and running itself.
        tiles.append(unavailable("ci_runner", "CI-Runner", "Unbekannt: der Issue-Worker meldet CI-Läufe nur, wenn er selbst läuft und kein Issue bearbeitet",
                                 ci_source, href))
    else:
        # Without a reported run the runner is most likely idle, but the worker cannot tell when its CI pause is switched off.
        tiles.append(make_tile("ci_runner", "CI-Runner", "kein Lauf gemeldet", "PASS", source=ci_source, as_of=as_of, max_age_seconds=WORKER_MAX_AGE,
                               href=href, now=now, detail="Der Worker meldet CI-Läufe über seine CI-Pause (Standard: an)", extra={"kind": "info"}))

    eligible = [item for item in open_items if item.get("eligible") is True]
    tiles.append(make_tile("queue", "Warteschlange", f"{len(eligible)} bereit · {len(open_items)} offen", "PASS",
                           source=source, as_of=as_of, max_age_seconds=WORKER_MAX_AGE, href=href, now=now,
                           detail="bereit = Labels agent:qwen-ready und status:ready", extra={"kind": "info"}))
    done = sorted(_list(data.get("done")),
                  key=lambda item: str(item.get("merged_at") or item.get("closed_at") or item.get("pr_created_at") or ""), reverse=True)
    merged = [item for item in done if str(item.get("state") or "").upper() == "MERGED"]
    if merged:
        last = merged[0]
        pr = last.get("pr_number")
        tiles.append(make_tile("last_done", "Zuletzt erledigt", f"#{last.get('issue')}" + (f" → PR #{pr}" if pr else ""), "PASS",
                               source=source, as_of=last.get("merged_at") or last.get("closed_at"), href=href, now=now,
                               detail=str(last.get("title") or "")[:140], extra={"kind": "info"}))
    else:
        tiles.append(unavailable("last_done", "Zuletzt erledigt", "Noch kein gemergter Worker-PR im Verlauf", source, href))
    ollama = worker.get("ollama") if isinstance(worker.get("ollama"), dict) else {}
    if ollama:
        ok = ollama.get("reachable") is True and ollama.get("model_installed") is True
        tiles.append(make_tile("model", "Lokales Modell", str(ollama.get("model") or "—"), "PASS" if ok else "WARN",
                               reason="" if ok else ("Ollama nicht erreichbar" if ollama.get("reachable") is not True else "Modell nicht installiert"),
                               source="Ollama auf dem Mac", href=href, now=now))

    events = []
    if current:
        for event in _list(current.get("events"))[-EVENTS_SHOWN:]:
            if event:
                events.append({"at": _epoch_iso(event.get("at")), "phase": str(event.get("phase") or ""),
                               "place": str(event.get("place") or ""), "detail": str(event.get("detail") or "")[:240]})
    details = {
        "reachable": True,
        "current": {"issue": number, "title": title, "url": url, "phase": phase, "events": events} if current else None,
        "stalled": [_issue_number(item) for item in stalled][:10],
        "paused_ci": paused_ci,
        "last_intake": str((log.get("last_intake") or {}).get("output") or "")[:240] if isinstance(log.get("last_intake"), dict) else "",
        "last_triage": str((log.get("last_triage") or {}).get("text") or "")[:300] if isinstance(log.get("last_triage"), dict) else "",
        "last_error": ({"text": str(error.get("text") or "")[:300], "age": human_age(error_age) if error_age is not None else "Alter unbekannt",
                        "recent": recent_error} if error.get("text") else None),
        "open": [{"number": item.get("number"), "title": str(item.get("title") or "")[:160], "url": _link(item.get("url")),
                  "eligible": item.get("eligible") is True, "stage": str(item.get("stage") or ""),
                  "waiting": str(item.get("waiting_reason") or "")[:200]}
                 for item in sorted(open_items, key=lambda item: (item.get("eligible") is not True, -(_issue_number(item.get("number")) or 0)))[:OPEN_ISSUES_SHOWN]],
        "open_total": len(open_items),
        "done": [{"issue": item.get("issue"), "title": str(item.get("title") or "")[:160], "pr": item.get("pr_number"),
                  "url": _link(item.get("pr_url")), "state": str(item.get("state") or ""),
                  "at": item.get("merged_at") or item.get("closed_at"), "helpers": [str(h) for h in item.get("helpers")][:4] if isinstance(item.get("helpers"), list) else []}
                 for item in done[:DONE_SHOWN]],
    }
    return tiles, details


# --- background services ----------------------------------------------------

def _service_tile(key: str, label: str, report: SourceResult, stamp_key: str, max_age: int, href: str, filename: str, now: datetime) -> Tile:
    source = f"data/operational/{filename}"
    if not report.ok:
        return unavailable(key, label, report.reason(), source, href)
    data = report.value or {}
    if not data:
        return unavailable(key, label, "Noch kein Statusbericht geschrieben", source, href)
    stamp = data.get(stamp_key)
    if key == "dashboard_refresh":
        decision = data.get("decision") if isinstance(data.get("decision"), dict) else {}
        action, reason = str(decision.get("action") or "UNKNOWN"), str(decision.get("reason") or "")
        raw = "FAIL" if reason in AGENT_FAIL else "WARN" if action == "HOLD" else "PASS" if action in {"UP_TO_DATE", "DEPLOY", "WAIT"} else "WARN"
        commit = str(data.get("deployed_commit") or "")[:7]
        return make_tile(key, label, {"UP_TO_DATE": "aktuell", "DEPLOY": "spielt auf", "WAIT": "wartet", "HOLD": "angehalten"}.get(action, action),
                         raw, reason="" if raw == "PASS" else str(decision.get("text") or reason), source=source, as_of=stamp,
                         max_age_seconds=max_age, href=href, now=now,
                         detail=(str(decision.get("text") or "") + (f" · läuft auf {commit}" if commit else "")).strip(" ·"))
    if key == "validator":
        status = str(data.get("overall_status") or "UNKNOWN").upper()
        raw = SERVICE_STATUS.get(status, status)
        failed = [str(item.get("check") if isinstance(item, dict) else item) for item in data.get("failed_checks") or []] if isinstance(data.get("failed_checks"), list) else []
        return make_tile(key, label, f"{data.get('checks_pass', '—')}/{data.get('checks_total', '—')} grün", raw,
                         reason="" if state_of(raw) == "ok" else f"{status}: " + (", ".join(failed[:4]) or "ohne Angabe"),
                         source=source, as_of=stamp, max_age_seconds=max_age, href=href, now=now,
                         detail=f"Zyklus {data.get('validator_cycle', '—')}")
    status = str(data.get("status") or "UNKNOWN").upper()
    reasons = []
    checks = data.get("checks")
    if isinstance(checks, dict):
        for name, check in checks.items():
            word = str(check.get("status", "")).upper() if isinstance(check, dict) else ""
            if word and word not in {"GREEN", "PASS", "OK"}:
                reasons.append(f"{name}: {check.get('reason') or word}")
    errors = data.get("errors")
    if isinstance(errors, list) and errors:
        reasons.append(f"{len(errors)} Fehler im letzten Lauf")
    words = {"PASS": "läuft", "GREEN": "läuft", "AMBER": "gelb", "YELLOW": "gelb", "RED": "rot", "FAIL": "Fehler"}
    return make_tile(key, label, words.get(status, status), SERVICE_STATUS.get(status, status),
                     reason="; ".join(reasons[:3]) or ("" if status in {"PASS", "GREEN"} else f"meldet {status}"),
                     source=source, as_of=stamp, max_age_seconds=max_age, href=href, now=now)


def _trading_team_tile(result: SourceResult, now: datetime) -> Tile:
    source = "~/TIM-trading-team/state/trading-team"
    if not result.ok:
        return unavailable("trading_team", "Trading-Team", result.reason(), source, "/neu/mac#dienste")
    data = result.value or {}
    if not data.get("exists"):
        return unavailable("trading_team", "Trading-Team", "Kein Trading-Team auf diesem Rechner (state.json fehlt)", source, "/neu/mac#dienste")
    state = data.get("state") if isinstance(data.get("state"), dict) else {}
    if not state:
        return make_tile("trading_team", "Trading-Team", "—", "WARN", reason="state.json leer oder nicht lesbar", source=source,
                         as_of=data.get("state_written"), href="/neu/mac#dienste", now=now)
    mode = str(state.get("mode") or "")
    open_count = len(state["open"]) if isinstance(state.get("open"), list) else 0
    shadow = len(state["shadow_open"]) if isinstance(state.get("shadow_open"), list) else 0
    raw, reason = "PASS", ""
    if mode != "PAPER_ONLY":
        raw, reason = "FAIL", f"Modus {mode or 'fehlt'}, erwartet PAPER_ONLY"
    # state.json is written at the end of a run, so its time shows the last finished run.
    return make_tile("trading_team", "Trading-Team", f"{open_count} offen · {shadow} Schatten", raw, reason=reason,
                     source=source + " (nur Papier)", as_of=data.get("state_written"), max_age_seconds=900, href="/neu/mac#dienste", now=now,
                     detail=str(data.get("summary") or "")[:200])


def service_tiles(results: dict[str, SourceResult], now: datetime) -> list[Tile]:
    tiles: list[Tile] = []
    picked = {"runtime", "watchdog", "backup"}
    try:
        system = _system_tiles(results["snapshot"], results["backup"], results["server_health_raw"], now)
        tiles += [tile for tile in system if tile.id in picked]
    except Exception as exc:  # noqa: BLE001 - unexpected data shape: grey tiles with the reason
        tiles += [unavailable(key, label, _broken(exc), "Kachelbau Dienste", href) for key, label, href in
                  (("runtime", "TIM-Laufzeit", "/runtime"), ("watchdog", "Watchdog", "/health"), ("backup", "Backup", "/timeline"))]
    for filename, key, label, stamp_key, max_age, href in SERVICES:
        try:
            tiles.append(_service_tile(key, label, results[f"svc_{key}"], stamp_key, max_age, href, filename, now))
        except Exception as exc:  # noqa: BLE001
            tiles.append(unavailable(key, label, _broken(exc), f"data/operational/{filename}", href))
    try:
        tiles.append(_trading_team_tile(results["trading_team"], now))
    except Exception as exc:  # noqa: BLE001
        tiles.append(unavailable("trading_team", "Trading-Team", _broken(exc), "~/TIM-trading-team", "/neu/mac#dienste"))
    for tile in tiles:
        if tile.id == "backup":
            tile.detail = (tile.detail + " · " if tile.detail else "") + "täglich 03:15 Uhr"
    return tiles


def build_mac(state: DashboardState, now: datetime | None = None, budget: float = 1.5, sources: BudgetedSources | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    results = (sources or _SOURCES).run(_jobs(state), budget=budget)
    try:
        worker, details = worker_tiles(results["worker"], now)
    except Exception as exc:  # noqa: BLE001
        worker = [unavailable("worker", "Issue-Worker", _broken(exc), "Issue-Worker-Dashboard", "/neu/mac#worker"),
                  unavailable("ci_runner", "CI-Runner", _broken(exc), "Issue-Worker-Dashboard", "/neu/mac#worker")]
        details = {"reachable": False, "error": _broken(exc)}
    services = service_tiles(results, now)
    needs = attention(worker + services)
    if any(t.state == "fail" for t in needs):
        headline = f"{sum(t.state == 'fail' for t in needs)} Fehler, bitte ansehen"
    elif needs:
        headline = f"{len(needs)} Punkt(e) brauchen einen Blick"
    elif worst([t.state for t in worker + services]) == "ok":
        headline = "Alles läuft"
    else:
        headline = "Nicht alle Quellen liefern Daten"
    now_lines = []
    by_id = {t.id: t for t in worker + services}
    for key in ("ci_runner", "worker", "dashboard_refresh", "trading_team", "backup"):
        tile = by_id.get(key)
        if tile is not None:
            now_lines.append({"label": tile.label, "value": tile.value, "detail": tile.detail if tile.state == "ok" else tile.reason,
                              "state": tile.state, "as_of": tile.as_of, "age_seconds": tile.age_seconds})
    return {
        "schema": SCHEMA,
        "generated_at": now.isoformat(),
        "mode": "OBSERVE",
        "safety": "Nur Anzeige: startet, stoppt und ändert keinen Dienst",
        "headline": headline,
        "overall": "fail" if any(t.state == "fail" for t in needs) else "warn" if needs else worst([t.state for t in worker + services]),
        "now": now_lines,
        "worker": [t.to_dict() for t in worker],
        "worker_details": details,
        "services": [t.to_dict() for t in services],
        "attention": [t.to_dict() for t in needs],
        "sources": {name: {"ok": r.ok, "seconds": r.seconds, "error": r.error, "stale_seconds": r.stale_seconds} for name, r in results.items()},
    }
