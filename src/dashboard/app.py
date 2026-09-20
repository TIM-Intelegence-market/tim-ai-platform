from __future__ import annotations

import html
import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from src.analytics.research import ResearchAnalyticsEngine
from src.insights import ResearchInsightsEngine
from src.research.router import ResearchRouter


DASHBOARD_VERSION = "2.2.1"
VISIBLE_LIMIT = 50
ORDERFLOW_VISIBLE_LIMIT = 100
ALLOWED_TIMELINE_EVENTS = {
    "RUNTIME_START",
    "VALIDATION_CYCLE",
    "RESEARCH_CYCLE_CHECK",
    "ACCEPTANCE_CHECK",
    "CONTROLLED_API_FAILURE",
    "UNCONTROLLED_API_FAILURE",
    "VALIDATOR_RECOVERY",
    "DATA_GAP",
    "RESTART",
}


def _safe(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def _short(value: Any, size: int = 10) -> str:
    text = str(value or "")
    return text[:size] if text else "—"


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _duration(start: Any, end: Any) -> str:
    left, right = _parse_time(start), _parse_time(end)
    if not left or not right or right < left:
        return "—"
    seconds = int((right - left).total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"


def _age_seconds(value: Any) -> str:
    parsed = _parse_time(value)
    if not parsed:
        return f"MISSING:{value!s}" if value not in (None, "") else "MISSING:freshness_seconds"
    age = int((datetime.now(timezone.utc) - parsed).total_seconds())
    return "INVALID:FUTURE_TIMESTAMP" if age < 0 else str(age)


def _json_block(value: Any) -> str:
    return _safe(json.dumps(value if value is not None else {}, indent=2, ensure_ascii=False, sort_keys=True))


def _status(value: Any) -> str:
    normalized = str(value or "UNKNOWN").upper()
    if normalized in {"HEALTHY", "RUNNING", "CONNECTED", "PASS", "GREEN", "TRUE"}:
        return "GREEN"
    if normalized in {"WARNING", "DEGRADED", "PENDING", "WAITING", "MONITORING", "YELLOW", "OPEN_ISSUES", "NOT_READY_FOR_V2"}:
        return "YELLOW"
    return "RED"


@dataclass(slots=True)
class DashboardState:
    market_status: dict[str, Any] = field(default_factory=lambda: {"status": "STARTING"})
    active_observations: list[dict] = field(default_factory=list)
    research_cases: list[dict] = field(default_factory=list)
    orderflow_observations: list[dict] = field(default_factory=list)
    orderflow_validations: list[dict] = field(default_factory=list)
    system_health: dict[str, Any] = field(default_factory=lambda: {
        "database": "unknown",
        "stream": "unknown",
        "queue_depth": 0,
        "queue_model": "DIRECT_AWAIT_NO_APPLICATION_QUEUE",
        "ollama_enabled": False,
        "ollama_availability": "DISABLED_BY_POLICY",
    })
    memory_status: dict[str, Any] = field(default_factory=lambda: {"observations": 0})
    news: dict[str, Any] = field(default_factory=lambda: {"status": "PLACEHOLDER", "items": []})
    recent_candles: list[dict] = field(default_factory=list)
    validator_path: Path = field(default_factory=lambda: Path("data/operational/state.json"))
    events_path: Path = field(default_factory=lambda: Path("data/operational/events.jsonl"))
    readiness_path: Path = field(default_factory=lambda: Path("data/research/status/tim_v1_readiness.json"))
    audit_path: Path = field(default_factory=lambda: Path("data/research/audit/latest.json"))
    quality_path: Path = field(default_factory=lambda: Path("data/research/quality/latest.json"))
    core_manifest_path: Path = field(default_factory=lambda: Path("config/core_manifest.json"))
    governance_roles_path: Path = field(default_factory=lambda: Path("config/governance_roles.json"))
    runtime_started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    lock: threading.Lock = field(default_factory=threading.Lock)
    _timeline_mtime_ns: int = field(default=-1, init=False)
    _timeline_cache: list[dict[str, Any]] = field(default_factory=list, init=False)

    def _validator(self) -> dict[str, Any]:
        try:
            value = json.loads(self.validator_path.read_text())
            return {
                "status": value.get("status", "UNKNOWN"),
                "cycles": int(value.get("cycles", 0)),
                "started_at": value.get("started_at"),
                "last_cycle_at": value.get("last_cycle_at"),
                "deadline": value.get("deadline"),
                "restart_count": int(value.get("restart_count", 0)),
                "acceptance": value.get("acceptance", {"status": "monitoring"}),
                "health_monitor": value.get("health_monitor", {}),
                "latest_health": value.get("latest_health", {}),
                "research_health": value.get("latest_health", {}).get("research", {}),
            }
        except (OSError, ValueError, TypeError):
            return {"status": "UNAVAILABLE", "cycles": 0}

    def _timeline(self, validator: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            mtime_ns = self.events_path.stat().st_mtime_ns
        except OSError:
            mtime_ns = -1
        if mtime_ns == self._timeline_mtime_ns and self._timeline_cache:
            return list(self._timeline_cache)
        events: list[dict[str, Any]] = []
        started = validator.get("started_at")
        if started:
            events.append({"timestamp": started, "event": "RUNTIME_START", "severity": "INFO", "summary": "Persistierte TIM-Laufzeit gestartet."})
        try:
            lines = self.events_path.read_text().splitlines()[-250:]
        except OSError:
            lines = []
        for line in lines:
            try:
                item = json.loads(line)
            except (TypeError, ValueError):
                continue
            kind = str(item.get("event", ""))
            if kind not in ALLOWED_TIMELINE_EVENTS or "TRADE" in kind or "ORDER" in kind:
                continue
            summary = item.get("overall_status") or item.get("category") or item.get("status") or item.get("severity") or "Recorded"
            events.append({"timestamp": item.get("timestamp"), "event": kind, "severity": item.get("severity", "INFO"), "summary": summary})
        self._timeline_mtime_ns = mtime_ns
        self._timeline_cache = events[-50:]
        return list(self._timeline_cache)

    def readiness(self)->dict[str,Any]:
        try:
            value=json.loads(self.readiness_path.read_text())
            return value if isinstance(value,dict) and value.get("mode")=="OBSERVE" else {"readiness_status":"UNAVAILABLE","criteria":{}}
        except (OSError,ValueError,TypeError):return {"readiness_status":"UNAVAILABLE","criteria":{}}

    @staticmethod
    def _read_dict(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError, TypeError):
            return {}

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            observations = [dict(item) for item in self.active_observations[-VISIBLE_LIMIT:]]
            candles = list(self.recent_candles[-VISIBLE_LIMIT:])
            cases = list(self.research_cases[-VISIBLE_LIMIT:])
            all_cases = list(self.research_cases)
            system_health = dict(self.system_health)
            market_status = dict(self.market_status)
            memory_status = dict(self.memory_status)
            news = dict(self.news)
        case_by_observation = {
            str(observation_id): case
            for case in all_cases
            for observation_id in case.get("observation_ids", [])
        }
        for observation in observations:
            related = case_by_observation.get(str(observation.get("observation_id", "")))
            if related:
                observation["research_case_id"] = related.get("case_id")
                observation["research_case_status"] = related.get("status")
        validator = self._validator()
        active = sum(str(case.get("status", "OPEN")).upper() not in {"CLOSED", "INVALIDATED"} for case in all_cases)
        closed = sum(str(case.get("status", "")).upper() == "CLOSED" for case in all_cases)
        by_status: dict[str, int] = {}
        for case in all_cases:
            key = str(case.get("status") or "OPEN").upper()
            by_status[key] = by_status.get(key, 0) + 1
        collecting = sum(by_status.get(status, 0) for status in ("OPEN", "MONITORING", "COLLECTING_EVIDENCE"))
        generated_at = datetime.now(timezone.utc)
        last_data_at = next(
            (item.get("close_time") or item.get("open_time") for item in reversed(candles) if item.get("close_time") or item.get("open_time")),
            None,
        )
        parsed_last_data = _parse_time(last_data_at)
        data_age = int((generated_at - parsed_last_data).total_seconds()) if parsed_last_data else None
        stream_running = str(system_health.get("stream", "")).lower() == "running"
        database_connected = str(system_health.get("database", "")).lower() == "connected"
        data_fresh = data_age is not None and 0 <= data_age <= 120
        operational_health = {
            "status": "GREEN" if stream_running and database_connected and data_fresh else "YELLOW" if database_connected else "RED",
            "database": "GREEN" if database_connected else "RED",
            "stream": "GREEN" if stream_running and data_fresh else "RED",
            "dashboard": "GREEN",
            "runtime": "GREEN",
            "last_data_at": last_data_at,
            "data_age_seconds": data_age if data_age is not None else "MISSING:last_data_at",
            "checked_at": generated_at.isoformat(),
            "runtime_started_at": self.runtime_started_at,
            "queue_depth": int(system_health.get("queue_depth", 0)),
            "queue_model": str(system_health.get("queue_model", "DIRECT_AWAIT_NO_APPLICATION_QUEUE")),
            "ollama_enabled": bool(system_health.get("ollama_enabled", False)),
            "ollama_availability": str(system_health.get("ollama_availability", "DISABLED_BY_POLICY")),
        }
        return {
                "timestamp": generated_at.isoformat(),
                "mode": "OBSERVE",
                "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC",
                "dashboard_version": DASHBOARD_VERSION,
                "count_scope": "VISIBLE_RECENT_WINDOW",
                "visible_counts": {"candles": len(candles), "observations": len(observations), "research_cases": len(cases)},
                "case_counts": {"active": active, "closed": closed, "total": len(all_cases),
                                "by_status": dict(sorted(by_status.items())),
                                "confirmed": by_status.get("CONFIRMED", 0),
                                "collecting_evidence": collecting,
                                "open": by_status.get("OPEN", 0),
                                "monitoring": by_status.get("MONITORING", 0),
                                "ready_for_review": by_status.get("READY_FOR_REVIEW", 0),
                                "rejected": by_status.get("REJECTED", 0),
                                "quarantined": by_status.get("QUARANTINED", 0)},
                "candles": candles,
                "observations": observations,
                "active_observations": observations,
                "research_cases": cases,
                "validator": validator,
                "timeline": self._timeline(validator),
                "system_health": system_health,
                "operational_health": operational_health,
                "market_status": market_status,
                "memory_status": memory_status,
                "news": news,
                "readiness": self.readiness(),
                "research_audit": self._read_dict(self.audit_path),
                "research_quality": self._read_dict(self.quality_path),
                "core_manifest": self._read_dict(self.core_manifest_path),
                "governance_roles": self._read_dict(self.governance_roles_path),
                "safety": "RESEARCH ONLY — NO ORDERS OR EXECUTION",
        }

    def analytics(self) -> dict[str, Any]:
        with self.lock:
            observations = [dict(item) for item in self.active_observations]
            cases = [dict(item) for item in self.research_cases]
        events: list[dict[str, Any]] = []
        try:
            lines = self.events_path.read_text().splitlines()
        except OSError:
            lines = []
        for line in lines:
            try:
                item = json.loads(line)
                kind = str(item.get("event", "")).upper()
                if isinstance(item, dict) and "TRADE" not in kind and "ORDER" not in kind:
                    events.append(item)
            except (TypeError, ValueError):
                continue
        return ResearchAnalyticsEngine().analyze(observations, cases, events)

    def insights(self) -> dict[str, Any]:
        """Build retrospective insights from copied persisted state only."""
        with self.lock:
            observations = [dict(item) for item in self.orderflow_observations]
            validations = [dict(item) for item in self.orderflow_validations]
            cases = [dict(item) for item in self.research_cases]
        try:
            manifest = json.loads(Path("config/core_manifest.json").read_text())
        except (OSError, ValueError, TypeError) as exc:
            raise ValueError("frozen Core manifest is unavailable") from exc
        validator = self._validator()
        monitor = validator.get("health_monitor", {})
        latest = validator.get("latest_health", {})
        critical = list(monitor.get("critical", []))
        quality = {
            "coverage_percent": validator.get("acceptance", {}).get("coverage_percent"),
            "known_data_gaps": [item for item in critical if str(item).upper() == "DATA_GAP"],
            "integrity_errors": len([item for item in critical if str(item).upper() != "DATA_GAP"]),
            "replay_status": latest.get("benchmark", "UNKNOWN"),
            "source_window_complete": len(observations) < 500 and len(validations) < 500 and len(cases) < 1000,
        }
        return ResearchInsightsEngine().analyze(observations, validations, cases, manifest, quality)


def _case_for_observation(observation: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    if observation.get("research_case_id"):
        return {"case_id": observation.get("research_case_id"), "status": observation.get("research_case_status", "OPEN")}
    oid = str(observation.get("observation_id", ""))
    return next((case for case in cases if oid and oid in [str(item) for item in case.get("observation_ids", [])]), None)


def _observation_row(item: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    case = _case_for_observation(item, cases)
    oid = str(item.get("observation_id", ""))
    evidence_score = item.get("confidence", "—")
    status = str(case.get("status")) if case else "UNASSIGNED"
    href = f"/observations?id={html.escape(oid, quote=True)}" if oid else "/observations"
    return (
        f"<tr data-status='{_safe(status)}' data-type='{_safe(item.get('kind'))}' data-rule='{_safe(item.get('rule_version'))}'>"
        f"<td>{_safe(item.get('observed_at'))}</td><td><a href='{href}' class='mono'>{_safe(_short(oid, 12))}</a></td>"
        f"<td><span class='tag'>{_safe(item.get('kind'))}</span></td><td class='mono'>{_safe(item.get('rule_version'))}</td>"
        f"<td>{_safe(evidence_score)}</td><td>{_safe(item.get('provenance'))}</td><td><span class='badge badge--{_status(status).lower()}'>{_safe(status)}</span></td></tr>"
    )


def _research_cases_collection(snapshot: dict[str, Any], query: dict[str, list[str]], stats_only: bool = False) -> dict[str, Any]:
    """Read-only Research Case collection: filters (no implicit CONFIRMED
    restriction), real per-status stats, cursor pagination. OBSERVE-only."""
    cases = [dict(item) for item in snapshot.get("research_cases", [])]
    by_status: dict[str, int] = {}
    for item in cases:
        key = str(item.get("status") or "OPEN").upper()
        by_status[key] = by_status.get(key, 0) + 1
    missing: dict[str, int] = {}
    for item in cases:
        for reason in item.get("missing_evidence", []) or []:
            missing[str(reason)] = missing.get(str(reason), 0) + 1
    stats = {"total": len(cases), "by_status": dict(sorted(by_status.items())),
             "confirmed": by_status.get("CONFIRMED", 0),
             "pending_outcome": sum(1 for item in cases if not item.get("outcome")),
             "missing_evidence": dict(sorted(missing.items()))}
    if stats_only:
        return {"stats": stats, "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC"}
    status = (query.get("status", [""])[0] or "").upper()
    if status and status != "ALL":
        cases = [item for item in cases if str(item.get("status") or "").upper() == status]
    timeframe = (query.get("timeframe", [""])[0] or "")
    if timeframe:
        cases = [item for item in cases if str(item.get("timeframe", "")) == timeframe]
    otype = (query.get("observation_type", [""])[0] or "")
    if otype:
        cases = [item for item in cases if any(str(ev.get("kind", "")) == otype for ev in item.get("evidence", []) or [])]
    rule = (query.get("rule_version", [""])[0] or "")
    if rule:
        cases = [item for item in cases if rule in set(str(v) for v in (item.get("rule_versions", {}) or {}).values())]
    instrument = (query.get("instrument", [""])[0] or "")
    if instrument:
        cases = [item for item in cases if str(item.get("symbol", "")) == instrument]
    try:
        limit = max(1, min(200, int((query.get("limit", ["50"])[0] or "50"))))
    except ValueError:
        limit = 50
    cursor = (query.get("cursor", [""])[0] or "")
    start = 0
    if cursor:
        for index, item in enumerate(cases):
            if str(item.get("case_id")) == cursor:
                start = index + 1
                break
    window = cases[start:start + limit]
    return {"cases": window, "stats": stats,
            "pagination": {"limit": limit, "returned": len(window), "total_matching": len(cases),
                           "next_cursor": str(window[-1].get("case_id", "")) if len(window) == limit and start + limit < len(cases) else None},
            "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC"}


def _case_row(item: dict[str, Any]) -> str:
    opened, updated = item.get("opened_at"), item.get("updated_at")
    kinds = sorted({str(ev.get("kind")) for ev in item.get("evidence", []) if ev.get("kind")})
    rules = ", ".join(f"{key}:{value}" for key, value in sorted(item.get("rule_versions", {}).items()))
    case_id = str(item.get("case_id", ""))
    return (
        f"<tr data-status='{_safe(item.get('status'))}' data-type='{_safe(' '.join(kinds))}' data-rule='{_safe(rules)}' data-time='{_safe(updated)}'>"
        f"<td><a href='/cases?id={html.escape(case_id, quote=True)}' class='mono'>{_safe(_short(case_id, 18))}</a></td>"
        f"<td><span class='badge badge--{_status(item.get('status')).lower()}'>{_safe(item.get('status'))}</span></td>"
        f"<td>{_safe(_duration(opened, updated))}</td><td>{len(item.get('observation_ids', []))}</td><td>{_safe(item.get('outcome'))}</td>"
        f"<td>{_safe(', '.join(item.get('missing_evidence', [])))}</td><td>{_safe(', '.join(kinds))}</td><td class='mono'>{_safe(rules)}</td></tr>"
    )


def _required(field: str, value: Any) -> str:
    if value in (None, "", [], {}, ()):
        return f"MISSING:{field}"
    return str(value)


def _status_level(value: Any, severity: str = "WARNING") -> tuple[str, str]:
    normalized = str(value or "UNKNOWN").upper()
    if normalized in {"GREEN", "HEALTHY", "RUNNING", "CONNECTED", "PASS", "COMPLETE", "COMPLETED", "AVAILABLE", "TRUE"}:
        return "GREEN", "INFO"
    if normalized in {"YELLOW", "WARNING", "WAITING", "MONITORING", "DEGRADED", "PARTIAL", "NOT_READY_FOR_V2", "OPEN", "OPEN_ISSUES"}:
        return "YELLOW", severity
    return "RED", "CRITICAL" if severity in {"HIGH", "CRITICAL"} else severity


def _issue_windows(data: dict[str, Any]) -> list[dict[str, Any]]:
    validator = data["validator"]
    readiness = data.get("readiness", {})
    quality = data.get("research_quality", {})
    audit = data.get("research_audit", {})
    window = {
        "start": readiness.get("continuous_window_start") or validator.get("started_at"),
        "end": readiness.get("continuous_window_end") or validator.get("last_cycle_at") or data.get("timestamp"),
    }
    rows: list[dict[str, Any]] = []
    for issue in quality.get("issues", []):
        if not isinstance(issue, dict):
            continue
        rows.append({
            "component_id": issue.get("code", "quality"),
            "display_name": issue.get("code", "Quality Issue"),
            "domain": "Scientific Health",
            "status": "RED",
            "severity": "HIGH",
            "short_summary": issue.get("detail", "Qualitätsabweichung dokumentiert."),
            "reason_code": issue.get("code", "QUALITY_ISSUE"),
            "reason_text": issue.get("detail", "Qualitätsabweichung dokumentiert."),
            "technical_cause": issue.get("detail", "Ursache dokumentiert im Quality-Report."),
            "scientific_meaning": "Beeinflusst Reproduzierbarkeit, Provenance oder Datenqualität.",
            "governance_impact": "Dokumentations- und Review-Pflicht.",
            "operational_impact": "Keine operative Korrektur im Dashboard.",
            "observed_since_utc": quality.get("generated_at") or data.get("timestamp"),
            "last_checked_utc": quality.get("generated_at") or data.get("timestamp"),
            "evidence_count": 1,
            "affected_artifact_count": 1,
            "linked_report": "data/research/quality/latest.json",
            "linked_blocker": "quality" if str(issue.get("code", "")).upper() != "DATA_GAP" else "continuous_coverage",
            "recommended_next_action": "Quality-Issue im unveränderten Report prüfen.",
            "operational_impact_text": "Keine betriebliche Änderung.",
            "scientific_impact": "Qualitäts- oder Provenance-Befund.",
            "governance_impact_text": "Read-only Diagnose erforderlich.",
            "freshness_seconds": 0,
            "provenance": issue.get("path", "PUBLIC_MARKET_DATA_DETERMINISTIC"),
            "source_hash": quality.get("report_hash") or quality.get("artifact_hash") or "MISSING:source_hash",
            "affected_windows": issue.get("path", "MISSING:affected_windows"),
            "affected_artifacts": issue.get("path", "MISSING:affected_artifacts"),
            "evidence": [issue.get("detail"), issue.get("path")],
            "status_history": [f"{quality.get('generated_at', data.get('timestamp'))}: {issue.get('code', 'UNKNOWN')}"],
            "historical_development": issue.get("path", "MISSING:historical_development"),
            "open_blockers": readiness.get("blocking_criteria", []),
            "known_limitations": ["Keine Rekonstruktion", "Kein Backfill"],
            "linked_report_path": "data/research/quality/latest.json",
            "window_start": window["start"],
            "window_end": window["end"],
        })
    for issue in audit.get("issues", []):
        if not isinstance(issue, dict):
            continue
        code = str(issue.get("code", "AUDIT_ISSUE")).upper()
        rows.append({
            "component_id": code,
            "display_name": code.replace("_", " ").title(),
            "domain": "Governance Health",
            "status": "RED" if "HASH" in code or "DOCUMENTATION" in code else "YELLOW",
            "severity": "HIGH" if "HASH" in code else "WARNING",
            "short_summary": issue.get("detail", "Audit finding documented."),
            "reason_code": code,
            "reason_text": issue.get("detail", "Audit finding documented."),
            "technical_cause": issue.get("detail", "Audit finding documented."),
            "scientific_meaning": "Betroffene Artefakte müssen unverändert dokumentiert bleiben.",
            "governance_impact": "Audit-Auflösung nur über Versionierung, nicht über Retrofix.",
            "operational_impact": "Kein runtime fix.",
            "observed_since_utc": audit.get("generated_at") or data.get("timestamp"),
            "last_checked_utc": audit.get("generated_at") or data.get("timestamp"),
            "evidence_count": 1,
            "affected_artifact_count": 1,
            "linked_report": "data/research/audit/latest.json",
            "linked_blocker": "scientific_review" if "HASH" in code else "documentation",
            "recommended_next_action": "Audit-Eintrag gegen Referenzkette prüfen.",
            "operational_impact_text": "Nur Diagnose, keine Laufzeitänderung.",
            "scientific_impact": "Historische Integrität und Reproduzierbarkeit.",
            "governance_impact_text": "Future Contract / Review erforderlich.",
            "freshness_seconds": 0,
            "provenance": issue.get("path", "PUBLIC_MARKET_DATA_DETERMINISTIC"),
            "source_hash": audit.get("audit_hash") or audit.get("artifact_hash") or "MISSING:source_hash",
            "affected_windows": issue.get("path", "MISSING:affected_windows"),
            "affected_artifacts": issue.get("path", "MISSING:affected_artifacts"),
            "evidence": [issue.get("detail"), issue.get("path")],
            "status_history": [f"{audit.get('generated_at', data.get('timestamp'))}: {issue.get('code', 'UNKNOWN')}"],
            "historical_development": issue.get("path", "MISSING:historical_development"),
            "open_blockers": readiness.get("blocking_criteria", []),
            "known_limitations": ["Historische Artefakte unverändert", "Keine Rekonstruktion"],
            "linked_report_path": "data/research/audit/latest.json",
            "window_start": window["start"],
            "window_end": window["end"],
        })
    for code in readiness.get("blocking_criteria", []):
        rows.append({
            "component_id": str(code).upper(),
            "display_name": str(code).replace("_", " ").title(),
            "domain": "Scientific Health",
            "status": "YELLOW",
            "severity": "WARNING",
            "short_summary": f"Blocker {code} verhindert automatische Freigabe.",
            "reason_code": str(code).upper(),
            "reason_text": f"Persistierter Blocker {code} ist noch offen.",
            "technical_cause": f"Blocking criterion {code} ist noch nicht PASS.",
            "scientific_meaning": "Readiness ist nicht erreicht.",
            "governance_impact": "Manueller Review erforderlich.",
            "operational_impact": "Kein operative Störung, aber wissenschaftlicher Stopp.",
            "observed_since_utc": readiness.get("generated_at") or data.get("timestamp"),
            "last_checked_utc": readiness.get("generated_at") or data.get("timestamp"),
            "evidence_count": 1,
            "affected_artifact_count": 1,
            "linked_report": "data/research/status/tim_v1_readiness.json",
            "linked_blocker": code,
            "recommended_next_action": "Persistiertes Blocker-Register prüfen.",
            "operational_impact_text": "Keine Laufzeitänderung.",
            "scientific_impact": "Ready-for-V2 bleibt offen.",
            "governance_impact_text": "Freigabe nicht erlaubt.",
            "freshness_seconds": 0,
            "provenance": readiness.get("provenance", "PUBLIC_MARKET_DATA_DETERMINISTIC"),
            "source_hash": readiness.get("artifact_hash") or "MISSING:source_hash",
            "affected_windows": readiness.get("continuous_window_start", "MISSING:affected_windows"),
            "affected_artifacts": "data/research/status/tim_v1_readiness.json",
            "evidence": [code, readiness.get("generated_at")],
            "status_history": [f"{readiness.get('generated_at', data.get('timestamp'))}: {code}"],
            "historical_development": readiness.get("continuous_window_start", "MISSING:historical_development"),
            "open_blockers": list(readiness.get("blocking_criteria", [])),
            "known_limitations": ["Keine automatische Schließung", "Keine Datenrekonstruktion"],
            "linked_report_path": "data/research/status/tim_v1_readiness.json",
            "window_start": window["start"],
            "window_end": window["end"],
        })
    return rows


def _card_markup(record: dict[str, Any]) -> str:
    status = str(record.get("status", "UNKNOWN")).upper()
    level = str(record.get("severity", "WARNING")).upper()
    archived_snapshot = bool(record.get("archived_snapshot"))
    badge = "snapshot" if archived_snapshot else status.lower()
    badge_text = f"ARCHIV · {status}" if archived_snapshot else status
    details = [
        ("component_id", record.get("component_id")),
        ("display_name", record.get("display_name")),
        ("domain", record.get("domain")),
        ("status", status),
        ("severity", level),
        ("short_summary", record.get("short_summary")),
        ("reason_code", record.get("reason_code")),
        ("reason_text", record.get("reason_text")),
        ("observed_since_utc", record.get("observed_since_utc")),
        ("last_checked_utc", record.get("last_checked_utc")),
        ("evidence_count", record.get("evidence_count")),
        ("affected_artifact_count", record.get("affected_artifact_count")),
        ("linked_report", record.get("linked_report")),
        ("linked_blocker", record.get("linked_blocker")),
        ("recommended_next_action", record.get("recommended_next_action")),
        ("operational_impact", record.get("operational_impact") or record.get("operational_impact_text")),
        ("scientific_impact", record.get("scientific_impact")),
        ("governance_impact", record.get("governance_impact") or record.get("governance_impact_text")),
        ("freshness_seconds", record.get("freshness_seconds")),
        ("provenance", record.get("provenance")),
        ("source_hash", record.get("source_hash")),
        ("technical_cause", record.get("technical_cause")),
        ("affected_windows", record.get("affected_windows")),
        ("affected_artifacts", record.get("affected_artifacts")),
        ("status_history", " | ".join(record.get("status_history", [])) if record.get("status_history") else None),
        ("historical_development", record.get("historical_development")),
        ("open_blockers", ", ".join(str(item) for item in record.get("open_blockers", [])) if record.get("open_blockers") else None),
        ("known_limitations", ", ".join(str(item) for item in record.get("known_limitations", [])) if record.get("known_limitations") else None),
        ("linked_report_path", record.get("linked_report_path")),
    ]
    evidence_items = record.get("evidence", [])
    evidence_html = "".join(f"<li class='mono'>{_safe(item)}</li>" for item in evidence_items) or "<li>MISSING:evidence</li>"
    optional_fields = {"linked_blocker", "linked_report_path", "open_blockers"}
    detail_html = "".join(
        f"<dt>{_safe(label)}</dt><dd class='mono'>{_safe('N/A' if label in optional_fields and value in (None, '') else _required(label, value))}</dd>"
        for label, value in details
    )
    glossary = "<p class='card-glossary'>Reason · Seit · Auswirkung · Empfohlener nächster Schritt · Evidenz</p>"
    return (
        f"<details class='card health-card health--{badge}'>"
        f"<summary><span><span class='card__label'>{_safe(record.get('display_name'))}</span><strong>{_safe(record.get('short_summary'))}</strong></span>"
        f"<span class='badge badge--{badge}'>{_safe(badge_text)}</span></summary>"
        f"<div class='diagnostic'>{glossary}<dl>{detail_html}</dl><h4>Evidenz</h4><ul>{evidence_html}</ul></div></details>"
    )


def _diagnostic_card(
    name: str,
    level: str,
    summary: str,
    reason: str,
    evidence: list[str],
    impact: str,
    next_step: str,
    since: Any = None,
) -> str:
    status, severity = _status_level(level)
    return _card_markup(
        {
            "component_id": name.lower().replace(" ", "_"),
            "display_name": name,
            "domain": "Scientific Health" if name in {"Continuous Coverage", "Validator", "Replay", "Research Integrity", "Determinism", "Provenance", "Hash Integrity", "Data Quality", "Acceptance"} else "Operational Health",
            "status": status,
            "severity": severity,
            "short_summary": summary,
            "reason_code": name.upper().replace(" ", "_"),
            "reason_text": reason,
            "technical_cause": reason,
            "scientific_meaning": impact,
            "governance_impact": next_step,
            "operational_impact": impact,
            "observed_since_utc": since,
            "last_checked_utc": since,
            "evidence_count": len(evidence),
            "affected_artifact_count": len(evidence),
            "linked_report": "MISSING:linked_report",
            "linked_blocker": "MISSING:linked_blocker",
            "recommended_next_action": next_step,
            "freshness_seconds": "MISSING:freshness_seconds",
            "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC",
            "source_hash": "MISSING:source_hash",
            "evidence": evidence,
            "status_history": [str(since)] if since not in (None, "") else [],
            "known_limitations": [],
        }
    )


def _timeline_rows(events: list[dict[str, Any]]) -> str:
    component_by_event = {
        "RUNTIME_START": "runtime",
        "RESTART": "runtime",
        "VALIDATION_CYCLE": "validator",
        "RESEARCH_CYCLE_CHECK": "research_integrity",
        "ACCEPTANCE_CHECK": "acceptance",
        "CONTROLLED_API_FAILURE": "dashboard_api",
        "UNCONTROLLED_API_FAILURE": "dashboard_api",
        "VALIDATOR_RECOVERY": "validator",
        "DATA_GAP": "data_quality",
    }
    status_by_event = {
        "RUNTIME_START": "RUNNING",
        "RESTART": "RUNNING",
        "VALIDATION_CYCLE": "CHECKED",
        "RESEARCH_CYCLE_CHECK": "CHECKED",
        "ACCEPTANCE_CHECK": "CHECKED",
        "CONTROLLED_API_FAILURE": "CONTROLLED_FAILURE",
        "UNCONTROLLED_API_FAILURE": "UNAVAILABLE",
        "VALIDATOR_RECOVERY": "RECOVERED",
        "DATA_GAP": "GAP_DETECTED",
    }
    rows: list[str] = []
    for idx, item in enumerate(reversed(events)):
        timestamp = item.get("timestamp") or item.get("timestamp_utc")
        event_type = str(item.get("event_type") or item.get("event") or "UNKNOWN")
        component_id = item.get("component_id") or component_by_event.get(event_type, "system")
        previous_status = item.get("previous_status") or "NOT_RECORDED"
        new_status = item.get("new_status") or item.get("status") or status_by_event.get(event_type, "RECORDED")
        reason_code = item.get("reason_code") or item.get("category") or event_type
        evidence_reference = item.get("evidence_reference") or item.get("summary") or "data/operational/events.jsonl"
        provenance = item.get("provenance") or "TIM_OPERATIONAL_EVENT"
        source_hash = item.get("source_hash") or "N/A:LEGACY_EVENT_NOT_HASHED"
        identity = json.dumps(
            {"timestamp": timestamp, "event_type": event_type, "component_id": component_id, "reason_code": reason_code},
            sort_keys=True,
            separators=(",", ":"),
        )
        event_id = item.get("event_id") or "evt-" + hashlib.sha256(identity.encode()).hexdigest()[:12]
        rows.append(
            "<tr>"
            f"<td class='mono'>{_safe(event_id)}</td>"
            f"<td>{_safe(_required('event_type', event_type))}</td>"
            f"<td>{_safe(_required('timestamp_utc', timestamp))}</td>"
            f"<td>{_safe(_required('component_id', component_id))}</td>"
            f"<td>{_safe(previous_status)}</td>"
            f"<td>{_safe(new_status)}</td>"
            f"<td>{_safe(reason_code)}</td>"
            f"<td class='mono'>{_safe(evidence_reference)}</td>"
            f"<td>{_safe(provenance)}</td>"
            f"<td class='mono'>{_safe(source_hash)}</td>"
            "</tr>"
        )
    return "".join(rows) or "<tr><td colspan='10' class='empty'>Keine Systemereignisse verfügbar.</td></tr>"


def _quality_exception_rows(data: dict[str, Any], *, archived: bool = False) -> tuple[str, list[dict[str, Any]]]:
    rows = _issue_windows(data)
    severity_order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}
    rows = sorted(rows, key=lambda item: (severity_order.get(str(item.get("severity", "WARNING")).upper(), 9), str(item.get("reason_code", "")), str(item.get("component_id", ""))))
    html_rows = []
    for item in rows:
        source_status = str(item.get("status", "UNKNOWN")).upper()
        display_status = "NOT_RECORDED" if archived and source_status == "UNKNOWN" else source_status
        badge = "snapshot" if archived else _status(source_status).lower()
        badge_text = f"ARCHIV · {display_status}" if archived else display_status
        html_rows.append(
            f"<tr data-status='{_safe(source_status)}' data-type='{_safe(item.get('reason_code'))}' data-rule='{_safe(item.get('linked_blocker'))}'>"
            f"<td>{_safe(item.get('component_id'))}</td><td><span class='badge badge--{badge}'>{_safe(badge_text)}</span></td>"
            f"<td>{_safe(item.get('reason_code'))}</td><td>{_safe(item.get('reason_text'))}</td><td>{_safe(item.get('window_start'))} → {_safe(item.get('window_end'))}</td>"
            f"<td>{_safe(item.get('provenance'))}</td><td>{_safe(item.get('linked_report_path'))}</td><td>{_safe(item.get('linked_blocker'))}</td></tr>"
        )
    if not html_rows:
        html_rows.append("<tr><td colspan='8' class='empty'>Keine Data-Quality-Exceptions dokumentiert.</td></tr>")
    return "".join(html_rows), rows


def _signal_context_rows(candles: list[dict[str, Any]]) -> str:
    by_timeframe: dict[str, dict[str, Any]] = {}
    for candle in candles:
        timeframe = str(candle.get("timeframe", "")).lower()
        if timeframe and timeframe not in by_timeframe:
            by_timeframe[timeframe] = candle
    rows = []
    for timeframe in ("60s", "1m", "5m", "15m", "1h"):
        candle = by_timeframe.get(timeframe) or by_timeframe.get("1m") if timeframe == "60s" else by_timeframe.get(timeframe)
        if not candle:
            rows.append(
                f"<tr><td>{timeframe}</td><td>MISSING:candle_open_time_utc</td><td>MISSING:price_change_in_window</td><td>MISSING:candle_range</td><td>MISSING:volume</td><td>MISSING:delta_relation</td><td>MISSING:cvd_relation</td><td>NO_SUFFICIENT_DATA</td></tr>"
            )
            continue
        open_price = candle.get("open")
        close_price = candle.get("close")
        high_price = candle.get("high")
        low_price = candle.get("low")
        change = None
        if isinstance(open_price, (int, float)) and isinstance(close_price, (int, float)):
            change = round(float(close_price) - float(open_price), 8)
        candle_range = None
        if isinstance(high_price, (int, float)) and isinstance(low_price, (int, float)):
            candle_range = round(float(high_price) - float(low_price), 8)
        context_state = "CONTEXT_ALIGNED" if candle.get("open_time") and candle.get("close_time") else "CONTEXT_INCOMPLETE"
        rows.append(
            f"<tr><td>{_safe(timeframe)}</td><td>{_safe(candle.get('open_time'))}</td><td class='mono'>{_safe(change if change is not None else 'MISSING:price_change_in_window')}</td><td class='mono'>{_safe(candle_range if candle_range is not None else 'MISSING:candle_range')}</td><td>{_safe(candle.get('volume'))}</td><td>MISSING:delta_relation</td><td>MISSING:cvd_relation</td><td>{context_state}</td></tr>"
        )
    return "".join(rows)


def _retrospective_outcome_rows(validations: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for validation in reversed(validations[:25]):
        horizons = validation.get("horizons", []) or []
        for horizon in horizons:
            minutes = horizon.get("minutes", "MISSING:minutes")
            rows.append(
                f"<tr><td>{_safe(validation.get('observation_id'))}</td><td>{_safe(minutes)}m</td><td>RETROSPECTIVE</td>"
                f"<td class='mono'>{_safe(horizon.get('price_change_percent') or 'MISSING:price_change')}</td>"
                f"<td class='mono'>{_safe(horizon.get('delta_change') or horizon.get('net_delta') or 'MISSING:delta_change')}</td>"
                f"<td class='mono'>{_safe(horizon.get('cvd_change') or 'MISSING:cvd_change')}</td>"
                f"<td class='mono'>{_safe(horizon.get('trade_frequency_change') or 'MISSING:trade_frequency_change')}</td>"
                f"<td>{_safe(horizon.get('context_change') or 'MISSING:context_change')}</td>"
                f"<td>{_safe(validation.get('outcome') or horizon.get('result') or 'MISSING:validation_result')}</td>"
                f"<td>{_safe(validation.get('invalidation_reason') or 'MISSING:invalidation_reason')}</td></tr>"
            )
    if not rows:
        rows.append("<tr><td colspan='10' class='empty'>Keine retrospektiv validierten Horizonte vorhanden.</td></tr>")
    return "".join(rows)


def _signal_research_page(state: DashboardState, data: dict[str, Any], selected_id: str | None) -> str:
    rows, counts, summary, cases, active = _signal_research_rows(state, data)
    _, exception_items = _quality_exception_rows(data)
    with state.lock:
        observations = [dict(item) for item in state.orderflow_observations[-ORDERFLOW_VISIBLE_LIMIT:]]
        validations = [dict(item) for item in state.orderflow_validations]
    selected = next((item for item in observations if str(item.get("observation_id")) == str(selected_id)), None) or (observations[0] if observations else None)
    symbol = data.get("market_status", {}).get("symbol", "BTCUSDT")
    stream_status = data.get("system_health", {}).get("stream", "unknown")
    last_capture = observations[-1].get("observed_at") if observations else data.get("timestamp")
    freshness = _age_seconds(last_capture)
    latest_rule = (selected or {}).get("rule_version") or data.get("readiness", {}).get("schema_version", "MISSING:rule_version")
    pipeline_version = data.get("readiness", {}).get("generator_version") or data.get("research_quality", {}).get("generator_version") or DASHBOARD_VERSION
    quality_summary = data.get("research_quality", {}).get("validation_status") or data.get("readiness", {}).get("validation_status") or "UNKNOWN"
    open_validations = sum(1 for item in validations if not item.get("complete"))
    completed_cases = sum(1 for item in cases if str(item.get("status", "")).upper() == "CLOSED")
    signal_note = "AggTrades · Orderflow Metrics · Signal Research. Kein Trading-Signal, keine Buy-/Sell-, Long-/Short-Entscheidung, keine Ausführung."
    top = (
        "<section class='panel'><div class='signal-header'><div><h2>Globaler Forschungsstatus</h2>"
        "<div class='signal-kicker'><span class='signal-pill'>OBSERVE</span><span class='signal-pill'>READ-ONLY</span><span class='signal-pill'>RESEARCH ONLY</span></div>"
        f"<p class='count-scope'>Symbol { _safe(symbol) } · Stream {_safe(stream_status)} · letzte Erfassung UTC {_safe(last_capture)} · Datenfrische {_safe(freshness)}s</p>"
        f"</div><div class='status-note'><b>Pipeline-Version:</b> {_safe(pipeline_version)}<br><b>Aktuelle Rule-Version:</b> {_safe(latest_rule)}<br><span class='muted'>{_safe(signal_note)}</span></div></div></section>"
    )
    summary_grid = (
        "<div class='meta-grid'>"
        f"<article class='card'><div class='card__label'>Sichtbare Observations</div><div class='card__value'>{counts['shown']}</div><div class='card__note'>Persistierter Ausschnitt</div></article>"
        f"<article class='card'><div class='card__label'>Offene Validierungen</div><div class='card__value'>{open_validations}</div><div class='card__note'>5m / 15m / 30m offen</div></article>"
        f"<article class='card'><div class='card__label'>Abgeschlossene Research Cases</div><div class='card__value'>{completed_cases}</div><div class='card__note'>Retrospektiv geschlossen</div></article>"
        f"<article class='card'><div class='card__label'>Data Quality Summary</div><div class='card__value'>{_safe(quality_summary)}</div><div class='card__note'>Read-only Gate</div></article>"
        f"<article class='card'><div class='card__label'>Modus</div><div class='card__value'>OBSERVE</div><div class='card__note'>No trading / no signals</div></article>"
        "</div>"
    )
    queue_grid = (
        "<div class='queue-grid'>"
        f"<article class='card'><div class='card__label'>Live Research Queue</div><div class='card__value'>{summary['shown'] - summary['validated']}</div><div class='card__note'>Neue oder unvollständige Observations</div></article>"
        f"<article class='card'><div class='card__label'>Validation Queue</div><div class='card__value'>{summary['awaiting']}</div><div class='card__note'>5m / 15m / 30m offen</div></article>"
        f"<article class='card'><div class='card__label'>Completed Research Cases</div><div class='card__value'>{completed_cases}</div><div class='card__note'>Abgeschlossene Fälle</div></article>"
        f"<article class='card'><div class='card__label'>Data Quality Exceptions</div><div class='card__value'>{len(exception_items)}</div><div class='card__note'>Aus der Diagnose-Ansicht</div></article>"
        "</div>"
    )
    selected_detail = ""
    if selected:
        validation = next((item for item in validations if str(item.get("observation_id")) == str(selected.get("observation_id"))), {})
        evidence = selected.get("evidence", [])
        evidence_names = sorted({str(value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key")) for value in evidence if isinstance(value, dict) and (value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key"))})
        selected_detail = (
            "<section class='panel'><div class='panel__head'><h2>Evidence Card</h2><span class='badge badge--yellow'>DETAIL</span></div>"
            "<div class='detail-grid'><dl class='detail'>"
            f"<dt>observation_id</dt><dd class='mono'>{_safe(selected.get('observation_id'))}</dd>"
            f"<dt>timestamp_utc</dt><dd>{_safe(selected.get('observed_at'))}</dd>"
            f"<dt>symbol</dt><dd>{_safe(selected.get('symbol') or symbol)}</dd>"
            f"<dt>timeframe</dt><dd>{_safe(selected.get('timeframe'))}</dd>"
            f"<dt>observation_type</dt><dd>{_safe(selected.get('kind'))}</dd>"
            f"<dt>rule_id</dt><dd>{_safe(selected.get('rule_id'))}</dd>"
            f"<dt>rule_version</dt><dd>{_safe(selected.get('rule_version'))}</dd>"
            f"<dt>fulfilled_conditions</dt><dd>{_safe(', '.join(evidence_names) or 'MISSING:fulfilled_conditions')}</dd>"
            f"<dt>missing_evidence</dt><dd>{_safe(', '.join(selected.get('missing_evidence', [])) or 'MISSING:missing_evidence')}</dd>"
            f"<dt>validation_status</dt><dd>{_safe('COMPLETE' if validation.get('complete') else 'INCOMPLETE')}</dd>"
            f"<dt>linked_research_case_id</dt><dd>{_safe(selected.get('research_case_id') or 'MISSING:linked_research_case_id')}</dd>"
            f"<dt>integrity_status</dt><dd>{_safe(selected.get('integrity_status') or selected.get('validation_status') or 'MISSING:integrity_status')}</dd>"
            "</dl><div><h3>Rohdaten</h3><pre class='code'>" + _json_block(selected) + "</pre><h3>Evidence</h3><pre class='code'>" + _json_block(evidence) + "</pre></div></div></section>"
        )
    evidence_table = (
        "<section class='panel'><div class='panel__head'><h2>Signal Research</h2><span class='badge badge--yellow'>MANUAL RESEARCH</span></div>"
        "<p class='safety-callout'><b>Kein Trading-Signal:</b> Diese Seite zeigt ausschließlich persistierte Evidenz und historische Validierung. Sie erzeugt keine Buy-/Sell-, Long-/Short- oder Ausführungsempfehlung.</p>"
        "<div class='filters'><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. RISING_CVD_ACTIVITY'></div><div><label>Validierungsstatus</label><select id='filter-status'><option value=''>Alle</option><option value='VALIDATED_CONTEXT'>Validierter Kontext</option><option value='AWAITING_OUTCOME'>Outcome ausstehend</option></select></div><div><label>Zeitraum</label><select id='filter-period'><option value=''>Gesamt</option><option value='1'>24 Stunden</option><option value='7'>7 Tage</option></select></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Timestamp UTC</th><th>Symbol</th><th>Observation ID</th><th>Observation Type</th><th>Timeframe</th><th>Delta</th><th>CVD State</th><th>Buy/Sell Ratio</th><th>Trade Frequency</th><th>Evidence Count</th><th>Missing Evidence Count</th><th>Research Status</th><th>Validation Stage</th><th>Retrospective Outcome</th><th>Data Freshness</th><th>Integrity Status</th><th>Detail</th></tr></thead><tbody>"
        + rows
        + "</tbody></table></div></section>"
    )
    context_matrix = (
        "<section class='panel'><div class='panel__head'><h2>Multi-Timeframe Kontextmatrix</h2><span class='badge badge--green'>DETERMINISTIC</span></div>"
        "<div class='table-wrap'><table><thead><tr><th>Timeframe</th><th>candle_open_time_utc</th><th>price_change_in_window</th><th>candle_range</th><th>volume</th><th>delta_relation</th><th>cvd_relation</th><th>context_state</th></tr></thead><tbody>"
        + _signal_context_rows(data.get("candles", []))
        + "</tbody></table></div><p class='count-scope'>Kontextwerte sind rein deskriptiv. Keine Richtungsempfehlung und keine Prognose.</p></section>"
    )
    retrospective = (
        "<section class='panel'><div class='panel__head'><h2>Retrospective Outcomes</h2><span class='badge badge--yellow'>RETROSPECTIVE</span></div>"
        "<p class='count-scope'>5m-, 15m- und 30m-Outcomes tragen dauerhaft das Label RETROSPECTIVE. Keine prognostische Formulierung.</p>"
        "<div class='table-wrap'><table><thead><tr><th>Observation ID</th><th>Horizon</th><th>Label</th><th>price_change</th><th>delta_change</th><th>cvd_change</th><th>trade_frequency_change</th><th>context_change</th><th>validation_result</th><th>invalidation_reason</th></tr></thead><tbody>"
        + _retrospective_outcome_rows(validations)
        + "</tbody></table></div></section>"
    )
    exceptions_rows, exception_items = _quality_exception_rows(data)
    exceptions = (
        "<section class='panel'><div class='panel__head'><h2>Data Quality Gating</h2><span class='badge badge--red'>EXCEPTIONS</span></div>"
        f"<div class='meta-grid'><article class='card'><div class='card__label'>Current Coverage</div><div class='card__value'>{_safe(data.get('readiness', {}).get('continuous_coverage_percent'))}%</div><div class='card__note'>Continuous coverage</div></article><article class='card'><div class='card__label'>Missing Minutes</div><div class='card__value'>{_safe(data.get('readiness', {}).get('continuous_missing_1m_intervals'))}</div><div class='card__note'>Expected minutes {_safe(data.get('readiness', {}).get('continuous_expected_1m_intervals'))}</div></article><article class='card'><div class='card__label'>Gap Count</div><div class='card__value'>{_safe(data.get('readiness', {}).get('unresolved_new_gap_count'))}</div><div class='card__note'>Open blocker register</div></article><article class='card'><div class='card__label'>Missing AggTrades</div><div class='card__value'>{_safe(sum(1 for item in exception_items if 'AGG' in str(item.get('reason_code', '')).upper()))}</div><div class='card__note'>From exception register</div></article><article class='card'><div class='card__label'>Missing Validation</div><div class='card__value'>{_safe(sum(1 for item in exception_items if 'VALIDATION' in str(item.get('reason_code', '')).upper()))}</div><div class='card__note'>From exception register</div></article></div>"
        "<div class='table-wrap'><table><thead><tr><th>Component</th><th>Status</th><th>Reason Code</th><th>Reason Text</th><th>Time Window</th><th>Provenance</th><th>Linked Report</th><th>Linked Blocker</th></tr></thead><tbody>"
        + exceptions_rows
        + "</tbody></table></div></section>"
    )
    areas = (
        "<div class='queue-grid'>"
        f"<article class='card'><div class='card__label'>Live Research Queue</div><div class='card__value'>{counts['shown'] - counts['validated']}</div><div class='card__note'>Neue oder unvollständige Observations</div></article>"
        f"<article class='card'><div class='card__label'>Validation Queue</div><div class='card__value'>{counts['awaiting']}</div><div class='card__note'>5m / 15m / 30m offen</div></article>"
        f"<article class='card'><div class='card__label'>Completed Research Cases</div><div class='card__value'>{completed_cases}</div><div class='card__note'>Abgeschlossene Fälle</div></article>"
        f"<article class='card'><div class='card__label'>Data Quality Exceptions</div><div class='card__value'>{len(exception_items)}</div><div class='card__note'>Ausgelöste Gate-Events</div></article>"
        "</div>"
    )
    top = (
        "<section class='panel'><div class='signal-header'><div><h2>Globaler Forschungsstatus</h2>"
        "<div class='signal-kicker'><span class='signal-pill'>OBSERVE</span><span class='signal-pill'>READ-ONLY</span><span class='signal-pill'>RESEARCH ONLY</span></div>"
        f"<p class='count-scope'>Symbol {_safe(symbol)} · Stream {_safe(stream_status)} · letzte Erfassung UTC {_safe(last_capture)} · Datenfrische {_safe(freshness)}s</p>"
        "</div><div class='status-note'><b>Pipeline-Version:</b> {_safe(pipeline_version)}<br><b>Aktuelle Rule-Version:</b> {_safe(latest_rule)}<br><b>Offene Validierungen:</b> {_safe(open_validations)}<br><b>Abgeschlossene Research Cases:</b> {_safe(completed_cases)}<br><span class='muted'>AggTrades · Orderflow Metrics · Signal Research · Kein Trading-Signal · keine Buy-/Sell-, Long-/Short-Entscheidung · keine Ausführung</span></div></div></section>"
    )
    return _layout(
        "Signal Research",
        "Signal Research",
        _hero("Signal Research", "Gefilterter Orderflow-Evidenzpfad für manuelle Forschung.")
        + top
        + summary_grid
        + queue_grid
        + areas
        + evidence_table
        + selected_detail
        + context_matrix
        + retrospective
        + exceptions
    )


def _data_quality_exceptions_page(data: dict[str, Any]) -> str:
    exceptions_rows, exception_items = _quality_exception_rows(data)
    counts = {}
    for item in exception_items:
        counts[str(item.get("reason_code", "UNKNOWN"))] = counts.get(str(item.get("reason_code", "UNKNOWN")), 0) + 1
    cards = "".join(
        f"<article class='card'><div class='card__label'>{_safe(label)}</div><div class='card__value'>{count}</div><div class='card__note'>Read-only exceptions</div></article>"
        for label, count in sorted(counts.items())
    ) or "<article class='card'><div class='card__label'>Exceptions</div><div class='card__value'>0</div><div class='card__note'>Keine dokumentierten Exceptions</div></article>"
    return _layout(
        "Data Quality Exceptions",
        "Data Quality Exceptions",
        _hero("Data Quality Exceptions", "Read-only Sicht auf alle dokumentierten Data-Quality-Abweichungen.")
        + "<p class='count-scope'>Nur dokumentierte Ursachen, keine automatische Rekonstruktion oder stille Korrektur.</p>"
        + f"<div class='grid'>{cards}</div>"
        + "<section class='panel'><div class='panel__head'><h2>Exceptions Register</h2><span class='badge badge--red'>GATED</span></div><div class='table-wrap'><table><thead><tr><th>Component</th><th>Status</th><th>Reason Code</th><th>Reason Text</th><th>Time Window</th><th>Provenance</th><th>Linked Report</th><th>Linked Blocker</th></tr></thead><tbody>"
        + exceptions_rows
        + "</tbody></table></div></section>"
    )


def _health_timeline_page(data: dict[str, Any]) -> str:
    timeline = data.get("timeline", [])
    counts = {}
    for item in timeline:
        counts[str(item.get("event", "UNKNOWN"))] = counts.get(str(item.get("event", "UNKNOWN")), 0) + 1
    summary_cards = "".join(
        f"<article class='card'><div class='card__label'>{_safe(name)}</div><div class='card__value'>{count}</div><div class='card__note'>Persisted events</div></article>"
        for name, count in sorted(counts.items())
    ) or "<article class='card'><div class='card__label'>Timeline Events</div><div class='card__value'>0</div><div class='card__note'>Keine Ereignisse verfügbar</div></article>"
    return _layout(
        "System Timeline",
        "Timeline",
        _hero("System Timeline", "Chronologische Runtime-, Validator-, Research- und Acceptance-Ereignisse.")
        + f"<div class='grid'>{summary_cards}</div><section class='panel'><div class='panel__head'><h2>Health Timeline</h2><span class='badge badge--yellow'>DIAGNOSTIC TIMELINE</span></div><div class='table-wrap'><table><thead><tr><th>event_id</th><th>event_type</th><th>timestamp_utc</th><th>component_id</th><th>previous_status</th><th>new_status</th><th>reason_code</th><th>evidence_reference</th><th>provenance</th><th>source_hash</th></tr></thead><tbody>"
        + _timeline_rows(timeline)
        + "</tbody></table></div><p class='count-scope'>Trading- und Order-Ereignisse werden nicht dargestellt.</p></section>"
    )


def _signal_research_rows(state: DashboardState, data: dict[str, Any] | None = None) -> tuple[str, dict[str, int], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Render a read-only evidence path from already persisted orderflow records."""
    with state.lock:
        observations = [dict(item) for item in state.orderflow_observations[-ORDERFLOW_VISIBLE_LIMIT:]]
        validations = {str(item.get("observation_id")): dict(item) for item in state.orderflow_validations}
        cases = [dict(item) for item in state.research_cases]
        active = [dict(item) for item in state.active_observations]
    counts = {"shown": len(observations), "validated": 0, "awaiting": 0}
    rows: list[str] = []
    for item in reversed(observations):
        validation = validations.get(str(item.get("observation_id")), {})
        complete = bool(validation.get("complete"))
        counts["validated" if complete else "awaiting"] += 1
        evidence = item.get("evidence", [])
        evidence_names = sorted({
            str(value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key"))
            for value in evidence
            if isinstance(value, dict) and (value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key"))
        })
        state_label = "VALIDATED_CONTEXT" if complete else "AWAITING_OUTCOME"
        outcome = validation.get("outcome") if complete else None
        observation_id = str(item.get("observation_id", ""))
        delta = item.get("delta") or item.get("net_delta") or item.get("metrics", {}).get("delta")
        cvd = item.get("cvd_state") or item.get("metrics", {}).get("cvd_state")
        ratio = item.get("buy_sell_ratio") or item.get("metrics", {}).get("buy_sell_ratio")
        trade_frequency = item.get("trade_frequency") or item.get("metrics", {}).get("trade_frequency")
        freshness = item.get("freshness_seconds")
        integrity = item.get("integrity_status") or item.get("validation_status") or ("COMPLETE" if complete else "INSUFFICIENT_EVIDENCE")
        rows.append(
            f"<tr data-type='{_safe(item.get('kind'))}' data-status='{state_label}' data-time='{_safe(item.get('observed_at'))}'>"
            f"<td>{_safe(item.get('observed_at'))}</td><td>{_safe(item.get('symbol') or 'BTCUSDT')}</td><td><a class='mono' href='/signals?id={html.escape(observation_id, quote=True)}'>{_safe(_short(observation_id, 14))}</a></td>"
            f"<td><span class='tag'>{_safe(item.get('kind'))}</span></td><td>{_safe(item.get('timeframe'))}</td><td class='mono'>{_safe(_required('delta', delta))}</td><td>{_safe(_required('cvd_state', cvd))}</td><td>{_safe(_required('buy_sell_ratio', ratio))}</td>"
            f"<td>{_safe(_required('trade_frequency', trade_frequency))}</td><td>{len(evidence)}</td><td>{max(0, int(item.get('missing_evidence_count', len(item.get('missing_evidence', []))) or 0))}</td>"
            f"<td>{_safe(item.get('research_status') or item.get('research_case_status') or ('VALIDATED_CONTEXT' if complete else 'AWAITING_OUTCOME'))}</td>"
            f"<td>{_safe(state_label)}</td><td>{_safe(outcome or 'RETROSPECTIVE')}</td><td>{_safe(_required('data_freshness', freshness))}</td>"
            f"<td><span class='badge badge--{'green' if integrity == 'COMPLETE' else 'yellow'}'>{_safe(integrity)}</span></td><td><a href='/signals?id={html.escape(observation_id, quote=True)}'>Details →</a></td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='17' class='empty'>Noch keine persistierte Orderflow-Evidenz.</td></tr>")
    summary = {
        "shown": len(observations),
        "validated": counts["validated"],
        "awaiting": counts["awaiting"],
        "open_validations": sum(1 for item in validations.values() if not item.get("complete")),
        "closed_cases": sum(1 for item in cases if str(item.get("status", "")).upper() == "CLOSED"),
        "data_quality_summary": (data or {}).get("readiness", {}).get("validation_status") or (data or {}).get("research_quality", {}).get("validation_status") or "UNKNOWN",
    }
    return "".join(rows), counts, summary, cases, active


def _health_center_sections(data: dict[str, Any]) -> str:
    validator = data["validator"]
    latest = validator.get("latest_health", {})
    live = data.get("operational_health", {})
    readiness = data.get("readiness", {})
    audit = data.get("research_audit", {})
    quality = data.get("research_quality", {})
    criteria = readiness.get("criteria", {})
    audit_issues = audit.get("issues", [])
    quality_issues = quality.get("issues", [])
    audit_issue_codes = [str(item.get("code", "UNKNOWN")) for item in audit_issues if isinstance(item, dict)]
    quality_issue_codes = [str(item.get("code", "UNKNOWN")) for item in quality_issues if isinstance(item, dict)]
    coverage = readiness.get("continuous_coverage_percent")
    missing_minutes = readiness.get("continuous_missing_1m_intervals")
    gaps = readiness.get("unresolved_new_gap_count")
    blocker_names = list(readiness.get("blocking_criteria", []))
    core = data.get("core_manifest", {})
    roles = data.get("governance_roles", {})
    validator_state = str(validator.get("status", "UNKNOWN")).upper()
    validator_level = "GREEN" if validator_state in {"RUNNING", "HEALTHY"} else "YELLOW" if validator_state == "COMPLETED" else "RED"
    quality_status = str(quality.get("validation_status", "UNKNOWN")).upper()
    quality_level = "GREEN" if quality_status == "PASS" else "RED" if quality_status == "FAIL" else "UNKNOWN"
    audit_status = str(audit.get("status", "UNKNOWN")).upper()
    audit_level = "GREEN" if audit_status == "PASS" else "RED" if audit_status == "FAIL" else "UNKNOWN"

    def mk(component_id: str, display_name: str, domain: str, status: Any, severity: str, summary: str, reason_code: str, reason_text: str, evidence: list[str], *, observed_since_utc: Any = None, last_checked_utc: Any = None, evidence_count: int | None = None, affected_artifact_count: int | None = None, linked_report: Any = None, linked_blocker: Any = None, recommended_next_action: Any = None, operational_impact: Any = None, scientific_impact: Any = None, governance_impact: Any = None, freshness_seconds: Any = None, provenance: Any = None, source_hash: Any = None, technical_cause: Any = None, affected_windows: Any = None, affected_artifacts: Any = None, status_history: list[str] | None = None, historical_development: Any = None, open_blockers: list[str] | None = None, known_limitations: list[str] | None = None) -> str:
        return _card_markup({
            "component_id": component_id,
            "display_name": display_name,
            "domain": domain,
            "status": status,
            "severity": severity,
            "short_summary": summary,
            "reason_code": reason_code,
            "reason_text": reason_text,
            "observed_since_utc": observed_since_utc,
            "last_checked_utc": last_checked_utc,
            "evidence_count": evidence_count if evidence_count is not None else len(evidence),
            "affected_artifact_count": affected_artifact_count if affected_artifact_count is not None else len(evidence),
            "linked_report": linked_report,
            "linked_blocker": linked_blocker,
            "recommended_next_action": recommended_next_action,
            "operational_impact": operational_impact,
            "scientific_impact": scientific_impact,
            "governance_impact": governance_impact,
            "freshness_seconds": freshness_seconds,
            "provenance": provenance,
            "source_hash": source_hash,
            "technical_cause": technical_cause,
            "affected_windows": affected_windows,
            "affected_artifacts": affected_artifacts,
            "evidence": evidence,
            "status_history": status_history or [],
            "historical_development": historical_development,
            "open_blockers": open_blockers or [],
            "known_limitations": known_limitations or [],
            # Scientific and governance records are immutable evidence snapshots.
            # Their original status remains visible, but must not masquerade as
            # the current operational health of the running process.
            "archived_snapshot": domain != "Operational Health",
        })

    operational = [
        mk("database", "Database", "Operational Health", live.get("database", "UNKNOWN"), "INFO" if live.get("database") == "GREEN" else "CRITICAL", str(data.get("system_health", {}).get("database") or "UNKNOWN"), "DATABASE_HEALTH", "Aktueller Datenbankstatus der laufenden TIM-Runtime.", ["system_health.database", f"checked_at={live.get('checked_at', 'MISSING:checked_at')}"], observed_since_utc=live.get("checked_at"), last_checked_utc=live.get("checked_at"), linked_report="/api/health", recommended_next_action="Bei RED Datenbankverbindung und letzten erfolgreichen Write prüfen.", operational_impact="Speicherzugriff und Persistenz", scientific_impact="Keine Wissenschaft ohne persistente Daten", governance_impact="Betrieb nur mit intakter Persistenz", freshness_seconds=_age_seconds(live.get("checked_at")), provenance=data.get("provenance"), source_hash="N/A:LIVE_STATUS_NOT_HASHED", technical_cause="In-Memory-Status der aktiven Runtime.", affected_windows=live.get("checked_at"), affected_artifacts="/api/health", status_history=[str(live.get("checked_at"))], historical_development="Aktueller Runtime-Status; historischer Validator separat", open_blockers=blocker_names, known_limitations=["Kein separater periodischer SQL-Probezyklus"]),
        mk("stream", "Stream", "Operational Health", live.get("stream", "UNKNOWN"), "INFO" if live.get("stream") == "GREEN" else "CRITICAL", str(data.get("system_health", {}).get("stream") or "UNKNOWN"), "STREAM_STATUS", "Streamstatus plus Frische der zuletzt abgeschlossenen Candle.", [f"last_data_at={live.get('last_data_at', 'MISSING:last_data_at')}", f"data_age_seconds={live.get('data_age_seconds', 'MISSING:data_age_seconds')}"], observed_since_utc=live.get("last_data_at"), last_checked_utc=live.get("checked_at"), linked_report="/api/health", recommended_next_action="Transport- und Reconnect-Logs prüfen.", operational_impact="Candles und Orderflow-Inputs", scientific_impact="Zeitliche Datenabdeckung", governance_impact="Keine Rekonstruktion erlaubt", freshness_seconds=live.get("data_age_seconds"), provenance=data.get("provenance"), source_hash="N/A:LIVE_STATUS_NOT_HASHED", technical_cause="Streamflag und echte Datenfrische.", affected_windows=live.get("last_data_at"), affected_artifacts="/api/health", status_history=[str(live.get("last_data_at"))], historical_development="Öffentlicher Stream", open_blockers=blocker_names, known_limitations=["Keine private Feeds"], affected_artifact_count=2),
        mk("dashboard", "Dashboard", "Operational Health", live.get("dashboard", "UNKNOWN"), "INFO", "HTTP 200 · aktuelle Antwort", "DASHBOARD_HEALTH", "Diese Seite wurde von der aktiven Dashboard-Runtime ausgeliefert.", [f"checked_at={live.get('checked_at', 'MISSING:checked_at')}", "/api/health"], observed_since_utc=live.get("checked_at"), last_checked_utc=live.get("checked_at"), linked_report="/api/health", recommended_next_action="Bei RED Runtime-Log und Port 8765 prüfen.", operational_impact="Bedienoberfläche", scientific_impact="Sichtbarkeit von Evidenz", governance_impact="Read-only UI muss erreichbar sein", freshness_seconds=_age_seconds(live.get("checked_at")), provenance=data.get("provenance"), source_hash="N/A:LIVE_STATUS_NOT_HASHED", technical_cause="Aktuelle HTTP-Auslieferung.", affected_windows=live.get("checked_at"), affected_artifacts="/api/health", status_history=[str(live.get("checked_at"))], historical_development="Aktueller Dashboard-Prozess", open_blockers=blocker_names, known_limitations=["Keine Schreibfunktionen"]),
        mk("capture_process", "Capture Process", "Operational Health", "GREEN" if live.get("stream") == "GREEN" and live.get("database") == "GREEN" else "RED", "INFO", _required("capture_process", data.get("system_health", {}).get("stream")), "CAPTURE_PROCESS", "TIM erfasst öffentliche Marktdaten deterministisch.", ["system_health.stream", "database.latest_health"], observed_since_utc=data.get("timestamp"), last_checked_utc=data.get("timestamp"), linked_report="data/operational/state.json", recommended_next_action="Bei Störung den Transportpfad und Persistenzpfad prüfen.", operational_impact="Rohdatenaufnahme", scientific_impact="Kontinuität der Eingangsdaten", governance_impact="Keine automatische Rekonstruktion", freshness_seconds=_age_seconds(data.get("timestamp")), provenance=data.get("provenance"), source_hash=data.get("research_audit", {}).get("audit_hash"), technical_cause="Beobachteter Capture-Prozess.", affected_windows=data.get("timestamp"), affected_artifacts="data/operational/state.json", status_history=[str(data.get("timestamp"))], historical_development="Capture pipeline", open_blockers=blocker_names, known_limitations=["Kein Side-channel capture"]),
        mk("websocket_connectivity", "WebSocket Connectivity", "Operational Health", live.get("stream", "UNKNOWN"), "INFO" if data.get("system_health", {}).get("stream") == "running" else "CRITICAL", _required("websocket_connectivity", data.get("system_health", {}).get("stream")), "WEBSOCKET_CONNECTIVITY", "Verbindung zum öffentlichen WebSocket-Stream.", ["system_health.stream"], observed_since_utc=data.get("timestamp"), last_checked_utc=data.get("timestamp"), linked_report="data/operational/state.json", recommended_next_action="Reconnect- und Timeout-Logs prüfen.", operational_impact="Transportstabilität", scientific_impact="Lückenfreie Beobachtung", governance_impact="Betrieb nur bei stabiler Verbindung", freshness_seconds=_age_seconds(data.get("timestamp")), provenance=data.get("provenance"), source_hash=data.get("research_audit", {}).get("audit_hash"), technical_cause="Transportstatus des Streams.", affected_windows=data.get("timestamp"), affected_artifacts="data/operational/state.json", status_history=[str(data.get("timestamp"))], historical_development="Transport layer", open_blockers=blocker_names, known_limitations=["Kein externes Failover"]),
        mk("persistency", "Persistency", "Operational Health", live.get("database", "UNKNOWN"), "INFO" if live.get("database") == "GREEN" else "CRITICAL", str(data.get("system_health", {}).get("database") or "UNKNOWN"), "PERSISTENCY", "Aktueller Persistenzstatus der laufenden Runtime.", [f"database={data.get('system_health', {}).get('database', 'MISSING:database_status')}", f"last_data_at={live.get('last_data_at', 'MISSING:last_data_at')}"], observed_since_utc=live.get("last_data_at"), last_checked_utc=live.get("checked_at"), linked_report="/api/health", recommended_next_action="Letzten erfolgreichen Write und DB-Status prüfen.", operational_impact="Datenhaltung", scientific_impact="Persistierte Reproduzierbarkeit", governance_impact="Keine Schreibfehler toleriert", freshness_seconds=live.get("data_age_seconds"), provenance=data.get("provenance"), source_hash="N/A:LIVE_STATUS_NOT_HASHED", technical_cause="Aktueller DB-Status plus letzte persistierte Candle.", affected_windows=live.get("last_data_at"), affected_artifacts="/api/health", status_history=[str(live.get("last_data_at"))], historical_development="Aktuelle Persistenz; historischer Validator separat", open_blockers=blocker_names, known_limitations=["Kein Backfill"]),
        mk("queue", "Queue", "Operational Health", "GREEN", "INFO", f"{live.get('queue_depth', 0)} wartende Nachrichten · Direct Await", "QUEUE", "TIM besitzt keine separate Anwendungsqueue: Der WebSocket-Reader wartet auf die vollständige Verarbeitung jedes Trades.", [f"queue_depth={live.get('queue_depth', 0)}", f"queue_model={live.get('queue_model', 'DIRECT_AWAIT_NO_APPLICATION_QUEUE')}"], observed_since_utc=live.get("runtime_started_at"), last_checked_utc=live.get("checked_at"), linked_report="/api/health", recommended_next_action="Bei steigender Datenlatenz Handler-Laufzeit und WebSocket-Backpressure prüfen.", operational_impact="Keine unkontrollierte interne Warteschlange", scientific_impact="Sequentielle Verarbeitung bewahrt Eingangsreihenfolge", governance_impact="Messwert beschreibt ausschließlich die Anwendungsqueue", freshness_seconds=_age_seconds(live.get("checked_at")), provenance=data.get("provenance"), source_hash="N/A:LIVE_STATUS_NOT_HASHED", technical_cause="Direktes await des Trade-Handlers; keine asyncio.Queue im TIM-Pfad.", affected_windows=live.get("checked_at"), affected_artifacts="src/data_ingestion/binance_ws.py", status_history=[str(live.get("checked_at"))], historical_development="Direkter WebSocket-zu-Handler-Pfad", open_blockers=blocker_names, known_limitations=["Die interne Queue der websockets-Bibliothek wird nicht als öffentliche Metrik exponiert"]),
        mk("storage", "Storage", "Operational Health", live.get("database", "UNKNOWN"), "INFO" if latest.get("database", {}).get("status") == "HEALTHY" else "HIGH", "Persistente Datenspeicherung", "STORAGE", "Storage-Betrieb wird über Datenbank- und Qualitätsstatus abgeleitet.", ["database.latest_health", "research_quality.latest"], observed_since_utc=data.get("timestamp"), last_checked_utc=data.get("timestamp"), linked_report="data/research/quality/latest.json", recommended_next_action="Max RSS und DB-Persistenz beobachten.", operational_impact="Speicher- und Persistenzpfad", scientific_impact="Artefaktstabilität", governance_impact="Betriebsgrenze der Persistenz", freshness_seconds=_age_seconds(data.get("timestamp")), provenance=data.get("provenance"), source_hash=data.get("research_quality", {}).get("report_hash"), technical_cause="Storage über persistente DB repräsentiert.", affected_windows=data.get("timestamp"), affected_artifacts="data/research/quality/latest.json", status_history=[str(data.get("timestamp"))], historical_development="Storage layer", open_blockers=blocker_names, known_limitations=["Kein dedizierter Storage-Monitor"], affected_artifact_count=2),
        mk("runtime", "Runtime", "Operational Health", live.get("runtime", "UNKNOWN"), "INFO", _duration(live.get("runtime_started_at"), data.get("timestamp")), "RUNTIME", "Laufzeit des aktuell antwortenden TIM-Prozesses.", [f"runtime_started_at={live.get('runtime_started_at', 'MISSING:runtime_started_at')}", f"checked_at={live.get('checked_at', 'MISSING:checked_at')}"], observed_since_utc=live.get("runtime_started_at"), last_checked_utc=live.get("checked_at"), linked_report="/api/health", recommended_next_action="Ungeplante Neustarts im Timeline-Register untersuchen.", operational_impact="Lebenszeichen der Anwendung", scientific_impact="Kontinuierlicher Beobachtungsraum", governance_impact="Core Freeze bleibt unverändert", freshness_seconds=_age_seconds(live.get("checked_at")), provenance=data.get("provenance"), source_hash="N/A:LIVE_STATUS_NOT_HASHED", technical_cause="Aktuell antwortender Dashboard-/Runtime-Prozess.", affected_windows=live.get("runtime_started_at"), affected_artifacts="/api/health", status_history=[str(live.get("runtime_started_at"))], historical_development="Aktuelle Runtime; Acceptance-Laufzeit separat", open_blockers=blocker_names, known_limitations=["Prozessstartzeit ist instanzlokal"]),
        mk("ollama_availability", "Ollama Availability", "Operational Health", "GREEN" if live.get("ollama_availability") in {"AVAILABLE", "DISABLED_BY_POLICY"} else "RED", "INFO" if live.get("ollama_availability") in {"AVAILABLE", "DISABLED_BY_POLICY"} else "WARNING", "Optional deaktiviert · Core nicht abhängig" if live.get("ollama_availability") == "DISABLED_BY_POLICY" else str(live.get("ollama_availability", "UNAVAILABLE")), "OLLAMA_AVAILABILITY", "Ollama ist optional. Deaktivierung gemäß Konfiguration ist ein gesunder Zustand; bei Aktivierung wird die lokale API beim Start geprüft.", [f"enabled={live.get('ollama_enabled', False)}", f"availability={live.get('ollama_availability', 'DISABLED_BY_POLICY')}"], observed_since_utc=live.get("runtime_started_at"), last_checked_utc=live.get("checked_at"), linked_report="/api/health", recommended_next_action="Nur bei aktiviertem und UNAVAILABLE gemeldetem Ollama den lokalen Dienst prüfen.", operational_impact="Kein Einfluss auf Marktdatenerfassung", scientific_impact="Optionale Erklärungen, keine Regel- oder Persistenzabhängigkeit", governance_impact="Ollama bleibt außerhalb des deterministischen Core", freshness_seconds=_age_seconds(live.get("checked_at")), provenance=data.get("provenance"), source_hash="N/A:LIVE_STATUS_NOT_HASHED", technical_cause="Expliziter Konfigurations- und Startzeitstatus.", affected_windows=live.get("checked_at"), affected_artifacts="config/settings.py", status_history=[str(live.get("checked_at"))], historical_development="Optionales lokales Modell", open_blockers=blocker_names, known_limitations=["Keine periodische Modell-Inferenz als Health-Probe"]),
    ]

    deterministic = quality.get("checks", {}).get("deterministic")
    deterministic_evidence_pass = (
        criteria.get("replay") == "PASS"
        and criteria.get("hash_consistency") == "PASS"
    )
    scientific = [
        mk("continuous_coverage", "Continuous Coverage", "Scientific Health", "GREEN" if criteria.get("continuous_coverage") == "PASS" else "RED", "INFO" if criteria.get("continuous_coverage") == "PASS" else "CRITICAL", f"{coverage}% · {missing_minutes} Minuten fehlen", "CONTINUOUS_COVERAGE", f"{readiness.get('continuous_persisted_1m_intervals', 'MISSING:continuous_persisted_1m_intervals')} von {readiness.get('continuous_expected_1m_intervals', 'MISSING:continuous_expected_1m_intervals')} erwarteten Minuten sind persistiert.", [f"window={readiness.get('continuous_window_start', 'MISSING:continuous_window_start')} → {readiness.get('continuous_window_end', 'MISSING:continuous_window_end')}", "data/research/status/tim_v1_readiness.json"], observed_since_utc=readiness.get("generated_at"), last_checked_utc=readiness.get("generated_at"), linked_report="data/research/status/tim_v1_readiness.json", linked_blocker="continuous_coverage", recommended_next_action="Neuen zusammenhängenden Beobachtungszeitraum ohne Rekonstruktion fortführen.", operational_impact="Keine operative Korrektur", scientific_impact="Blockiert Scientific Readiness", governance_impact="Data Gap Governance", freshness_seconds=_age_seconds(readiness.get("generated_at")), provenance=readiness.get("provenance"), source_hash=readiness.get("artifact_hash"), technical_cause="Persistierte 1m-Abdeckung unter Ziel.", affected_windows=f"{readiness.get('continuous_window_start', 'MISSING:continuous_window_start')} → {readiness.get('continuous_window_end', 'MISSING:continuous_window_end')}", affected_artifacts="data/research/status/tim_v1_readiness.json", status_history=[str(readiness.get("generated_at"))], historical_development="Continuous coverage window", open_blockers=blocker_names, known_limitations=["Coverage historical and continuous window differ"]),
        mk("validator", "Validator", "Scientific Health", validator_level, "WARNING" if validator_level == "YELLOW" else "INFO", f"{validator.get('status', 'UNKNOWN')} · {validator.get('cycles', 0)} Zyklen", "VALIDATOR", "Persistierter Acceptance-Validator und wissenschaftliche Bewertung.", [f"last_cycle_at={validator.get('last_cycle_at', 'MISSING:last_cycle_at')}", f"acceptance_score={validator.get('acceptance', {}).get('score', 'MISSING:score')}", "docs/TIM_72H_ACCEPTANCE_REPORT.md"], observed_since_utc=validator.get("started_at"), last_checked_utc=validator.get("last_cycle_at"), linked_report="docs/TIM_72H_ACCEPTANCE_REPORT.md", linked_blocker="manual_scientific_review" if criteria.get("manual_scientific_review") != "PASS" else None, recommended_next_action="Acceptance-Report und offene Readiness-Kriterien gemeinsam prüfen.", operational_impact="Wissenschaftlicher Gatekeeper", scientific_impact="Freigabe- und Integritätskontext", governance_impact="Manueller Review benötigt", freshness_seconds=_age_seconds(validator.get("last_cycle_at")), provenance=data.get("provenance"), source_hash=validator.get("acceptance", {}).get("report_path"), technical_cause="Persistierter Validator- und Acceptance-Status.", affected_windows=validator.get("last_cycle_at"), affected_artifacts="docs/TIM_72H_ACCEPTANCE_REPORT.md", status_history=[str(validator.get("last_cycle_at"))], historical_development="Validator cycle", open_blockers=blocker_names, known_limitations=["Completed state is read-only"]),
        mk("replay", "Replay", "Scientific Health", "GREEN" if criteria.get("replay") == "PASS" else "RED", "INFO" if criteria.get("replay") == "PASS" else "CRITICAL", str(criteria.get("replay", "UNKNOWN")), "REPLAY", "Persistierter deterministischer Replay-Status.", [f"benchmark={latest.get('benchmark', 'MISSING:benchmark')}", "data/research/status/tim_v1_readiness.json"], observed_since_utc=readiness.get("generated_at"), last_checked_utc=readiness.get("generated_at"), linked_report="data/research/status/tim_v1_readiness.json", linked_blocker="replay" if criteria.get("replay") != "PASS" else None, recommended_next_action="Bei Abweichung Dataset- und Output-Hashes vergleichen.", operational_impact="Reproduzierbarkeit", scientific_impact="Benchmark-Stabilität", governance_impact="Versionierte Replays", freshness_seconds=_age_seconds(readiness.get("generated_at")), provenance=readiness.get("provenance"), source_hash=readiness.get("output_hash"), technical_cause="Deterministischer Replay-Check.", affected_windows=readiness.get("generated_at"), affected_artifacts="data/research/status/tim_v1_readiness.json", status_history=[str(readiness.get("generated_at"))], historical_development="Replay validation", open_blockers=blocker_names, known_limitations=["Replay result is historical"]),
        mk("determinism", "Determinism", "Scientific Health", "GREEN" if deterministic_evidence_pass else "RED", "INFO" if deterministic_evidence_pass else "HIGH", "PASS · Replay und Hash-Konsistenz" if deterministic_evidence_pass else "FAIL", "DETERMINISM", "Der historische Quality-Report ist wegen Artefakt-Governance fehlgeschlagen; Replay und Hash-Konsistenz werden separat bewertet.", quality_issue_codes + ["criteria.replay", "criteria.hash_consistency"], observed_since_utc=quality.get("generated_at"), last_checked_utc=quality.get("generated_at"), linked_report="data/research/quality/latest.json", linked_blocker=None if deterministic_evidence_pass else "determinism", recommended_next_action="Historische Audit-Issues getrennt vom Determinismus bewerten; Artefakte nicht verändern.", operational_impact="Kein aktueller Betriebsfehler", scientific_impact="Replay und Hash-Konsistenz sind die maßgebliche Determinismus-Evidenz", governance_impact="Artefakt-Governance bleibt separat offen", freshness_seconds=_age_seconds(quality.get("generated_at")), provenance=quality.get("read_only_sources", data.get("provenance")), source_hash=quality.get("report_hash"), technical_cause="Historischer Quality-Status enthält zusätzliche Governance-Issues.", affected_windows=quality.get("generated_at"), affected_artifacts="data/research/quality/latest.json", status_history=[str(quality.get("generated_at"))], historical_development="Historical quality snapshot", open_blockers=blocker_names, known_limitations=["Snapshot ist historisch"]),
        mk("provenance", "Provenance", "Scientific Health", "GREEN" if criteria.get("new_artifact_provenance") == "PASS" and "PROVENANCE_INCOMPLETE" not in quality_issue_codes else "YELLOW" if criteria.get("new_artifact_provenance") == "PASS" else "RED", "INFO" if "PROVENANCE_INCOMPLETE" not in quality_issue_codes else "WARNING", "Neue Artefakte PASS · Historisch unvollständig" if "PROVENANCE_INCOMPLETE" in quality_issue_codes else str(criteria.get("new_artifact_provenance", "UNKNOWN")), "PROVENANCE", "Neue Artefakte erfüllen das Gate; der historische Quality-Report dokumentiert unveränderte Provenance-Lücken.", [code for code in quality_issue_codes if "PROVENANCE" in code or "DOCUMENTATION" in code] + ["data/research/quality/latest.json"], observed_since_utc=quality.get("generated_at"), last_checked_utc=quality.get("generated_at"), linked_report="data/research/quality/latest.json", linked_blocker="historical_provenance" if "PROVENANCE_INCOMPLETE" in quality_issue_codes else None, recommended_next_action="Historische Lücken dokumentiert lassen; keine rückwirkenden Hashes erzeugen.", operational_impact="Kein aktueller Betriebsfehler", scientific_impact="Historische Vergleichbarkeit eingeschränkt", governance_impact="Keine Retro-Korrektur", freshness_seconds=_age_seconds(quality.get("generated_at")), provenance=readiness.get("provenance"), source_hash=readiness.get("artifact_hash"), technical_cause="Historische Provenance-Abweichungen dokumentiert.", affected_windows=quality.get("generated_at"), affected_artifacts="data/research/quality/latest.json", status_history=[str(quality.get("generated_at"))], historical_development="Historical provenance report", open_blockers=blocker_names, known_limitations=["Historical gaps may be unrecoverable"]),
        mk("hash_integrity", "Hash Integrity", "Scientific Health", "GREEN" if criteria.get("hash_consistency") == "PASS" and "OUTPUT_HASH_MISMATCH" not in audit_issue_codes else "YELLOW", "INFO" if criteria.get("hash_consistency") == "PASS" and "OUTPUT_HASH_MISMATCH" not in audit_issue_codes else "WARNING", "P0 untersucht · Contract-Semantik offen" if "OUTPUT_HASH_MISMATCH" in audit_issue_codes else str(criteria.get("hash_consistency", "UNKNOWN")), "HASH_INTEGRITY", "Der Audit meldet OUTPUT_HASH_MISMATCH; die bestehende P0-Untersuchung klassifiziert die Ursache als Hash-Domänen-/Vertragsproblem.", [code for code in audit_issue_codes if "HASH" in code] + ["data/research/audit/latest.json"], observed_since_utc=audit.get("generated_at"), last_checked_utc=audit.get("generated_at"), linked_report="data/research/audit/latest.json", linked_blocker="hash_contract_v2" if "OUTPUT_HASH_MISMATCH" in audit_issue_codes else None, recommended_next_action="Historische Artefakte unverändert lassen; HC-1.0 erst für V2 verwenden.", operational_impact="Hash-Interpretation", scientific_impact="Artefaktvergleich", governance_impact="Vertragsdisziplin", freshness_seconds=_age_seconds(audit.get("generated_at")), provenance=audit.get("read_only") if audit.get("read_only") is not None else data.get("provenance"), source_hash=audit.get("audit_hash"), technical_cause="Hash-Domänen-/Vertragsproblem.", affected_windows=audit.get("generated_at"), affected_artifacts="data/research/audit/latest.json", status_history=[str(audit.get("generated_at"))], historical_development="Hash audit", open_blockers=blocker_names, known_limitations=["No retroactive rewrite"]),
        mk("research_integrity", "Research Integrity", "Scientific Health", str(validator.get("research_health", {}).get("level", "YELLOW")).upper(), "INFO" if str(validator.get("research_health", {}).get("level", "YELLOW")).upper() == "GREEN" else "WARNING", f"{validator.get('research_health', {}).get('trigger_duplicates', 0)} Trigger-Duplikate", "RESEARCH_INTEGRITY", "Persistierter Research-Integrity-Check für Reports, Provenance, Schema und Trigger-Deduplizierung.", ["data/operational/state.json", f"checked_at={validator.get('research_health', {}).get('checked_at', 'MISSING:checked_at')}"], observed_since_utc=validator.get("research_health", {}).get("checked_at"), last_checked_utc=validator.get("research_health", {}).get("checked_at"), linked_report="data/operational/state.json", linked_blocker="research_integrity" if validator.get("research_health", {}).get("level") != "GREEN" else None, recommended_next_action="Bei RED den letzten Research-Cycle-Check und betroffene Artefakte prüfen.", operational_impact="Research pipeline integrity", scientific_impact="Trigger-Deduplizierung", governance_impact="Auditability", freshness_seconds=_age_seconds(validator.get("research_health", {}).get("checked_at")), provenance=data.get("provenance"), source_hash=validator.get("research_health", {}).get("checked_at"), technical_cause="Research-Integrity-Report.", affected_windows=validator.get("research_health", {}).get("checked_at"), affected_artifacts="data/operational/state.json", status_history=[str(validator.get("research_health", {}).get("checked_at"))], historical_development="Research integrity", open_blockers=blocker_names, known_limitations=["Historical findings stay readable"]),
        mk("data_quality", "Data Quality", "Scientific Health", quality_level, "INFO" if quality_status == "PASS" else "HIGH", f"{quality.get('validation_status', 'UNKNOWN')} · {gaps} ungeklärte Gaps", "DATA_QUALITY", f"Coverage {coverage}%; {missing_minutes} Minuten fehlen. Research Quality enthält {len(quality_issues)} offene Issues.", quality_issue_codes + ["data/research/quality/latest.json"], observed_since_utc=quality.get("generated_at"), last_checked_utc=quality.get("generated_at"), linked_report="data/research/quality/latest.json", linked_blocker="data_gap_register", recommended_next_action="DATA_GAP-Register und Provenance-Issues abarbeiten; keine Daten rekonstruieren.", operational_impact="Datenqualität", scientific_impact="Reproduzierbarkeit und Coverage", governance_impact="Readiness blockiert", freshness_seconds=_age_seconds(quality.get("generated_at")), provenance=quality.get("read_only_sources", data.get("provenance")), source_hash=quality.get("report_hash"), technical_cause="Quality validation report.", affected_windows=f"{readiness.get('continuous_window_start', 'MISSING:continuous_window_start')} → {readiness.get('continuous_window_end', 'MISSING:continuous_window_end')}", affected_artifacts="data/research/quality/latest.json", status_history=[str(quality.get("generated_at"))], historical_development="Data quality report", open_blockers=blocker_names, known_limitations=["No reconstruction"]),
        mk("acceptance", "Acceptance", "Scientific Health", "GREEN" if validator.get("acceptance", {}).get("score", 0) >= 0.95 else "YELLOW", "INFO" if validator.get("acceptance", {}).get("score", 0) >= 0.95 else "WARNING", f"{float(validator.get('acceptance', {}).get('score', 0)) * 100:.0f}% · {validator.get('acceptance', {}).get('status', 'UNKNOWN')}", "ACCEPTANCE", "72h Acceptance ist abgeschlossen, das dokumentierte Ergebnis erreicht jedoch nicht das 95%-GO-Kriterium.", [str(validator.get("acceptance", {}).get("report_path", "MISSING:report_path")), "data/operational/state.json"], observed_since_utc=validator.get("acceptance", {}).get("checked_at"), last_checked_utc=validator.get("acceptance", {}).get("checked_at"), linked_report=validator.get("acceptance", {}).get("report_path"), linked_blocker="coverage_review" if validator.get("acceptance", {}).get("score", 0) < 0.95 else None, recommended_next_action="Offene Coverage-, Gap- und Review-Blocker schließen.", operational_impact="Governance gate", scientific_impact="Review milestone", governance_impact="Manual review", freshness_seconds=_age_seconds(validator.get("acceptance", {}).get("checked_at")), provenance=data.get("provenance"), source_hash=validator.get("acceptance", {}).get("report_path"), technical_cause="Acceptance report status.", affected_windows=validator.get("acceptance", {}).get("checked_at"), affected_artifacts="docs/TIM_72H_ACCEPTANCE_REPORT.md", status_history=[str(validator.get("acceptance", {}).get("checked_at"))], historical_development="Acceptance gate", open_blockers=blocker_names, known_limitations=["Readiness remains open"]),
    ]

    governance = [
        mk("observe_only", "OBSERVE-only Status", "Governance Health", "GREEN" if data.get("mode") == "OBSERVE" else "RED", "INFO" if data.get("mode") == "OBSERVE" else "CRITICAL", str(data.get("mode", "UNKNOWN")), "OBSERVE_ONLY", "Dashboard und Runtime melden Forschungsmodus ohne Ausführung.", [str(data.get("safety")), str(data.get("provenance"))], observed_since_utc=data.get("timestamp"), last_checked_utc=data.get("timestamp"), linked_report="config/core_manifest.json", recommended_next_action="Bei Abweichung Betrieb sofort stoppen und untersuchen.", operational_impact="Ausführung verboten", scientific_impact="Read-only invariant", governance_impact="Core freeze protected", freshness_seconds=_age_seconds(data.get("timestamp")), provenance=data.get("provenance"), source_hash=data.get("research_audit", {}).get("audit_hash"), technical_cause="Forschungsmodus im Snapshot.", affected_windows=data.get("timestamp"), affected_artifacts="config/core_manifest.json", status_history=[str(data.get("timestamp"))], historical_development="Operational boundary", open_blockers=blocker_names, known_limitations=["No execution controls"]),
        mk("core_freeze", "Core Freeze Status", "Governance Health", "GREEN" if core.get("status") == "FROZEN" else "YELLOW", "INFO" if core.get("status") == "FROZEN" else "WARNING", str(core.get("status", "Nicht im Manifest ausgewiesen")), "CORE_FREEZE", "Status wird ausschließlich aus config/core_manifest.json gelesen.", [f"core_version={core.get('core_version', core.get('version', 'MISSING:core_version'))}", "config/core_manifest.json"], observed_since_utc=core.get("frozen_at") or core.get("generated_at") or "UNSPECIFIED_IN_FROZEN_MANIFEST", last_checked_utc=data.get("timestamp"), linked_report="config/core_manifest.json", recommended_next_action="Core-Manifest vor funktionalen Änderungen prüfen.", operational_impact="Core protection", scientific_impact="Frozen reference baseline", governance_impact="No core edits", freshness_seconds=_age_seconds(data.get("timestamp")), provenance=core.get("provenance", data.get("provenance")), source_hash=core.get("artifact_hash") or core.get("core_version"), technical_cause="Frozen core manifest.", affected_windows=core.get("frozen_at") or core.get("generated_at") or "UNSPECIFIED_IN_FROZEN_MANIFEST", affected_artifacts="config/core_manifest.json", status_history=[str(core.get("frozen_at") or core.get("generated_at") or "UNSPECIFIED_IN_FROZEN_MANIFEST")], historical_development="Core freeze", open_blockers=blocker_names, known_limitations=["Das eingefrorene Manifest enthält keinen frozen_at-Zeitstempel"]),
        mk("open_blockers", "Offene Blocker", "Governance Health", "YELLOW" if blocker_names else "GREEN", "WARNING", ", ".join(blocker_names) or "Keine persistierten Blocker", "OPEN_BLOCKERS", f"{len(blocker_names)} persistierte Blocker verhindern eine automatische Freigabe.", blocker_names + ["data/research/status/tim_v1_readiness.json"], observed_since_utc=readiness.get("generated_at"), last_checked_utc=readiness.get("generated_at"), linked_report="data/research/status/tim_v1_readiness.json", linked_blocker=",".join(blocker_names) if blocker_names else None, recommended_next_action="Blocker verifizieren und manuellen Scientific Review durchführen.", operational_impact="Freigabestatus", scientific_impact="Readiness gate", governance_impact="V2 planning blocked", freshness_seconds=_age_seconds(readiness.get("generated_at")), provenance=readiness.get("provenance"), source_hash=readiness.get("artifact_hash"), technical_cause="Persistierte blocker list.", affected_windows=readiness.get("generated_at"), affected_artifacts="data/research/status/tim_v1_readiness.json", status_history=[str(readiness.get("generated_at"))], historical_development="Readiness blockers", open_blockers=blocker_names, known_limitations=["No auto-close"]),
        mk("scientific_review", "Scientific Review Status", "Governance Health", "GREEN" if criteria.get("manual_scientific_review") == "PASS" else "YELLOW", "INFO" if criteria.get("manual_scientific_review") == "PASS" else "WARNING", str(criteria.get("manual_scientific_review", "UNKNOWN")), "SCIENTIFIC_REVIEW", "Die Freigabe erfordert eine dokumentierte manuelle Entscheidung.", ["manual_scientific_review", "eligible_for_scientific_review=" + str(readiness.get("eligible_for_scientific_review"))], observed_since_utc=readiness.get("generated_at"), last_checked_utc=readiness.get("generated_at"), linked_report="data/research/status/tim_v1_readiness.json", linked_blocker="manual_scientific_review", recommended_next_action="Reviewer, Evidenzbasis und Entscheidung protokollieren.", operational_impact="Review gate", scientific_impact="Formal approval", governance_impact="Manual decision required", freshness_seconds=_age_seconds(readiness.get("generated_at")), provenance=readiness.get("provenance"), source_hash=readiness.get("artifact_hash"), technical_cause="Manual review still open.", affected_windows=readiness.get("generated_at"), affected_artifacts="data/research/status/tim_v1_readiness.json", status_history=[str(readiness.get("generated_at"))], historical_development="Scientific review", open_blockers=blocker_names, known_limitations=["Manual review cannot be automated"]),
        mk("hash_contract", "Hash Contract Status", "Governance Health", "GREEN" if quality.get("validation_status") == "PASS" and "OUTPUT_HASH_MISMATCH" not in audit_issue_codes else "YELLOW", "INFO" if quality.get("validation_status") == "PASS" and "OUTPUT_HASH_MISMATCH" not in audit_issue_codes else "WARNING", "HC-1.0 referenziert; V2-Contract vorbereiten", "HASH_CONTRACT", "Der Audit meldet OUTPUT_HASH_MISMATCH; die Ursache ist ein Vertrags-/Domänenproblem.", [code for code in audit_issue_codes if "HASH" in code] + ["data/research/audit/latest.json"], observed_since_utc=audit.get("generated_at"), last_checked_utc=audit.get("generated_at"), linked_report="data/research/audit/latest.json", linked_blocker="hash_contract_v2" if "OUTPUT_HASH_MISMATCH" in audit_issue_codes else None, recommended_next_action="HC-1.0 nur als Referenz beibehalten.", operational_impact="Contract semantics", scientific_impact="Artifact comparison", governance_impact="Future versioned contract only", freshness_seconds=_age_seconds(audit.get("generated_at")), provenance=audit.get("provenance", data.get("provenance")), source_hash=audit.get("audit_hash"), technical_cause="Hash domain mismatch documented in audit.", affected_windows=audit.get("generated_at"), affected_artifacts="data/research/audit/latest.json", status_history=[str(audit.get("generated_at"))], historical_development="Hash contract", open_blockers=blocker_names, known_limitations=["Historical hashes remain frozen"]),
        mk("readiness", "Readiness Status", "Governance Health", "GREEN" if readiness.get("readiness_status") == "READY_FOR_V2" else "YELLOW", "INFO" if readiness.get("readiness_status") == "READY_FOR_V2" else "WARNING", str(readiness.get("readiness_status", "UNKNOWN")), "READINESS", f"{len(blocker_names)} persistierte Blocker verhindern eine automatische Freigabe.", blocker_names + ["data/research/status/tim_v1_readiness.json"], observed_since_utc=readiness.get("generated_at"), last_checked_utc=readiness.get("generated_at"), linked_report="data/research/status/tim_v1_readiness.json", linked_blocker=",".join(blocker_names) if blocker_names else None, recommended_next_action="Blocker verifizieren und Review durchführen.", operational_impact="V2 gate", scientific_impact="Operational readiness", governance_impact="Planning only", freshness_seconds=_age_seconds(readiness.get("generated_at")), provenance=readiness.get("provenance"), source_hash=readiness.get("artifact_hash"), technical_cause="Readiness report state.", affected_windows=readiness.get("generated_at"), affected_artifacts="data/research/status/tim_v1_readiness.json", status_history=[str(readiness.get("generated_at"))], historical_development="Readiness assessment", open_blockers=blocker_names, known_limitations=["Not automatically promoted"]),
        mk("last_audit", "Letzter Research Audit", "Governance Health", audit_level, "INFO" if audit_status == "PASS" else "HIGH", f"{audit_status} · {audit.get('artifacts_failed', '—')} von {audit.get('artifacts_checked', '—')} fehlgeschlagen", "LAST_AUDIT", ", ".join(audit_issue_codes) or "Keine Audit-Issues dokumentiert.", audit_issue_codes + ["data/research/audit/latest.json"], observed_since_utc=audit.get("generated_at"), last_checked_utc=audit.get("generated_at"), linked_report="data/research/audit/latest.json", linked_blocker="audit", recommended_next_action="Fehlgeschlagene Artefakte anhand des unveränderten Auditberichts prüfen.", operational_impact="Audit trail", scientific_impact="Evidence traceability", governance_impact="Audit governance", freshness_seconds=_age_seconds(audit.get("generated_at")), provenance=audit.get("provenance", data.get("provenance")), source_hash=audit.get("audit_hash"), technical_cause="Audit report results.", affected_windows=audit.get("generated_at"), affected_artifacts="data/research/audit/latest.json", status_history=[str(audit.get("generated_at"))], historical_development="Audit trail", open_blockers=blocker_names, known_limitations=["Audit cannot rewrite history"]),
        mk("responsible_role", "Verantwortliche Rolle", "Governance Health", "GREEN" if roles.get("scientific_release_authority") else "YELLOW", "INFO" if roles.get("scientific_release_authority") else "WARNING", str(roles.get("scientific_release_authority") or "Manuelle Rollenzuweisung ausstehend"), "RESPONSIBLE_ROLE", "Die Rolle genehmigt wissenschaftliche Freigaben; TIM selbst kann keine Freigabe erteilen.", [f"scientific_release_authority={roles.get('scientific_release_authority', 'NOT_ASSIGNED')}", f"core_owner={roles.get('core_owner', 'NOT_ASSIGNED')}", "config/governance_roles.json"], observed_since_utc=roles.get("effective_from"), last_checked_utc=data.get("timestamp"), linked_report="config/governance_roles.json", recommended_next_action="Personelle Benennung außerhalb des Systems dokumentieren; Rollenvertrag unverändert halten.", operational_impact="Eindeutige menschliche Verantwortung", scientific_impact="Nachvollziehbare Review-Autorität", governance_impact="TIM darf sich nicht selbst freigeben", freshness_seconds=_age_seconds(data.get("timestamp")), provenance=roles.get("provenance", "TIM_GOVERNANCE_DOCUMENT"), source_hash=roles.get("artifact_hash", "N/A:ROLE_CONTRACT_NOT_SELF_HASHED"), technical_cause="Expliziter rollenbasierter Governance-Vertrag.", affected_windows=roles.get("effective_from"), affected_artifacts="config/governance_roles.json", status_history=[str(roles.get("effective_from"))], historical_development="Rollenvertrag gilt prospektiv", open_blockers=blocker_names, known_limitations=["Die konkrete natürliche Person wird bewusst nicht in Runtime-Konfiguration gespeichert"]),
        mk("release_status", "Freigabestatus", "Governance Health", "YELLOW" if readiness.get("v2_approved") is not True else "GREEN", "WARNING", "NOT_READY_FOR_V2" if readiness.get("v2_approved") is not True else "READY_FOR_V2", "RELEASE_STATUS", "Die finale Freigabe bleibt manuell und unverändert ausstehend.", blocker_names + ["data/research/status/tim_v1_readiness.json"], observed_since_utc=readiness.get("generated_at"), last_checked_utc=readiness.get("generated_at"), linked_report="data/research/status/tim_v1_readiness.json", linked_blocker="v2_approval" if readiness.get("v2_approved") is not True else None, recommended_next_action="Manuellen Scientific Review protokollieren.", operational_impact="Release gate", scientific_impact="Eligibility gate", governance_impact="Approval process", freshness_seconds=_age_seconds(readiness.get("generated_at")), provenance=readiness.get("provenance"), source_hash=readiness.get("artifact_hash"), technical_cause="No automatic approval", affected_windows=readiness.get("generated_at"), affected_artifacts="data/research/status/tim_v1_readiness.json", status_history=[str(readiness.get("generated_at"))], historical_development="Release gating", open_blockers=blocker_names, known_limitations=["No automatic release"]),
    ]

    timelines = _timeline_rows(data.get("timeline", []))
    exceptions_rows, exceptions = _quality_exception_rows(data, archived=True)
    def section(title: str, text: str, cards: list[str], *, badge: str, timestamp: Any) -> str:
        return (
            "<section class='panel'>"
            "<div class='panel__head'><div>"
            f"<h2>{_safe(title)}</h2><p class='muted'>{_safe(text)}</p>"
            "</div><div class='health-section-meta'>"
            f"<span class='badge badge--{_safe(badge)}'>{_safe('LIVE' if badge == 'green' else 'HISTORISCHER SNAPSHOT')}</span>"
            f"<span class='mono'>Berichtszeit: {_safe(_required('timestamp', timestamp))}</span>"
            "</div></div>"
            f"<div class='health-grid'>{''.join(cards)}</div></section>"
        )

    return (
        "<div class='safety-callout health-scope-note'><b>Statusbereiche sind getrennt:</b> "
        "Grün markierte Live-Daten beschreiben den aktuellen Betrieb. Historische Audit- und Readiness-Snapshots "
        "sind eingefrorene wissenschaftliche Befunde und bedeuten nicht automatisch einen aktuellen Systemausfall.</div>"
        + section("1 · Live Operational Health", "Aktueller Betrieb von Persistenz, Stream, Dashboard und Runtime.", operational, badge="green", timestamp=data.get("timestamp"))
        + section("2 · Historical Scientific Baseline", "Archivierte Evidenz, kein Live-Health-Status. FAIL- und WAITING-Werte bleiben unverändert dokumentiert.", scientific, badge="snapshot", timestamp=quality.get("generated_at") or readiness.get("generated_at"))
        + section("3 · V2 Governance & Readiness", "Archivierte Governance-Evidenz, kein aktueller Systemfehler. Freigaben bleiben ausschließlich manuell.", governance, badge="snapshot", timestamp=readiness.get("generated_at"))
        + "<section class='panel'><div class='panel__head'><h2>Health Timeline</h2><span class='badge badge--snapshot'>DIAGNOSTIC TIMELINE</span></div><div class='table-wrap'><table><thead><tr><th>event_id</th><th>event_type</th><th>timestamp_utc</th><th>component_id</th><th>previous_status</th><th>new_status</th><th>reason_code</th><th>evidence_reference</th><th>provenance</th><th>source_hash</th></tr></thead><tbody>" + timelines + "</tbody></table></div></section>"
        + "<section class='panel'><div class='panel__head'><h2>Data Quality Evidence Register</h2><span class='badge badge--snapshot'>ARCHIVIERTE BEFUNDE</span></div><div class='table-wrap'><table><thead><tr><th>Component</th><th>Status</th><th>Reason Code</th><th>Reason Text</th><th>Time Window</th><th>Provenance</th><th>Linked Report</th><th>Linked Blocker</th></tr></thead><tbody>" + exceptions_rows + "</tbody></table></div><p class='count-scope'>Historische Ausnahmen bleiben unverändert sichtbar und werden nicht als aktueller Runtime-Fehler gewertet.</p></section>"
    )


CSS = r"""
:root{color-scheme:dark;--bg:#08111f;--panel:#101c2e;--panel2:#132238;--line:#263852;--text:#e9f0f8;--muted:#91a2b8;--green:#3ddc97;--yellow:#f6c85f;--red:#ff6b6b;--blue:#66a6ff;--radius:14px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}.shell{max-width:1480px;margin:auto;padding:76px 24px 40px}.topbar{position:fixed;inset:0 0 auto;z-index:10;background:#0b1626eF;border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}.topbar__inner{max-width:1480px;margin:auto;padding:12px 24px;display:flex;align-items:center;gap:20px}.brand{font-size:18px;font-weight:800;color:white}.brand small{display:block;font-size:10px;color:var(--muted);letter-spacing:.13em}.nav{display:flex;gap:6px;flex-wrap:wrap}.nav a{color:var(--muted);padding:8px 11px;border-radius:8px}.nav a.active,.nav a:hover{background:var(--panel2);color:white;text-decoration:none}.live{margin-left:auto;font:12px ui-monospace,monospace;color:var(--green);white-space:nowrap}.hero{display:flex;justify-content:space-between;gap:20px;align-items:end;margin:16px 0 22px}.hero h1{font-size:30px;margin:0 0 7px}.hero p{margin:0;color:var(--muted)}.observe{color:var(--green);font-weight:700}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.card,.panel{background:linear-gradient(145deg,var(--panel),#0d192a);border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 12px 30px #0002}.card{padding:17px;min-height:118px}.card__label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.card__value{font-size:25px;font-weight:760;margin:12px 0 5px}.card__note{color:var(--muted);font-size:12px}.panel{padding:20px;margin-top:16px}.panel h2{margin:0 0 16px;font-size:19px}.panel__head{display:flex;justify-content:space-between;gap:15px;align-items:center}.badge{display:inline-block;padding:4px 8px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.04em}.badge--green{background:#143d30;color:var(--green)}.badge--yellow{background:#493b19;color:var(--yellow)}.badge--red{background:#4a2026;color:var(--red)}.badge--snapshot{background:#1b304d;color:#b8d4f5;border:1px solid #35577f}.tag{display:inline-block;padding:4px 7px;background:#1b304d;border-radius:6px;color:#cfe2ff}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.table-wrap{overflow:auto;max-width:100%;border:1px solid var(--line);border-radius:10px}table{border-collapse:collapse;width:100%;min-width:850px}th,td{padding:11px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{position:sticky;top:0;background:#17263c;color:#aebbd0;font-size:11px;text-transform:uppercase;letter-spacing:.06em}tr:hover td{background:#142239}.filters{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:10px;margin-bottom:15px}.filters label,.field label{display:block;color:var(--muted);font-size:11px;margin-bottom:5px}input,select,textarea,button{font:inherit;color:var(--text);background:#0b1728;border:1px solid var(--line);border-radius:8px;padding:9px 10px}textarea{min-height:100px;resize:vertical}button{cursor:pointer;background:#244b79}button:hover{background:#2d609a}.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.detail{background:#0b1728;border:1px solid var(--line);border-radius:10px;padding:15px}.detail dt{color:var(--muted);font-size:11px}.detail dd{margin:4px 0 13px;overflow-wrap:anywhere}.code{white-space:pre-wrap;word-break:break-word;background:#07101c;border:1px solid var(--line);border-radius:9px;padding:14px;color:#cbd8e7;max-height:420px;overflow:auto}.health-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}.health{border-left:4px solid var(--line)}.health--green{border-color:var(--green)}.health--yellow{border-color:var(--yellow)}.health--red{border-color:var(--red)}.health--snapshot{border-color:#35577f;background:linear-gradient(145deg,#101c2e,#101b2b)}.health-card{padding:0;overflow:hidden}.health-card summary{list-style:none;cursor:pointer;padding:17px;display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.health-card summary::-webkit-details-marker{display:none}.health-card summary strong{display:block;font-size:18px;margin-top:9px}.health-card[open] summary{border-bottom:1px solid var(--line)}.diagnostic{padding:15px 17px;background:#0a1524}.diagnostic dl{margin:0}.diagnostic dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}.diagnostic dd{margin:4px 0 13px;overflow-wrap:anywhere}.diagnostic h4{margin:14px 0 7px}.diagnostic ul{margin:0;padding-left:18px;overflow-wrap:anywhere}.timeline{list-style:none;margin:0;padding:0}.timeline li{display:grid;grid-template-columns:180px 190px 1fr;gap:14px;padding:12px 0;border-bottom:1px solid var(--line)}.timeline time{color:var(--muted);font-family:ui-monospace,monospace}.research-tabs{display:flex;gap:8px;margin-bottom:12px}.research-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}.research-grid>*{min-width:0}.muted{color:var(--muted)}.empty{text-align:center;color:var(--muted);padding:30px}.count-scope{font-size:11px;color:var(--muted)}details.readiness{margin-top:14px}details.readiness summary{cursor:pointer;color:var(--blue);font-weight:700;padding:8px 0}.path{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0}.path__step{padding:13px;border:1px solid var(--line);border-radius:10px;background:#0b1728}.path__step b{display:block;margin-bottom:5px}.safety-callout{border-left:4px solid var(--green);padding:12px 14px;background:#10261f;color:#bff4db;border-radius:8px}
@media(max-width:1050px){.grid{grid-template-columns:repeat(2,1fr)}.health-grid{grid-template-columns:repeat(2,1fr)}.topbar__inner{align-items:flex-start}.live{display:none}}
@media(max-width:680px){.shell{padding:122px 14px 30px}.topbar__inner{display:block}.nav{margin-top:8px}.grid,.health-grid,.detail-grid,.research-grid,.filters,.path{grid-template-columns:1fr}.hero{display:block}.timeline li{grid-template-columns:1fr;gap:3px}.card{min-height:100px}table{min-width:720px}.readiness table{min-width:100%}.readiness th,.readiness td{overflow-wrap:anywhere}}
"""

EXTRA_CSS = r"""
.health-card{padding:0;overflow:hidden}
.health-card summary{list-style:none;cursor:pointer;padding:17px;display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.health-card summary::-webkit-details-marker{display:none}
.health-card summary strong{display:block;font-size:18px;margin-top:9px}
.health-card[open] summary{border-bottom:1px solid var(--line)}
.diagnostic{padding:15px 17px;background:#0a1524}
.diagnostic dl{margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 18px}
.diagnostic dt{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.diagnostic dd{margin:4px 0 0;overflow-wrap:anywhere}
.contract-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.queue-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.meta-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}
.signal-header{display:flex;justify-content:space-between;gap:20px;align-items:flex-start;flex-wrap:wrap}
.signal-kicker{display:flex;gap:8px;flex-wrap:wrap}
.signal-pill{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:#0b1728;color:var(--text);font-size:12px}
.status-note{font-size:11px;color:var(--muted);margin-top:4px}
.status-note b{color:var(--text)}
.health-section-meta{display:flex;flex-direction:column;align-items:flex-end;gap:7px;color:var(--muted);font-size:11px;text-align:right}
.health-scope-note{margin-top:16px}
@media(max-width:680px){.health-section-meta{align-items:flex-start;text-align:left}.panel__head{align-items:flex-start;flex-direction:column}}
"""


AUTO_REFRESH_SCRIPT = r"""
<script>
(() => {
  'use strict';
  const INTERVAL_MS = 5000;
  const MAX_RETRIES = 3;
  let timer = null, retries = 0, healthSignature = null;
  const byId = id => document.getElementById(id);
  const text = value => value === null || value === undefined || value === '' ? '—' : String(value);
  function set(id, value) { const node=byId(id); if(node) node.textContent=text(value); }
  function status(kind, message) { const el=byId('tim-status'); if(!el)return; el.className=`live badge--${kind}`;el.textContent=`● ${message}`; }
  function countdown(deadline) { const seconds=Math.max(0,Math.floor((new Date(deadline).getTime()-Date.now())/1000));return `${Math.floor(seconds/3600)}h ${String(Math.floor((seconds%3600)/60)).padStart(2,'0')}m ${String(seconds%60).padStart(2,'0')}s`; }
  function update(data) {
    set('runtime', data.validator?.started_at ? countdown(new Date(Date.now()+(Date.now()-new Date(data.validator.started_at).getTime())).toISOString()) : '—');
    set('acceptance-countdown', data.validator?.deadline ? countdown(data.validator.deadline) : '—');
    set('acceptance-state', `${text(data.validator?.acceptance?.status).toUpperCase()} • ${text(data.validator?.health_monitor?.level)}`);
    set('validator-cycles', data.validator?.cycles || 0);
    set('visible-candles', data.visible_counts?.candles || 0);
    set('visible-observations', data.visible_counts?.observations || 0);
    set('memory-observations', data.memory_status?.observations || data.visible_counts?.observations || 0);
    set('case-active', data.case_counts?.active || 0);set('case-closed',data.case_counts?.closed || 0);
    const health=String(data.operational_health?.status || 'UNKNOWN').toLowerCase();
    const badge=health==='green'?'green':health==='red'?'red':'yellow';
    const label=health==='green'?'Live':health==='red'?'Betriebsstörung':'Betriebsstatus unvollständig';
    status(badge, `${label} • sichtbarer Ausschnitt: ${data.visible_counts?.candles || 0} Candles • ${data.visible_counts?.observations || 0} Beobachtungen • ${new Date().toLocaleTimeString('de-DE')}`);
    if(location.pathname==='/health'){
      const signature=JSON.stringify([data.operational_health?.status,data.operational_health?.database,data.operational_health?.stream,data.operational_health?.dashboard,data.operational_health?.runtime,data.operational_health?.last_data_at,data.validator?.status,data.validator?.last_cycle_at,data.readiness?.readiness_status]);
      if(healthSignature!==null && healthSignature!==signature){ location.reload(); return; }
      healthSignature=signature;
    }
  }
  async function poll() {
    if(document.hidden)return;status('yellow','Aktualisiere…');
    const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),8000);
    try{const response=await fetch('/api/state',{signal:controller.signal,cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);update(await response.json());retries=0;}
    catch(error){retries+=1;status(retries>=MAX_RETRIES?'red':'yellow',retries>=MAX_RETRIES?`Verbindung verloren – automatischer Wiederherstellungsversuch ${retries-MAX_RETRIES+1}`:`Temporärer Fehler ${retries}/${MAX_RETRIES}`);}
    finally{clearTimeout(timeout);clearTimeout(timer);if(!document.hidden)timer=setTimeout(poll,retries?2000:INTERVAL_MS);}
  }
  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (document.hidden) status('paused', 'Pausiert – Tab im Hintergrund');
    else { retries = 0; poll(); }
  });
  const live=byId('tim-status');if(live)live.addEventListener('click',poll);
  const filter=()=>{const statusValue=byId('filter-status')?.value||'',typeValue=(byId('filter-type')?.value||'').toLowerCase(),ruleValue=(byId('filter-rule')?.value||'').toLowerCase(),period=byId('filter-period')?.value||'';document.querySelectorAll('tbody tr[data-status]').forEach(row=>{let ok=!statusValue||row.dataset.status===statusValue;ok=ok&&(!typeValue||(row.dataset.type||'').toLowerCase().includes(typeValue));ok=ok&&(!ruleValue||(row.dataset.rule||'').toLowerCase().includes(ruleValue));if(ok&&period&&row.dataset.time){const age=Date.now()-new Date(row.dataset.time).getTime();ok=age<=Number(period)*86400000;}row.hidden=!ok;});};
  document.querySelectorAll('.filters input,.filters select').forEach(node=>node.addEventListener('input',filter));
  function showResearch(target,data,deep=false){const box=byId(target);if(!box)return;box.replaceChildren();const pre=document.createElement('pre');pre.className='code';pre.textContent=data.error||(!data.result?'Kein Ergebnis':deep?`Report: ${data.result.report_id||'—'}\n${data.result.word_count||0} Wörter • ${data.result.sources||0} Quellen`:`${data.result.summary||''}\nPatterns: ${(data.result.patterns||[]).join(', ')||'keine'}`);box.appendChild(pre);if(deep&&data.result?.download_url){const link=document.createElement('a');link.href=data.result.download_url;link.textContent='Markdown-Bericht öffnen';link.target='_blank';link.rel='noopener';box.appendChild(link);}}
  async function research(endpoint,query,target,extra={}){const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,...extra})});showResearch(target,await response.json(),endpoint.endsWith('/deep'));}
  byId('quick-run')?.addEventListener('click',()=>research('/api/research/quick',byId('quick-query').value,'quick-results'));
  byId('deep-run')?.addEventListener('click',()=>research('/api/research/deep',byId('deep-query').value,'deep-results',{type:byId('report-type').value}));
  poll();
})();
</script>
"""


def _layout(title: str, page: str, body: str) -> str:
    links = [("Overview", "/"), ("Observations", "/observations"), ("Research Cases", "/cases"), ("Orderflow", "/orderflow"), ("Signal Research", "/signals"), ("Analytics", "/analytics"), ("Insights", "/insights"), ("Health Center", "/health"), ("Data Quality Exceptions", "/exceptions"), ("Timeline", "/timeline"), ("Research", "/research")]
    nav = "".join(f"<a href='{href}' class='{'active' if page == key else ''}'>{key}</a>" for key, href in links)
    return f"""<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{_safe(title)} · TIM</title><style>{CSS}{EXTRA_CSS}</style></head><body><header class='topbar'><div class='topbar__inner'><a class='brand' href='/'>TIM<small>TRANSPARENT INTELLIGENCE FOR MARKETS</small></a><nav class='nav'>{nav}</nav><div id='tim-status' class='live badge--yellow'>● Startet…</div></div></header><main class='shell'>{body}</main>{AUTO_REFRESH_SCRIPT}</body></html>"""


def _hero(title: str, text: str) -> str:
    return f"<div class='hero'><div><h1>{_safe(title)}</h1><p>{_safe(text)}</p></div><div class='observe'>OBSERVE • READ-ONLY</div></div>"


def render(state: DashboardState, page: str = "Overview", selected_id: str | None = None) -> str:
    data = state.snapshot()
    validator = data["validator"]
    if page == "Orderflow":
        with state.lock:
            total_orderflow=len(state.orderflow_observations)
            observations=[dict(item) for item in state.orderflow_observations[-ORDERFLOW_VISIBLE_LIMIT:]]
            validations={str(item.get("observation_id")):dict(item) for item in state.orderflow_validations}
        selected=next((item for item in observations if str(item.get("observation_id"))==str(selected_id)),None)
        rows="".join(f"<tr data-type='{_safe(item.get('kind'))}' data-rule='{_safe(item.get('rule_version'))}' data-time='{_safe(item.get('observed_at'))}'><td>{_safe(item.get('observed_at'))}</td><td><a class='mono' href='/orderflow?id={_safe(item.get('observation_id'))}'>{_safe(_short(item.get('observation_id'),18))}</a></td><td><span class='tag'>{_safe(item.get('kind'))}</span></td><td>{_safe(item.get('timeframe'))}</td><td>{len(item.get('evidence',[]))}</td><td>{len(validations.get(str(item.get('observation_id')),{}).get('horizons',[]))}/3</td><td>{_safe(validations.get(str(item.get('observation_id')),{}).get('outcome') or 'PENDING')}</td><td class='mono'>{_safe(item.get('rule_version'))}</td></tr>" for item in reversed(observations)) or "<tr><td colspan='8' class='empty'>Noch keine Orderflow-Observations.</td></tr>"
        detail=""
        if selected:
            validation=validations.get(str(selected.get("observation_id")),{})
            detail=f"<section class='panel'><div class='panel__head'><h2>Observation &amp; Outcome Detail</h2><span class='badge badge--green'>READ-ONLY</span></div><div class='detail-grid'><dl class='detail'><dt>ID</dt><dd class='mono'>{_safe(selected.get('observation_id'))}</dd><dt>Beschreibung</dt><dd>{_safe(selected.get('summary'))}</dd><dt>Rule Version</dt><dd>{_safe(selected.get('rule_version'))}</dd><dt>Input Hash</dt><dd class='mono'>{_safe(selected.get('input_hash'))}</dd><dt>Outcome</dt><dd>{_safe(validation.get('outcome') or 'PENDING')}</dd><dt>Validated Through</dt><dd>{_safe(validation.get('validated_through'))}</dd></dl><div><h3>Evidenzbedingungen</h3><pre class='code'>{_json_block(selected.get('evidence'))}</pre><h3>5/15/30-Minuten-Verlauf</h3><pre class='code'>{_json_block(validation.get('horizons',[]))}</pre></div></div></section>"
        body=_hero("Orderflow Research","Deterministische Beschreibungen und nachgelagerte 5/15/30-Minuten-Outcomes.")+f"<section class='panel'><div class='panel__head'><h2>Persistierte Orderflow-Observations</h2><span class='count-scope'>neueste {len(observations)} von {total_orderflow}</span></div><div class='filters'><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. STRONG_BUYER_ACTIVITY'></div><div><label>Rule Version</label><input id='filter-rule' placeholder='1.0.0'></div><div><label>Zeitraum</label><select id='filter-period'><option value=''>Gesamt</option><option value='1'>24 Stunden</option><option value='7'>7 Tage</option></select></div></div><div class='table-wrap'><table><thead><tr><th>Timestamp</th><th>Observation ID</th><th>Type</th><th>Timeframe</th><th>Evidence</th><th>Horizonte</th><th>Outcome</th><th>Rule Version</th></tr></thead><tbody>{rows}</tbody></table></div><p class='count-scope'>Der sichtbare Ausschnitt ist bewusst auf {ORDERFLOW_VISIBLE_LIMIT} Einträge begrenzt. Outcomes dokumentieren beobachtete Preisentwicklung; keine Prognose.</p></section>{detail}"
        return _layout("Orderflow Research",page,body)
    if page == "Signal Research":
        return _signal_research_page(state, data, selected_id)
    if page == "Analytics":
        analytics = state.analytics()
        rules = "".join(f"<tr><td>{_safe(x['rule_id'])}</td><td class='mono'>{_safe(x['version'])}</td><td>{x['count']}</td><td>{_safe(x['first_occurrence'])}</td><td>{_safe(x['last_occurrence'])}</td><td>{x['average_duration_seconds']}</td><td>{x['average_timeframes_per_case']}</td><td>{_safe(', '.join(x['most_common_missing_evidence']))}</td><td>{_safe(', '.join(x['most_common_outcomes']))}</td><td>{x['confirmed_rate_percent']}%</td><td>{x['invalidation_rate_percent']}%</td><td>{x['closed_rate_percent']}%</td><td>{x['average_lifetime_seconds']}</td></tr>" for x in analytics["rules"]) or "<tr><td colspan='13' class='empty'>Keine persistierten Rule-Daten.</td></tr>"
        clusters = "".join(f"<tr><td>{_safe(x['observation_type'])}</td><td>{_safe(x['rule_version'])}</td><td>{_safe(x['outcome'])}</td><td>{_safe(', '.join(x['missing_evidence']))}</td><td>{_safe(x['stored_evidence_score'])}</td><td>{_safe(x['timeframe'])}</td><td>{x['count']}</td></tr>" for x in analytics["case_clusters"]) or "<tr><td colspan='7' class='empty'>Keine Cluster verfügbar.</td></tr>"
        days = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["research_cases_per_day"].items()) or "<tr><td colspan='2' class='empty'>Keine Timeline-Daten.</td></tr>"
        hours = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["research_cases_per_hour"].items()) or "<tr><td colspan='2' class='empty'>Keine Timeline-Daten.</td></tr>"
        obs_frequency = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["observation_frequency"].items()) or "<tr><td colspan='2' class='empty'>Keine Observations.</td></tr>"
        outcome_frequency = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["outcome_frequency"].items()) or "<tr><td colspan='2' class='empty'>Keine persistierten Outcomes.</td></tr>"
        quality = "".join(f"<article class='card'><div class='card__label'>{_safe(key.replace('_',' '))}</div><div class='card__value'>{value}</div><div class='card__note'>Persistierte Ereignisse</div></article>" for key, value in analytics["data_quality"].items())
        body = _hero("Research Analytics", "Deterministische Statistik über bereits persistierte Research-Daten.")
        body += f"<p class='observe'>OBSERVE • READ-ONLY • Dataset <span class='mono'>{_safe(_short(analytics['dataset_hash'],16))}</span></p><section class='panel'><div class='panel__head'><h2>Exporte</h2><div><a class='tag' href='/exports/analytics.csv'>CSV</a> <a class='tag' href='/exports/analytics.json'>JSON</a> <a class='tag' href='/exports/analytics.md'>Markdown</a></div></div><p class='count-scope'>{analytics['source_counts']['observations']} persistierte Observations · {analytics['source_counts']['research_cases']} Research Cases · {analytics['source_counts']['events']} Systemereignisse. Keine Prognosen, Rankings oder neu berechneten Scores.</p></section>"
        body += f"<section class='panel'><h2>Rule Analytics</h2><div class='table-wrap'><table><thead><tr><th>Rule</th><th>Version</th><th>Anzahl</th><th>Erstes Auftreten</th><th>Letztes Auftreten</th><th>Ø Dauer s</th><th>Ø Timeframes/Case</th><th>Häufigste Missing Evidence</th><th>Häufigste Outcomes</th><th>Confirmed</th><th>Invalidiert</th><th>Closed</th><th>Ø Lifetime s</th></tr></thead><tbody>{rules}</tbody></table></div></section>"
        body += f"<section class='panel'><h2>Case Cluster</h2><div class='table-wrap'><table><thead><tr><th>Observation Type</th><th>Rule Version</th><th>Outcome</th><th>Missing Evidence</th><th>Gespeicherter Evidence Score</th><th>Timeframe</th><th>Anzahl</th></tr></thead><tbody>{clusters}</tbody></table></div><p class='count-scope'>Evidence Score ist ausschließlich der persistierte Wert; Analytics berechnet keinen neuen Score.</p></section>"
        body += f"<div class='research-grid'><section class='panel'><h2>Cases pro Tag</h2><div class='table-wrap'><table><thead><tr><th>Tag (UTC)</th><th>Anzahl</th></tr></thead><tbody>{days}</tbody></table></div></section><section class='panel'><h2>Cases pro Stunde</h2><div class='table-wrap'><table><thead><tr><th>Stunde (UTC)</th><th>Anzahl</th></tr></thead><tbody>{hours}</tbody></table></div></section><section class='panel'><h2>Observation-Häufigkeit</h2><div class='table-wrap'><table><thead><tr><th>Observation Type</th><th>Anzahl</th></tr></thead><tbody>{obs_frequency}</tbody></table></div></section><section class='panel'><h2>Outcome-Häufigkeit</h2><div class='table-wrap'><table><thead><tr><th>Outcome</th><th>Anzahl</th></tr></thead><tbody>{outcome_frequency}</tbody></table></div></section></div><section class='panel'><h2>Data Quality Analytics</h2><div class='grid'>{quality}</div></section>"
        return _layout("Research Analytics", page, body)
    if page == "Insights":
        insights = state.insights()
        badge = "green" if insights["eligibility_status"] == "ELIGIBLE" else "yellow"
        outcome_rows = "".join(
            f"<tr><td>{_safe(item['observation_type'])}</td><td class='mono'>{_safe(item['versions']['rule'])}</td><td>{item['fully_validated_cases']}</td><td>{item['outcomes']['PRICE_INCREASED']}</td><td>{item['outcomes']['PRICE_DECREASED']}</td><td>{item['outcomes']['PRICE_SIDEWAYS']}</td><td><span class='badge badge--yellow'>{_safe(item['sample_label'])}</span></td></tr>"
            for item in insights["outcome_distribution"]
        ) or "<tr><td colspan='7' class='empty'>Keine auswertbaren Orderflow-Observations.</td></tr>"
        followup_rows = []
        for item in insights["followup_statistics"]:
            for horizon in item["horizons"]:
                price, delta = horizon["price_change_percent"], horizon["net_delta"]
                followup_rows.append(f"<tr><td>{_safe(item['observation_type'])}</td><td>{horizon['minutes']}m</td><td>{_safe(price.get('n') if price else None)}</td><td>{_safe(price.get('median') if price else None)}</td><td>{_safe(price.get('mean') if price else None)}</td><td>{_safe(price.get('percentile_25') if price else None)} / {_safe(price.get('percentile_75') if price else None)}</td><td>{_safe(delta.get('median') if delta else None)}</td><td>{_safe(delta.get('mean') if delta else None)}</td></tr>")
        combination_rows = "".join(
            f"<tr><td>{_safe(item['observation_type'])}</td><td>{item['count']}</td><td class='mono'>{_safe(item['rule_version'])}</td><td>{_safe(' + '.join(item['evidence']))}</td><td>{item['outcomes']['PRICE_INCREASED']} / {item['outcomes']['PRICE_DECREASED']} / {item['outcomes']['PRICE_SIDEWAYS']}</td><td>{_safe(item['sample_label'])}</td></tr>"
            for item in insights["evidence_combinations"][:30]
        ) or "<tr><td colspan='6' class='empty'>Keine Evidenzkombinationen.</td></tr>"
        session_rows = "".join(f"<tr><td>{_safe(name)}</td><td>{count}</td></tr>" for name, count in insights["temporal_distribution"]["market_session"].items()) or "<tr><td colspan='2' class='empty'>Keine zeitlichen Daten.</td></tr>"
        warnings = "".join(f"<li>{_safe(item)}</li>" for item in insights["warnings"]) or "<li>Keine Warnungen.</li>"
        versions = insights["versions"]
        body = _hero("Research Insights", "Retrospektive, versionsgetrennte Statistik über vollständig persistierte Forschungsergebnisse.")
        body += f"<p class='observe'>EXTERNAL TO CORE • READ-ONLY • NO FORECASTS • Dataset <span class='mono'>{_safe(_short(insights['input_hash'],16))}</span></p><div class='grid'><article class='card'><div class='card__label'>Eligibility</div><div class='card__value'><span class='badge badge--{badge}'>{_safe(insights['eligibility_status'])}</span></div><div class='card__note'>{_safe(insights['result_status'])}</div></article><article class='card'><div class='card__label'>Fully Validated</div><div class='card__value'>{insights['eligibility']['fully_validated_cases']}</div><div class='card__note'>Minimum für Eligibility: 1.000</div></article><article class='card'><div class='card__label'>Versionen</div><div class='card__value mono'>{_safe(versions['core'])}</div><div class='card__note'>Metrics {_safe(', '.join(versions['metrics']))} · Rules {_safe(', '.join(versions['rules']))} · Validation {_safe(', '.join(versions['validations']))}</div></article><article class='card'><div class='card__label'>Integrity</div><div class='card__value'>{_safe(insights['data_quality']['integrity_status'])}</div><div class='card__note'>Replay {_safe(insights['data_quality']['replay_status'])} · Coverage {_safe(insights['data_quality']['coverage_percent'])}</div></article></div>"
        body += f"<section class='panel'><div class='panel__head'><h2>Exporte</h2><div><a class='tag' href='/exports/insights.json'>JSON</a> <a class='tag' href='/exports/insights.csv'>CSV</a> <a class='tag' href='/exports/insights.md'>Markdown</a></div></div><ul>{warnings}</ul></section>"
        body += f"<section class='panel'><h2>Outcome-Verteilungen</h2><div class='table-wrap'><table><thead><tr><th>Observation</th><th>Rule</th><th>N vollständig</th><th>Price Increased</th><th>Price Decreased</th><th>Price Sideways</th><th>Sample</th></tr></thead><tbody>{outcome_rows}</tbody></table></div></section>"
        body += f"<section class='panel'><h2>Folgeverläufe</h2><p class='count-scope'>Mittelwert wird stets zusammen mit Median und N dargestellt. Keine kausale Interpretation.</p><div class='table-wrap'><table><thead><tr><th>Observation</th><th>Horizont</th><th>N</th><th>Median Preis %</th><th>Mittel Preis %</th><th>Q25 / Q75</th><th>Median Delta</th><th>Mittel Delta</th></tr></thead><tbody>{''.join(followup_rows)}</tbody></table></div></section>"
        body += f"<section class='panel'><h2>Evidenzkombinationen</h2><div class='table-wrap'><table><thead><tr><th>Observation</th><th>Anzahl</th><th>Rule</th><th>Evidenz</th><th>Outcomes I / D / S</th><th>Sample</th></tr></thead><tbody>{combination_rows}</tbody></table></div></section><section class='panel'><h2>Market Sessions (UTC)</h2><p class='count-scope'>ASIA 00–08 · EUROPE 08–16 · USA 16–24 UTC. Feste deskriptive Einteilung.</p><div class='table-wrap'><table><thead><tr><th>Session</th><th>Observations</th></tr></thead><tbody>{session_rows}</tbody></table></div></section>"
        return _layout("Research Insights", page, body)
    if page == "Observations":
        selected = next((item for item in data["observations"] if str(item.get("observation_id")) == str(selected_id)), None)
        rows = "".join(_observation_row(item, data["research_cases"]) for item in reversed(data["observations"])) or "<tr><td colspan='7' class='empty'>No observations yet</td></tr>"
        detail = ""
        if selected:
            case = _case_for_observation(selected, data["research_cases"])
            detail = f"<section class='panel'><div class='panel__head'><h2>Observation Detail</h2><span class='badge badge--green'>READ-ONLY</span></div><div class='detail-grid'><dl class='detail'><dt>Observation ID</dt><dd class='mono'>{_safe(selected.get('observation_id'))}</dd><dt>Timestamp</dt><dd>{_safe(selected.get('observed_at'))}</dd><dt>Type</dt><dd>{_safe(selected.get('kind'))}</dd><dt>Rule</dt><dd>{_safe(selected.get('rule_id'))} · {_safe(selected.get('rule_version'))}</dd><dt>Provenance</dt><dd>{_safe(selected.get('provenance'))}</dd><dt>Research Case</dt><dd>{_safe(case.get('case_id') if case else None)}</dd><dt>Hash</dt><dd class='mono'>{_safe(selected.get('input_hash'))}</dd></dl><div><h3>Evidence / Rohdaten</h3><pre class='code'>{_json_block(selected.get('evidence'))}</pre></div></div><h3>Vollständige Observation</h3><pre class='code'>{_json_block(selected)}</pre></section>"
        body = _hero("Observation Explorer", "Deterministische Beobachtungen mit Evidenz und Provenance.") + f"<section class='panel'><div class='panel__head'><h2>Active Observations</h2><span class='count-scope'>sichtbarer Ausschnitt: {len(data['observations'])}</span></div><div class='filters'><div><label>Status</label><select id='filter-status'><option value=''>Alle</option><option>OPEN</option><option>MONITORING</option><option>CONFIRMED</option><option>INVALIDATED</option><option>CLOSED</option><option>UNASSIGNED</option></select></div><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. REJECTION'></div><div><label>Rule Version</label><input id='filter-rule' placeholder='z. B. 1.0.0'></div></div><div class='table-wrap'><table><thead><tr><th>Timestamp</th><th>Observation ID</th><th>Observation Type</th><th>Rule Version</th><th>Evidence Score</th><th>Provenance</th><th>Status</th></tr></thead><tbody id='observations-body'>{rows}</tbody></table></div><p class='count-scope'>Evidence Score entspricht der gespeicherten deterministischen Confidence; keine neue Bewertung wird erzeugt.</p></section>{detail}"
        return _layout("Observation Explorer", page, body)
    if page == "Research Cases":
        selected = next((item for item in data["research_cases"] if str(item.get("case_id")) == str(selected_id)), None)
        rows = "".join(_case_row(item) for item in reversed(data["research_cases"])) or "<tr><td colspan='8' class='empty'>keine materialisierten Research Cases vorhanden</td></tr>"
        counts = data.get("case_counts", {})
        confirmed = int(counts.get("confirmed", 0) or 0)
        collecting = int(counts.get("collecting_evidence", 0) or 0)
        total = int(counts.get("total", 0) or 0)
        if confirmed == 0 and collecting > 0:
            progress = f"0 confirmed, aber {collecting} collecting evidence"
        elif total == 0:
            progress = "0 confirmed, 0 collecting evidence — derzeit keine materialisierten Research Cases"
        else:
            progress = f"{confirmed} confirmed · {collecting} collecting evidence · {total} total"
        summary = (
            "<div class='grid case-status-summary'>"
            f"<article class='card'><div class='card__label'>Confirmed</div><div class='card__value'>{confirmed}</div><div class='card__note'>wissenschaftlich bestätigte Cases</div></article>"
            f"<article class='card'><div class='card__label'>Collecting Evidence</div><div class='card__value'>{collecting}</div><div class='card__note'>OPEN / MONITORING / COLLECTING_EVIDENCE</div></article>"
            f"<article class='card'><div class='card__label'>Total Cases</div><div class='card__value'>{total}</div><div class='card__note'>persistierte Research Cases</div></article>"
            "</div>"
            f"<p class='observe case-progress'>{_safe(progress)}</p>"
        )
        detail = ""
        if selected:
            timeline = "".join(f"<li><time>{_safe(item.get('observed_at'))}</time><span class='tag'>{_safe(item.get('kind'))}</span><span class='mono'>{_safe(_short(item.get('observation_id'), 14))}</span></li>" for item in selected.get("evidence", [])) or "<li class='empty'>Keine Evidenz-Timeline.</li>"
            reviews = "".join(f"<li><time>{_safe(item.get('at'))}</time><span class='tag'>{_safe(item.get('to'))}</span><span>{_safe(item.get('reason'))}</span></li>" for item in selected.get("review_history", []) or []) or "<li class='empty'>Noch kein Review.</li>"
            case_hash = hashlib.sha256(json.dumps({"case_id": selected.get("case_id"), "observation_ids": selected.get("observation_ids", []), "rule_versions": selected.get("rule_versions", {})}, sort_keys=True).encode()).hexdigest()[:16]
            rules = ", ".join(f"{key}:{value}" for key, value in sorted((selected.get("rule_versions", {}) or {}).items())) or "—"
            detail = f"<section class='panel'><div class='panel__head'><h2>Case Detail</h2><span class='badge badge--green'>READ-ONLY</span></div><div class='detail-grid'><dl class='detail'><dt>Case ID</dt><dd class='mono'>{_safe(selected.get('case_id'))}</dd><dt>Status</dt><dd>{_safe(selected.get('status'))}</dd><dt>Dauer</dt><dd>{_safe(_duration(selected.get('opened_at'),selected.get('updated_at')))}</dd><dt>Outcome</dt><dd>{_safe(selected.get('outcome'))}</dd><dt>Missing Evidence</dt><dd>{_safe(', '.join(selected.get('missing_evidence', [])))}</dd><dt>Rule Versions</dt><dd class='mono'>{_safe(rules)}</dd><dt>Case Hash</dt><dd class='mono'>casehash:{_safe(case_hash)}</dd></dl><div><h3>Timeline</h3><ul class='timeline'>{timeline}</ul><h3>Review History</h3><ul class='timeline'>{reviews}</ul></div></div></section>"
        stand = f"<p class='count-scope'>Datenstand: {_safe(data.get('timestamp'))} · Builder: ResearchCaseEngine/30min-Fenster · Quelle: OBSERVE-only Laufzeit</p>"
        body = _hero("Research Case Explorer", "Case-Lifecycle, fehlende Evidenz und reproduzierbare Timeline.") + f"<section class='panel'><div class='panel__head'><h2>Research Cases &amp; Missing Evidence</h2><span class='count-scope'>sichtbarer Ausschnitt: {len(data['research_cases'])}</span></div>" + summary + f"<div class='filters'><div><label>Status</label><select id='filter-status'><option value='' selected>Alle aktiven / alle Status</option><option>OPEN</option><option>MONITORING</option><option>COLLECTING_EVIDENCE</option><option>READY_FOR_REVIEW</option><option>CONFIRMED</option><option>REJECTED</option><option>QUARANTINED</option><option>INVALIDATED</option><option>CLOSED</option></select></div><div><label>Zeitraum</label><select id='filter-period'><option value=''>Gesamt</option><option value='1'>24 Stunden</option><option value='7'>7 Tage</option><option value='30'>30 Tage</option></select></div><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. BOS'></div><div><label>Rule Version</label><input id='filter-rule' placeholder='z. B. 1.0.0'></div></div><div class='table-wrap'><table><thead><tr><th>Case</th><th>Status</th><th>Dauer</th><th>Observations</th><th>Outcome</th><th>Missing Evidence</th><th>Types</th><th>Rule Version</th></tr></thead><tbody id='cases-body'>{rows}</tbody></table></div>{stand}</section>{detail}"
        return _layout("Research Case Explorer", page, body)
    if page == "Health Center":
        body = _hero("Health Center", "Zentrales Diagnosezentrum für Betrieb, Wissenschaft und Governance.")
        body += "<p class='count-scope'>Karten öffnen, um Ursache, Zeitpunkt, Evidenz, Auswirkung und nächsten Schritt zu sehen. Statuswerte werden nicht synthetisch ergänzt.</p>"
        body += _health_center_sections(data)
        return _layout("Health Center", page, body)
    if page == "Data Quality Exceptions":
        return _data_quality_exceptions_page(data)
    if page == "Timeline":
        return _health_timeline_page(data)
    if page == "Research":
        research = validator.get("research_health", {})
        body = _hero("Research Workspace", "Lokale, dokumentierte TIM-Evidenz. Keine automatische Websuche.") + f"<div class='grid'><article class='card'><div class='card__label'>Research Integrity</div><div class='card__value'><span class='badge badge--{_status(research.get('level')).lower()}'>{_safe(research.get('level'))}</span></div><div class='card__note'>{research.get('trigger_duplicates', 0)} Trigger-Duplikate</div></article><article class='card'><div class='card__label'>Mode</div><div class='card__value'>OBSERVE</div><div class='card__note'>Keine Multi-Agent-Ausführung</div></article></div><section class='panel'><div class='research-grid'><div><h2>Module A · Schnell</h2><label for='quick-query'>Pattern oder Frage</label><input id='quick-query' maxlength='500' placeholder='Dokumentierte Rejection-Muster prüfen'><button id='quick-run'>Schnell-Recherche</button><div id='quick-results'></div></div><div><h2>Module B · Bericht</h2><label for='deep-query'>Fragestellung</label><textarea id='deep-query' maxlength='2000' placeholder='Lokalen Evidenzbericht erstellen'></textarea><label for='report-type'>Report-Typ</label><select id='report-type'><option value='research_report'>Standard Report</option><option value='deep'>Deep Research (lokal)</option></select><button id='deep-run'>Bericht erstellen</button><div id='deep-results'></div></div></div></section>"
        return _layout("Research Workspace", page, body)
    readiness = data["readiness"]
    audit = data.get("research_audit", {})
    quality = data.get("research_quality", {})
    health_level = str(validator.get("health_monitor", {}).get("level", "YELLOW")).upper()
    started = _parse_time(validator.get("started_at"))
    runtime = _duration(started.isoformat() if started else None, datetime.now(timezone.utc).isoformat())
    checks = validator.get("health_monitor", {}).get("checks", {})
    candle_gap_free = bool(checks.get("candle_sequence_gap_free", True))
    provenance_deterministic = bool(checks.get("provenance_deterministic", True))
    data_quality_level = "RED" if not candle_gap_free else str(
        readiness.get("scientific_health_status")
        or quality.get("status")
        or audit.get("status")
        or "UNKNOWN"
    ).upper()
    data_quality_note = (
        f"Persistierte Sequenz, Zeitstempel und Provenance. "
        f"Coverage {_safe(readiness.get('continuous_coverage_percent'))}% · "
        f"Gap {_safe(readiness.get('unresolved_new_gap_count'))} · "
        f"Audit {_safe(audit.get('status'))} · Quality {_safe(quality.get('status'))}"
    )
    validator_level = str(validator.get("status") or validator.get("health_monitor", {}).get("level") or "UNKNOWN").upper()
    validator_note = (
        f"{_safe(validator.get('cycles', 0))} persistierte Zyklen · "
        f"letzte Prüfung {_safe(validator.get('research_last_check'))}"
    )
    cards = [
        ("Acceptance Countdown", f"<span id='acceptance-state' class='badge badge--{health_level.lower()}'>{_safe(validator.get('acceptance',{}).get('status','monitoring')).upper()} • {health_level}</span>", f"<span id='acceptance-countdown'>Deadline wird geladen</span>"),
        ("Data Quality", f"<span class='badge badge--{data_quality_level.lower()}'>{data_quality_level}</span>", _safe(data_quality_note)),
        ("Stream Status", _safe(data.get("system_health", {}).get("stream")), "Öffentliche Marktdaten"),
        ("Validator Status", f"<span class='badge badge--{validator_level.lower()}'>{_safe(validator.get('status'))}</span>", f"<span id='validator-cycles'>{validator.get('cycles',0)}</span> persistierte Zyklen."),
        ("Runtime", f"<span id='runtime'>{_safe(runtime)}</span>", f"Restart Count: {validator.get('restart_count',0)}"),
        ("Active Research Cases", f"<span id='case-active'>{data['case_counts']['active']}</span>", "Persistierter Case-Status"),
        ("Closed Research Cases", f"<span id='case-closed'>{data['case_counts']['closed']}</span>", "Persistierter Case-Status"),
        ("Candles (sichtbar)", f"<span id='visible-candles'>{len(data['candles'])}</span>", "Letzter persistierter Ausschnitt"),
        ("Observations", f"<span id='memory-observations'>{data['memory_status'].get('observations',len(data['observations']))}</span>", "Persistierter Memory-Zähler"),
        ("Dashboard Version", DASHBOARD_VERSION, "Read-only Research UI"),
    ]
    card_html = "".join(f"<article class='card'><div class='card__label'>{label}</div><div class='card__value'>{value}</div><div class='card__note'>{note}</div></article>" for label, value, note in cards)
    recent_obs = "".join(_observation_row(item, data["research_cases"]) for item in reversed(data["observations"][-8:])) or "<tr><td colspan='7' class='empty'>No observations yet</td></tr>"
    case_preview = "".join(_case_row(item) for item in reversed(data["research_cases"][-5:])) or "<tr><td colspan='8' class='empty'>No research cases yet</td></tr>"
    readiness=data["readiness"];criteria_rows="".join(f"<tr><td>{_safe(name)}</td><td><span class='badge badge--{_status(status).lower()}'>{_safe(status)}</span></td></tr>" for name,status in sorted(readiness.get("criteria",{}).items())) or "<tr><td colspan='2' class='empty'>Statusdatei noch nicht verfügbar.</td></tr>"
    readiness_panel=f"<section class='panel'><div class='panel__head'><h2>Scientific Data Progress &amp; V2 Readiness</h2><span class='badge badge--{_status(readiness.get('readiness_status')).lower()}'>{_safe(readiness.get('readiness_status'))}</span></div><div class='grid'><article class='card'><div class='card__label'>Validierte Cases</div><div class='card__value'>{_safe(readiness.get('validated_case_count'))} / {_safe(readiness.get('required_case_count'))}</div><div class='card__note'>{_safe(readiness.get('validated_case_progress_percent'))}% · {_safe(readiness.get('remaining_case_count'))} verbleibend</div></article><article class='card'><div class='card__label'>Offene Cases</div><div class='card__value'>{_safe(readiness.get('open_case_count'))}</div><div class='card__note'>{_safe(readiness.get('observation_count'))} Observationen gesamt</div></article><article class='card'><div class='card__label'>Neue Continuous Coverage</div><div class='card__value'>{_safe(readiness.get('continuous_coverage_percent'))}%</div><div class='card__note'>{_safe(readiness.get('continuous_persisted_1m_intervals'))} / {_safe(readiness.get('continuous_expected_1m_intervals'))} Minuten</div></article><article class='card'><div class='card__label'>Gemessener Verlauf</div><div class='card__value'>{_safe(readiness.get('measured_validated_cases_per_hour'))}/h</div><div class='card__note'>{_safe(readiness.get('measured_validated_cases_per_day'))}/Tag · Hochrechnung unverbindlich: {_safe(readiness.get('nonbinding_projected_1000_case_time'))}</div></article></div><details class='readiness'><summary>Alle Freigabekriterien anzeigen</summary><div class='table-wrap'><table><thead><tr><th>Freigabekriterium</th><th>Status</th></tr></thead><tbody>{criteria_rows}</tbody></table></div></details><p class='count-scope'>TIM startet V2 niemals automatisch. Die endgültige Freigabe erfordert einen manuellen Evolution Review.</p></section>"
    body = _hero("TIM Research Dashboard", "Research Overview · deterministischer Systemzustand und aktuelle Research-Aktivität.") + f"<p class='observe'>OBSERVE MODE • {data['safety']}</p>{readiness_panel}<section class='panel'><div class='panel__head'><h2>Market Status</h2><span class='badge badge--green'>{_safe(data['market_status'].get('status'))}</span></div><p class='count-scope'><b>Zählerbereich:</b> sichtbarer letzter Ausschnitt, keine Gesamtzahlen. Sichtbare Candles: <span id='candles-count'>{len(data['candles'])}</span> · Sichtbare Observations: <span id='obs-count'>{len(data['observations'])}</span> · Sichtbare Cases: <span id='cases-count'>{len(data['research_cases'])}</span></p></section><div class='grid'>{card_html}<article class='card'><div class='card__label'>Research Module</div><div class='card__value'><span id='research-health' class='badge badge--{_status(validator.get('research_health',{}).get('level')).lower()}'>{_safe(validator.get('research_health',{}).get('level'))}</span></div><div class='card__note'><a href='/research'>Research Workspace öffnen →</a></div></article></div><section class='panel'><div class='panel__head'><h2>Active Observations</h2><a href='/observations'>Alle öffnen →</a></div><div class='table-wrap'><table><thead><tr><th>Timestamp</th><th>Observation ID</th><th>Observation Type</th><th>Rule Version</th><th>Evidence Score</th><th>Provenance</th><th>Status</th></tr></thead><tbody id='observations-body'>{recent_obs}</tbody></table></div></section><section class='panel'><div class='panel__head'><h2>Research Cases &amp; Missing Evidence</h2><a href='/cases'>Alle öffnen →</a></div><div class='table-wrap'><table><thead><tr><th>Case</th><th>Status</th><th>Dauer</th><th>Observations</th><th>Outcome</th><th>Missing Evidence</th><th>Types</th><th>Rule Version</th></tr></thead><tbody id='cases-body'>{case_preview}</tbody></table></div></section><section class='panel'><h2>News</h2><p class='muted'>Keine autorisierte News-Ingestion aktiv. Es werden keine Nachrichten erfunden oder ergänzt.</p></section>"
    return _layout("Research Overview", page, body)


class DashboardServer:
    def __init__(self, state: DashboardState, host: str = "127.0.0.1", port: int = 8765, research_router: ResearchRouter | None = None) -> None:
        self.state, self.host, self.port = state, host, port
        self.research_router = research_router or ResearchRouter()
        self.research_lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def respond(self, status: int, payload: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self):
                parsed = urlparse(self.path)
                path, query = parsed.path, parse_qs(parsed.query)
                if path == "/api/state":
                    return self.respond(200, json.dumps(outer.state.snapshot()).encode(), "application/json")
                if path == "/api/health":
                    snapshot = outer.state.snapshot()
                    payload = {
                        "timestamp": snapshot["timestamp"],
                        "mode": snapshot["mode"],
                        "operational": snapshot["operational_health"],
                        "historical_scientific": {
                            "validator_status": snapshot["validator"].get("status", "UNKNOWN"),
                            "last_checked_at": snapshot["validator"].get("last_cycle_at"),
                            "quality_status": snapshot["research_quality"].get("validation_status", "UNKNOWN"),
                            "audit_status": snapshot["research_audit"].get("status", "UNKNOWN"),
                        },
                        "governance": {
                            "readiness_status": snapshot["readiness"].get("readiness_status", "UNKNOWN"),
                            "core_status": snapshot["core_manifest"].get("status", "UNKNOWN"),
                            "observe_only": snapshot["mode"] == "OBSERVE",
                        },
                    }
                    return self.respond(200, json.dumps(payload, sort_keys=True).encode(), "application/json")
                if path == "/api/analytics":
                    return self.respond(200, ResearchAnalyticsEngine.to_json(outer.state.analytics()).encode(), "application/json")
                if path == "/api/insights":
                    return self.respond(200, ResearchInsightsEngine.to_json(outer.state.insights()).encode(), "application/json")
                if path == "/api/readiness":
                    return self.respond(200, json.dumps(outer.state.readiness(),sort_keys=True).encode(), "application/json")
                if path.startswith("/exports/analytics."):
                    analytics = outer.state.analytics()
                    extension = path.rsplit(".", 1)[-1]
                    exports = {"json": (ResearchAnalyticsEngine.to_json, "application/json"), "csv": (ResearchAnalyticsEngine.to_csv, "text/csv; charset=utf-8"), "md": (ResearchAnalyticsEngine.to_markdown, "text/markdown; charset=utf-8")}
                    if extension not in exports:
                        return self.respond(404, b'{"error":"not found"}', "application/json")
                    formatter, content_type = exports[extension]
                    return self.respond(200, formatter(analytics).encode(), content_type)
                if path.startswith("/exports/insights."):
                    insights = outer.state.insights()
                    extension = path.rsplit(".", 1)[-1]
                    exports = {"json": (ResearchInsightsEngine.to_json, "application/json"), "csv": (ResearchInsightsEngine.to_csv, "text/csv; charset=utf-8"), "md": (ResearchInsightsEngine.to_markdown, "text/markdown; charset=utf-8")}
                    if extension not in exports:
                        return self.respond(404, b'{"error":"not found"}', "application/json")
                    formatter, content_type = exports[extension]
                    return self.respond(200, formatter(insights).encode(), content_type)
                pages = {"/": "Overview", "/observations": "Observations", "/cases": "Research Cases", "/orderflow": "Orderflow", "/signals": "Signal Research", "/analytics": "Analytics", "/insights": "Insights", "/health": "Health Center", "/exceptions": "Data Quality Exceptions", "/timeline": "Timeline", "/research": "Research"}
                if path in pages:
                    page = render(outer.state, pages[path], query.get("id", [None])[0])
                    return self.respond(200, page.encode(), "text/html; charset=utf-8")
                if path.startswith("/api/observations/"):
                    oid = unquote(path.removeprefix("/api/observations/"))
                    item = next((entry for entry in outer.state.snapshot()["observations"] if str(entry.get("observation_id")) == oid), None)
                    return self.respond(200 if item else 404, json.dumps(item or {"error": "observation not found"}).encode(), "application/json")
                if path.startswith("/api/cases/"):
                    cid = unquote(path.removeprefix("/api/cases/"))
                    with outer.state.lock:
                        full_cases = [dict(entry) for entry in outer.state.research_cases]
                    item = next((entry for entry in full_cases if str(entry.get("case_id")) == cid), None)
                    return self.respond(200 if item else 404, json.dumps(item or {"error": "case not found"}).encode(), "application/json")
                if path == "/api/research-cases" or path == "/api/research-cases/stats":
                    with outer.state.lock:
                        full = {"research_cases": [dict(entry) for entry in outer.state.research_cases]}
                    return self.respond(200, json.dumps(_research_cases_collection(full, query, stats_only=(path == "/api/research-cases/stats"))).encode(), "application/json")
                if path.startswith("/api/research-cases/"):
                    cid = unquote(path.removeprefix("/api/research-cases/"))
                    with outer.state.lock:
                        full_cases = [dict(entry) for entry in outer.state.research_cases]
                    item = next((entry for entry in full_cases if str(entry.get("case_id")) == cid), None)
                    return self.respond(200 if item else 404, json.dumps(item or {"error": "case not found"}).encode(), "application/json")
                if path.startswith("/reports/"):
                    name = Path(unquote(path.removeprefix("/reports/"))).name
                    root = outer.research_router.config.report_root.resolve()
                    candidate = (root / name).resolve()
                    if candidate.parent != root or not candidate.is_file() or candidate.suffix not in {".md", ".json"}:
                        return self.respond(404, b'{"error":"report not found"}', "application/json")
                    return self.respond(200, candidate.read_bytes(), "text/markdown; charset=utf-8" if candidate.suffix == ".md" else "application/json")
                return self.respond(404, b'{"error":"not found"}', "application/json")

            def do_POST(self):
                path = urlparse(self.path).path
                if path not in {"/api/research/quick", "/api/research/deep"}:
                    return self.respond(404, b'{"error":"not found"}', "application/json")
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size < 2 or size > 8192:
                        raise ValueError("request body must be between 2 and 8192 bytes")
                    value = json.loads(self.rfile.read(size))
                    query = str(value.get("query", "")).strip()
                    limit = 500 if path.endswith("/quick") else 2000
                    if not query or len(query) > limit:
                        raise ValueError(f"query must contain 1-{limit} characters")
                    report_type = str(value.get("type", "research_report"))
                    if report_type not in {"research_report", "deep"}:
                        raise ValueError("unsupported report type")
                    snapshot = outer.state.snapshot()
                    evidence = [{"source": item.get("source", "TIM_DASHBOARD"), "provenance": item.get("provenance", snapshot["provenance"]), "observed_at": item.get("observed_at"), "summary": item.get("summary", "")} for item in snapshot["observations"][-20:]]
                    requested = "quick" if path.endswith("/quick") else ("deep" if report_type == "deep" else "report")
                    with outer.research_lock:
                        routed = outer.research_router.route(query, evidence, requested_type=requested, context={"symbol": snapshot["market_status"].get("symbol", "BTCUSDT"), "timeframe": "mixed"})
                    result = asdict(routed["result"]) if is_dataclass(routed["result"]) else dict(routed["result"])
                    if routed["module"] == "B":
                        result["download_url"] = "/reports/" + Path(result["file"]).name
                    return self.respond(200, json.dumps({"selected_type": routed["selected_type"], "module": routed["module"], "result": result}).encode(), "application/json")
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    return self.respond(400, json.dumps({"error": str(exc)}).encode(), "application/json")
                except Exception:
                    return self.respond(500, b'{"error":"research processing failed"}', "application/json")

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="tim-dashboard", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
