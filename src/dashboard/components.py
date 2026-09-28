from __future__ import annotations

import html
import hashlib
import json
from typing import Any

from src.dashboard.helpers import _case_status, _duration, _required, _safe, _short, _status, _status_level


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


def _case_row(item: dict[str, Any]) -> str:
    opened, updated = item.get("opened_at"), item.get("updated_at")
    kinds = sorted({str(ev.get("kind")) for ev in item.get("evidence", []) if ev.get("kind")})
    rules = ", ".join(f"{key}:{value}" for key, value in sorted(item.get("rule_versions", {}).items()))
    case_id = str(item.get("case_id", ""))
    return (
        f"<tr data-status='{_safe(item.get('status'))}' data-type='{_safe(' '.join(kinds))}' data-rule='{_safe(rules)}' data-time='{_safe(updated)}'>"
        f"<td><a href='/cases?id={html.escape(case_id, quote=True)}' class='mono'>{_safe(_short(case_id, 18))}</a></td>"
        f"<td><span class='badge badge--{_case_status(item.get('status'))}'>{_safe(item.get('status'))}</span></td>"
        f"<td>{_safe(_duration(opened, updated))}</td><td>{len(item.get('observation_ids', []))}</td><td>{_safe(item.get('outcome'))}</td>"
        f"<td>{_safe(', '.join(item.get('missing_evidence', [])))}</td><td>{_safe(', '.join(kinds))}</td><td class='mono'>{_safe(rules)}</td></tr>"
    )


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
