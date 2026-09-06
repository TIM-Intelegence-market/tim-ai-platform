from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


MAX_EVIDENCE_BYTES = 2_000_000
MAX_GAP_ROWS = 500
UNAVAILABLE = "UNAVAILABLE"


def _safe(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def _path_value(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _first(value: Any, *paths: str, default: Any = None) -> Any:
    for path in paths:
        found = _path_value(value, path)
        if found not in (None, ""):
            return found
    return default


def _number(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _percent(value: Any) -> str | None:
    number = _number(value)
    if number is None:
        return None
    if 0 <= number <= 1:
        number *= 100
    return f"{number:.3f}%"


def _normalized_status(value: Any, default: str = UNAVAILABLE) -> str:
    if value in (None, "", {}):
        return default
    if isinstance(value, bool):
        return "PASS" if value else "FAIL"
    text = str(value).strip().upper().replace("_", " ")
    aliases = {
        "TRUE": "PASS",
        "FALSE": "FAIL",
        "OK": "PASS",
        "HEALTHY": "PASS",
        "GREEN": "PASS",
        "COMPLETED": "PASS",
        "COMPLETE": "PASS",
        "NOT STARTED": "TIME GATE",
        "WAITING": "PENDING HUMAN APPROVAL",
        "PENDING REAL HUMAN REVIEW": "PENDING HUMAN APPROVAL",
    }
    return aliases.get(text, text)


def _status_class(status: Any) -> str:
    text = _normalized_status(status)
    if text == "PASS" or text.startswith("PASS ") or text in {"ACTIVE", "RUNNING"}:
        return "green"
    if any(marker in text for marker in ("FAIL", "ERROR", "EXPOSED", "CRITICAL", "POSTGRES ADMIN ACTION REQUIRED")):
        return "red"
    return "yellow"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, UnicodeError, ValueError, TypeError):
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        if not path.is_file() or path.stat().st_size > MAX_EVIDENCE_BYTES:
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[:MAX_GAP_ROWS]:
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _artifact(root: Path, name: str) -> tuple[dict[str, Any], str]:
    path = root / name
    return _read_json(path), path.as_posix()


def _source(path: str, available: bool, *, legacy: bool = False) -> dict[str, Any]:
    return {
        "path": path,
        "available": available,
        "scope": "LEGACY_BASELINE" if legacy else "V2_COMPLETION",
    }


def _metric(value: Any, source: str, *, status: Any = None, unit: str | None = None) -> dict[str, Any]:
    present = value not in (None, "")
    return {
        "value": value if present else UNAVAILABLE,
        "status": _normalized_status(status, "MEASURED" if present else UNAVAILABLE),
        "unit": unit,
        "source": source,
    }


def _latest_daily_manifest(root: Path) -> tuple[dict[str, Any], str]:
    directory = root / "qualification_daily_manifests"
    try:
        candidates = sorted(
            (path for path in directory.iterdir() if path.is_file() and path.suffix == ".json"),
            key=lambda path: path.name,
        )
    except OSError:
        candidates = []
    if not candidates:
        return {}, directory.as_posix()
    path = candidates[-1]
    return _read_json(path), path.as_posix()


def _load_gaps(completion_root: Path, legacy_root: Path) -> tuple[list[dict[str, Any]], str, str]:
    candidates = (
        (completion_root / "data_gap_inventory.jsonl", "V2_COMPLETION"),
        (completion_root / "gap_inventory.jsonl", "V2_COMPLETION"),
        (legacy_root / "data_gap_ledger.jsonl", "LEGACY_BASELINE"),
    )
    for path, scope in candidates:
        rows = _read_jsonl(path)
        if rows:
            return rows, path.as_posix(), scope
    return [], candidates[0][0].as_posix(), "V2_COMPLETION"


def _coverage_card(label: str, coverage: Any, observed: Any, expected: Any, status: Any, source: str) -> dict[str, Any]:
    return {
        "label": label,
        "coverage": _percent(coverage) or UNAVAILABLE,
        "observed": observed if observed not in (None, "") else UNAVAILABLE,
        "expected": expected if expected not in (None, "") else UNAVAILABLE,
        "status": _normalized_status(status),
        "source": source,
    }


def build_operations_snapshot(
    base: dict[str, Any],
    completion_root: Path = Path("artifacts/v2_completion"),
    legacy_root: Path = Path("artifacts/v2_readiness"),
    live_watchdog_path: Path = Path("data/operational/watchdog_status.json"),
) -> dict[str, Any]:
    """Build a bounded, read-only control-center contract from persisted evidence.

    Completion evidence always wins. Legacy V2-readiness evidence is used only as
    a visibly labelled baseline and never promoted to a current completion claim.
    """

    names = (
        "implementation_state.json",
        "postgres_listener_before.json",
        "postgres_listener_after.json",
        "postgres_hba_validation.json",
        "credential_migration_evidence.json",
        "safe_stop_test.json",
        "durable_cursor_state.json",
        "queue_metrics.json",
        "watchdog_status.json",
        "backfill_candidate_manifest.json",
        "qualification_preregistration.json",
        "independent_case_audit.json",
        "final_test_summary.json",
        "final_protected_state.json",
        "baseline_manifest.json",
        "mcp_support_status.json",
    )
    evidence: dict[str, dict[str, Any]] = {}
    sources: dict[str, dict[str, Any]] = {}
    for name in names:
        value, path = _artifact(completion_root, name)
        evidence[name] = value
        sources[name] = _source(path, bool(value))

    legacy_names = (
        "coverage_final.json",
        "runtime_observability_snapshot.json",
        "validated_case_audit.json",
        "v2_readiness_matrix_final.json",
        "final_test_summary.json",
        "final_runtime_recheck.json",
    )
    legacy: dict[str, dict[str, Any]] = {}
    for name in legacy_names:
        value, path = _artifact(legacy_root, name)
        legacy[name] = value
        sources[f"legacy/{name}"] = _source(path, bool(value), legacy=True)
    live_watchdog = _read_json(live_watchdog_path)
    sources["live/watchdog_status.json"] = {
        "path": live_watchdog_path.as_posix(),
        "available": bool(live_watchdog),
        "scope": "LIVE_RUNTIME",
    }

    implementation = evidence["implementation_state.json"]
    listener_before = evidence["postgres_listener_before.json"]
    listener_after = evidence["postgres_listener_after.json"]
    hba = evidence["postgres_hba_validation.json"]
    credentials = evidence["credential_migration_evidence.json"]
    safe_stop = evidence["safe_stop_test.json"]
    cursor = evidence["durable_cursor_state.json"]
    queue = evidence["queue_metrics.json"]
    watchdog = evidence["watchdog_status.json"] or live_watchdog
    watchdog_source = (
        sources["watchdog_status.json"]["path"]
        if evidence["watchdog_status.json"]
        else sources["live/watchdog_status.json"]["path"]
    )
    backfill = evidence["backfill_candidate_manifest.json"]
    prereg = evidence["qualification_preregistration.json"]
    independent = evidence["independent_case_audit.json"]
    tests = evidence["final_test_summary.json"] or legacy["final_test_summary.json"]
    protected = evidence["final_protected_state.json"]
    mcp = evidence["mcp_support_status.json"]
    daily, daily_source = _latest_daily_manifest(completion_root)

    runtime_baseline = legacy["runtime_observability_snapshot.json"]
    legacy_coverage = legacy["coverage_final.json"]
    legacy_cases = legacy["validated_case_audit.json"]
    readiness = legacy["v2_readiness_matrix_final.json"]
    final_runtime = legacy["final_runtime_recheck.json"]

    live = base.get("operational_health", {})
    live_system = base.get("system_health", {})
    queue_depth = _first(queue, "queue_depth", "current.depth", "metrics.queue_depth")
    if queue_depth is None and live_system.get("queue_depth_measured_at"):
        queue_depth = live_system.get("queue_depth")
        queue_source = "/api/state system_health.queue_depth"
    else:
        queue_source = sources["queue_metrics.json"]["path"]
    completion_trading_actions = _first(implementation, "trading_action_count", "trading_actions")
    watchdog_trading_actions = _first(watchdog, "trading_actions")
    trading_action_value = completion_trading_actions if completion_trading_actions is not None else watchdog_trading_actions if watchdog_trading_actions is not None else _first(runtime_baseline, "trading_actions_emitted")
    trading_action_source = (
        sources["implementation_state.json"]["path"]
        if completion_trading_actions is not None
        else watchdog_source
        if watchdog_trading_actions is not None
        else sources["legacy/runtime_observability_snapshot.json"]["path"]
    )
    lan_after = _first(listener_after, "lan_test.status", "lan_probe.reachable", "lan_exposure_test", "lan_test")
    lan_before = _first(listener_before, "lan_test.status", "lan_probe.reachable", "lan_exposure_test", "lan_test")
    if lan_after is not None:
        lan_value = lan_after
        lan_source = sources["postgres_listener_after.json"]["path"]
        lan_status = _first(listener_after, "lan_test.status", "status", "result")
    elif lan_before is not None:
        lan_value = lan_before
        lan_source = sources["postgres_listener_before.json"]["path"]
        lan_status = _first(listener_before, "lan_test.status", "status", "result")
    else:
        lan_value = _first(final_runtime, "postgresql.lan_tcp_test")
        lan_source = sources["legacy/final_runtime_recheck.json"]["path"]
        lan_status = None

    security = {
        "status": _normalized_status(_first(implementation, "security_status", "gates.security.status", default=_first(final_runtime, "overall_security_gate"))),
        "listener_before": _metric(
            _first(listener_before, "listen_addresses", "listener", "postgresql.listen_addresses", "snapshot.listen_addresses"),
            sources["postgres_listener_before.json"]["path"],
            status=_first(listener_before, "status", "test_status", "result"),
        ),
        "listener_after": _metric(
            _first(listener_after, "listen_addresses", "listener", "postgresql.listen_addresses", "snapshot.listen_addresses"),
            sources["postgres_listener_after.json"]["path"],
            status=_first(listener_after, "status", "test_status", "result"),
        ),
        "lan_exposure": _metric(
            lan_value,
            lan_source,
            status=lan_status,
        ),
        "hba": _metric(
            _first(hba, "status", "hba_status", "validation.status"),
            sources["postgres_hba_validation.json"]["path"],
            status=_first(hba, "status", "validation.status"),
        ),
        "credential_rotation": _metric(
            _first(credentials, "rotation_status", "status", "credential_rotation"),
            sources["credential_migration_evidence.json"]["path"],
            status=_first(credentials, "rotation_status", "status"),
        ),
        "secret_provider": _metric(
            _first(credentials, "secret_provider.status", "secret_provider.name", "secret_provider.provider", "provider_status", default=_first(watchdog, "checks.secret_provider.value")),
            sources["credential_migration_evidence.json"]["path"] if credentials else watchdog_source,
            status=_first(credentials, "secret_provider.status", "provider_status", default=_first(watchdog, "checks.secret_provider.status")),
        ),
        "dashboard_binding": _metric("127.0.0.1 only", "DashboardServer._require_loopback_host", status="PASS"),
        "observe_only": _metric(base.get("mode"), "/api/state mode", status=base.get("mode") == "OBSERVE"),
        "trading_actions": _metric(
            trading_action_value,
            trading_action_source,
            status=(trading_action_value == 0) if trading_action_value is not None else None,
        ),
        "safe_stop": _metric(
            _first(safe_stop, "status", "safe_stop_status", "result"),
            sources["safe_stop_test.json"]["path"],
            status=_first(safe_stop, "status", "safe_stop_status", "result"),
        ),
        "last_test": _first(listener_after, "tested_at_utc", "captured_at_utc", default=_first(tests, "finished_at_utc")),
    }

    runtime = {
        "status": _normalized_status(_first(implementation, "runtime_status", "gates.runtime.status", default=live.get("status"))),
        "processes": _metric(_first(watchdog, "processes", "runtime.processes", "checks.runtime_process.value", default=_first(tests, "runtime.pid")), watchdog_source),
        "uptime": _metric(_first(watchdog, "uptime_seconds", "runtime.uptime_seconds", default=live.get("runtime_started_at")), watchdog_source, unit="seconds or start time"),
        "restarts": _metric(_first(watchdog, "restart_count", "runtime.restart_count", default=base.get("validator", {}).get("restart_count")), watchdog_source),
        "queue_depth": _metric(queue_depth, queue_source, status=_first(queue, "status", "queue_status")),
        "queue_age": _metric(_first(queue, "oldest_age_seconds", "queue_age_seconds", "current.oldest_age_seconds", default=_first(watchdog, "checks.queue_age.value")), sources["queue_metrics.json"]["path"] if queue else watchdog_source, status=_first(queue, "status", default=_first(watchdog, "checks.queue_age.status")), unit="s"),
        "cursor_age": _metric(_first(cursor, "cursor_age_seconds", "age_seconds", "metrics.cursor_age_seconds", default=_first(watchdog, "checks.cursor_age.value")), sources["durable_cursor_state.json"]["path"] if cursor else watchdog_source, status=_first(cursor, "status", default=_first(watchdog, "checks.cursor_age.status")), unit="s"),
        "receive_rate": _metric(_first(queue, "receive_rate_per_second", "rates.receive_per_second", "receive_rate"), sources["queue_metrics.json"]["path"], unit="events/s"),
        "persist_rate": _metric(_first(queue, "persist_rate_per_second", "rates.persist_per_second", "persist_rate"), sources["queue_metrics.json"]["path"], unit="events/s"),
        "drop_count": _metric(_first(queue, "drop_count", "counters.dropped", "discarded_events"), sources["queue_metrics.json"]["path"]),
        "duplicate_count": _metric(_first(queue, "duplicate_count", "counters.duplicates", "duplicate_attempts"), sources["queue_metrics.json"]["path"]),
        "late_count": _metric(_first(queue, "late_count", "counters.late", "very_late_events"), sources["queue_metrics.json"]["path"]),
        "source_to_store_latency": _metric(_first(queue, "source_to_store_latency_seconds.p95", "latency.source_to_store_p95_seconds", "source_to_store_p95_seconds"), sources["queue_metrics.json"]["path"], unit="s p95"),
        "event_loop_lag": _metric(_first(queue, "event_loop_lag_seconds", "latency.event_loop_lag_seconds"), sources["queue_metrics.json"]["path"], unit="s"),
        "disk": _metric(_first(watchdog, "disk", "disk_status", "metrics.disk", "checks.disk_space.value"), watchdog_source, status=_first(watchdog, "disk.status", "disk_status", "checks.disk_space.status")),
        "logs": _metric(_first(watchdog, "log_rotation_status", "logs.status", "log_retention.status", "checks.log_growth.value"), watchdog_source, status=_first(watchdog, "log_rotation_status", "logs.status", "checks.log_growth.status")),
        "watchdog": _metric(_first(watchdog, "status", "watchdog_status", "health.status"), watchdog_source, status=_first(watchdog, "status", "watchdog_status")),
        "collector_freshness": _metric(live.get("data_age_seconds"), "/api/state operational_health.data_age_seconds", status=live.get("stream"), unit="s"),
        "cursor": cursor,
        "queue": queue,
    }

    gaps_raw, gaps_source, gaps_scope = _load_gaps(completion_root, legacy_root)
    gaps: list[dict[str, Any]] = []
    for item in gaps_raw:
        gaps.append({
            "id": _first(item, "gap_id", "id", default=UNAVAILABLE),
            "start": _first(item, "start_utc", "window_start_utc", "start", default=UNAVAILABLE),
            "end": _first(item, "end_utc", "window_end_utc", "end", default=UNAVAILABLE),
            "priority": _first(item, "severity", "priority", default=UNAVAILABLE),
            "root_cause": _first(item, "root_cause_class", "root_cause", "cause", default=UNAVAILABLE),
            "repairability": _first(item, "repairability", default=UNAVAILABLE),
            "backfill_candidate": _first(item, "backfill_candidate_status", "repair_status", default=UNAVAILABLE),
            "provenance": _first(item, "source", "provenance", default=UNAVAILABLE),
            "status": _first(item, "status", "repair_status", default="OPEN"),
            "evidence": _first(item, "evidence_refs", "evidence", default=[]),
        })
    priorities = Counter(str(item["priority"]).upper() for item in gaps)

    frozen_source = sources["legacy/coverage_final.json"]["path"]
    frozen_completion_coverage = _first(implementation, "frozen_coverage", "frozen_coverage_percent")
    if frozen_completion_coverage is not None:
        frozen_values = implementation
        frozen_source = sources["implementation_state.json"]["path"]
        frozen_paths = ("frozen_coverage", "frozen_coverage_percent")
        frozen_observed_paths = ("frozen_valid_observations",)
        frozen_expected_paths = ("frozen_expected_observations",)
        frozen_status_paths = ("frozen_coverage_status",)
    elif _first(backfill, "coverage_metrics.frozen_live_capture.coverage") is not None:
        frozen_values = backfill
        frozen_source = sources["backfill_candidate_manifest.json"]["path"]
        frozen_paths = ("coverage_metrics.frozen_live_capture.coverage",)
        frozen_observed_paths = ("coverage_metrics.frozen_live_capture.valid_minutes",)
        frozen_expected_paths = ("coverage_metrics.frozen_live_capture.expected_minutes",)
        frozen_status_paths = ("coverage_metrics.frozen_live_capture.gate_status",)
    else:
        frozen_values = legacy_coverage
        frozen_paths = ("product_calculation.coverage", "coverage")
        frozen_observed_paths = ("product_calculation.valid_observations", "valid_observations")
        frozen_expected_paths = ("product_calculation.expected_observations", "expected_observations")
        frozen_status_paths = ("product_calculation.status", "status")
    frozen = _coverage_card(
        "Frozen Live Capture",
        _first(frozen_values, *frozen_paths),
        _first(frozen_values, *frozen_observed_paths),
        _first(frozen_values, *frozen_expected_paths),
        _first(frozen_values, *frozen_status_paths, default="FAIL" if _number(_first(frozen_values, *frozen_paths)) is not None and float(_first(frozen_values, *frozen_paths)) < 0.95 else None),
        frozen_source,
    )
    rolling_record = _first(legacy_coverage, "product_calculation.rolling.PT1440M", "dimensions.rolling.PT1440M", default={})
    backfill_status = _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.gate_status", "status", "gate_status", "governance_disposition")
    if _normalized_status(backfill_status) == "PASS" and backfill.get("readiness_counted") is False:
        backfill_status = "CANDIDATE PASS — NOT APPROVED"
    datasets = [
        frozen,
        _coverage_card("Backfill Candidate", _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.coverage", "coverage", "coverage_percent", "candidate.coverage"), _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.valid_minutes", "valid_observations", "candidate.valid_observations", "imported_rows"), _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.expected_minutes", "expected_observations", "candidate.expected_observations"), backfill_status, sources["backfill_candidate_manifest.json"]["path"]),
        _coverage_card("Approved Qualification Dataset", _first(daily, "approved_dataset.coverage", "qualification_dataset.coverage", default=_first(prereg, "approved_dataset.coverage")), _first(daily, "approved_dataset.valid_observations", "qualification_dataset.valid_observations"), _first(daily, "approved_dataset.expected_observations", "qualification_dataset.expected_observations"), _first(daily, "approved_dataset.status", "qualification_dataset.status", default=_first(prereg, "approved_dataset.status")), daily_source),
        _coverage_card("Prospective Qualification Campaign", _first(daily, "metrics.coverage", "coverage", "coverage_percent", "campaign.coverage", default=_first(prereg, "campaign.coverage")), _first(daily, "metrics.valid_observations", "valid_observations", "campaign.valid_observations"), _first(daily, "metrics.expected_observations", "expected_observations", "campaign.expected_observations"), _first(daily, "status", "campaign.status", default=_first(prereg, "campaign_status", "status", default=_first(backfill, "coverage_metrics.prospective_qualification.status"))), daily_source if daily else sources["qualification_preregistration.json"]["path"]),
        _coverage_card("Rolling Liveness", _first(rolling_record, "coverage", "coverage_percent"), _first(rolling_record, "valid_observations"), _first(rolling_record, "expected_observations"), _first(rolling_record, "status", default=live.get("stream")), sources["legacy/coverage_final.json"]["path"]),
    ]

    current_cases = _first(independent, "current.strict_independent_cases", "current.strict_independent_units", "current.strict_independent_30m_windows", "strict_independent_cases", default=_first(legacy_cases, "current_cutoff_audit.strict_independent_30m_windows"))
    frozen_cases = _first(independent, "frozen.strict_independent_cases", "frozen.strict_independent_units", "frozen_strict_independent_cases", default=_first(implementation, "frozen_strict_independent_cases", default=_first(legacy_cases, "frozen_cutoff_audit.strict_independent_30m_windows")))
    qualification_cases = _first(independent, "qualification.strict_independent_cases", "qualification.strict_independent_units", "qualification_independent_cases", default=_first(daily, "metrics.independent_case_count", "independent_cases"))
    required_cases = _first(independent, "required_independent_cases", "qualification.required_units", "current.required_units", "frozen.required_units", default=_first(legacy_cases, "current_cutoff_audit.required_independent_cases", default=1000 if legacy_cases else None))
    case_status = _first(independent, "status", "gate_status", "scientific_gate", default=_first(legacy_cases, "current_cutoff_audit.gate_status"))

    gates = _first(implementation, "gates", default=_first(readiness, "gates", default=[]))
    if isinstance(gates, dict):
        gates = [{"gate_id": key, **(value if isinstance(value, dict) else {"status": value})} for key, value in gates.items()]
    if not isinstance(gates, list):
        gates = []
    normalized_gates = []
    for gate in gates:
        if not isinstance(gate, dict):
            continue
        normalized_gates.append({
            "id": _first(gate, "gate_id", "id", default=UNAVAILABLE),
            "name": _first(gate, "name", "label", default=UNAVAILABLE),
            "status": _normalized_status(_first(gate, "status", "gate_status")),
            "limitation": _first(gate, "open_limitation", "reason", "blocker", default=UNAVAILABLE),
            "owner": _first(gate, "reviewer_requirement", "owner", "responsible_role", default=UNAVAILABLE),
            "evidence": _first(gate, "evidence", "evidence_refs", default=[]),
        })

    manual_review = _first(implementation, "manual_review_status", "science.manual_review_status", default=_first(independent, "manual_review_status", default=_first(readiness, "manual_scientific_approval_present")))
    human_approval = _first(implementation, "human_approval", "science.human_approval", default=_first(independent, "human_approval", default=_first(readiness, "manual_scientific_approval_present")))
    if manual_review is False:
        manual_review = "PENDING HUMAN APPROVAL"
    if human_approval is False:
        human_approval = "PENDING HUMAN APPROVAL"
    mcp_status = _first(mcp, "status", "secure_mcp_status", default=_first(implementation, "mcp_status", default=_first(readiness, "secure_mcp_status")))

    last_test = _first(tests, "finished_at_utc", "completed_at_utc", "generated_at_utc")
    incidents = [item for item in base.get("timeline", []) if str(item.get("severity", "")).upper() in {"ERROR", "CRITICAL", "HIGH"}]
    last_incident = incidents[-1] if incidents else None
    audit_sources = list(sources.values())

    return {
        "schema_version": "1.0.0",
        "product": "TIM OPERATIONS & RESEARCH CONTROL CENTER",
        "generated_at_utc": base.get("timestamp"),
        "mode": "OBSERVE",
        "read_only": True,
        "execution_disabled": True,
        "trading_locked": True,
        "security": security,
        "runtime": runtime,
        "datasets": datasets,
        "gaps": {
            "rows": gaps,
            "total_loaded": len(gaps),
            "p0": priorities.get("P0", 0),
            "p1": priorities.get("P1", 0),
            "source": gaps_source,
            "scope": gaps_scope,
            "bounded_at": MAX_GAP_ROWS,
        },
        "qualification": {
            "status": _normalized_status(_first(daily, "status", "campaign.status", default=_first(prereg, "campaign_status", "status"))),
            "campaign_id": _first(prereg, "campaign_id", "dataset_id", "program_id", default=UNAVAILABLE),
            "preregistered_at": _first(prereg, "preregistered_at_utc", "generated_at_utc", "created_at_utc", default=UNAVAILABLE),
            "started_at": _first(daily, "started_at_utc", "campaign.started_at_utc", default=_first(prereg, "start_utc", default=UNAVAILABLE)),
            "latest_manifest": daily_source,
            "source": sources["qualification_preregistration.json"]["path"],
        },
        "independent_cases": {
            "status": _normalized_status(case_status),
            "frozen": frozen_cases if frozen_cases is not None else UNAVAILABLE,
            "current": current_cases if current_cases is not None else UNAVAILABLE,
            "qualification": qualification_cases if qualification_cases is not None else UNAVAILABLE,
            "required": required_cases if required_cases is not None else UNAVAILABLE,
            "negative_controls": _first(independent, "negative_control_cases", "negative_controls", "current_negative_or_control_sampling", default=_first(legacy_cases, "current_cutoff_audit.negative_or_control_sampling", default=UNAVAILABLE)),
            "regime_coverage": _first(independent, "regime_coverage", "regimes.status", default=UNAVAILABLE),
            "manual_review": _normalized_status(manual_review, "PENDING HUMAN APPROVAL"),
            "human_approval": _normalized_status(human_approval, "PENDING HUMAN APPROVAL"),
            "source": sources["independent_case_audit.json"]["path"] if independent else sources["legacy/validated_case_audit.json"]["path"],
        },
        "readiness": {
            "status": _normalized_status(_first(implementation, "overall_status", "v2_status", default=_first(readiness, "overall_status"))),
            "gates": normalized_gates,
            "source": sources["implementation_state.json"]["path"] if implementation else sources["legacy/v2_readiness_matrix_final.json"]["path"],
        },
        "mcp": {
            "status": _normalized_status(mcp_status, "EXTERNAL ACTION REQUIRED"),
            "case_id": _first(mcp, "support_case_id", "case_id", default=_first(implementation, "mcp_support_case_id", default=UNAVAILABLE)),
            "workspace": _first(mcp, "workspace", "workspace_status", default=UNAVAILABLE),
            "developer_mode": _first(mcp, "developer_mode", "developer_mode_status", default=UNAVAILABLE),
            "tunnel_permissions": _first(mcp, "tunnel_permissions", "permissions", default=UNAVAILABLE),
            "source": sources["mcp_support_status.json"]["path"],
        },
        "audit": {
            "test_status": _normalized_status(_first(tests, "overall_test_status", "status")),
            "last_test": last_test if last_test else UNAVAILABLE,
            "passed": _first(tests, "full_suite.passed", "passed", default=UNAVAILABLE),
            "failed": _first(tests, "full_suite.failed", "failed", default=UNAVAILABLE),
            "warnings": _first(tests, "full_suite.warnings", "warnings.count", "warnings", default=UNAVAILABLE),
            "doctor": _normalized_status(_first(tests, "doctor.status")),
            "validate": _normalized_status(_first(tests, "validate.status")),
            "protected_state": _normalized_status(_first(protected, "status", "result", default=_first(tests, "protected_state.status"))),
            "last_incident": last_incident or UNAVAILABLE,
            "sources": audit_sources,
        },
        "sources": sources,
    }


def _badge(status: Any) -> str:
    normalized = _normalized_status(status)
    return f"<span class='badge badge--{_status_class(normalized)}'>{_safe(normalized)}</span>"


def _card(label: str, value: Any, note: Any, *, status: Any = None) -> str:
    if status is None:
        shown = _safe(value)
    else:
        suffix = f"<span class='metric-value'>{_safe(value)}</span>" if value not in (None, "") else ""
        shown = _badge(status) + suffix
    return (
        "<article class='card operations-card'>"
        f"<div class='card__label'>{_safe(label)}</div>"
        f"<div class='card__value'>{shown}</div>"
        f"<div class='card__note'>{_safe(note)}</div></article>"
    )


def _hero(title: str, text: str) -> str:
    return (
        "<div class='hero operations-hero'><div>"
        f"<p class='eyebrow'>TIM CONTROL CENTER</p><h1>{_safe(title)}</h1><p>{_safe(text)}</p>"
        "</div><div class='safety-stack' aria-label='Sicherheitsmodus'>"
        "<span class='badge badge--green'>OBSERVE-ONLY</span>"
        "<span class='badge badge--green'>TRADING LOCKED</span>"
        "<span class='badge badge--green'>EXECUTION DISABLED</span></div></div>"
    )


def _source_note(source: Any) -> str:
    return f"Quelle: {_safe(source)}"


def _metric_cards(metrics: dict[str, Any], definitions: Iterable[tuple[str, str]]) -> str:
    cards = []
    for key, label in definitions:
        metric = metrics.get(key, {})
        value = metric.get("value", UNAVAILABLE)
        unit = metric.get("unit")
        shown = f"{value} {unit}" if unit and value != UNAVAILABLE else value
        cards.append(_card(label, shown, _source_note(metric.get("source", UNAVAILABLE)), status=metric.get("status")))
    return "<div class='grid operations-grid'>" + "".join(cards) + "</div>"


def _dataset_section(data: dict[str, Any]) -> str:
    cards = []
    for item in data["datasets"]:
        note = f"{item['observed']} / {item['expected']} · {_source_note(item['source'])}"
        cards.append(_card(item["label"], item["coverage"], note, status=item["status"]))
    return (
        "<section class='panel'><div class='panel__head'><div><p class='eyebrow'>GETRENNTE DATENSÄTZE</p>"
        "<h2>Coverage darf nicht vermischt werden</h2></div><span class='badge badge--yellow'>5 EVIDENZRÄUME</span></div>"
        "<div class='grid operations-grid'>" + "".join(cards) + "</div></section>"
    )


def _market_contexts() -> str:
    """Reserve explicit, non-prescriptive horizons for future intelligence.

    These cards intentionally expose availability only. They must never infer a
    direction, confidence, or trading action from incomplete research evidence.
    """
    horizons = (
        ("SHORT", "Intraday structure", "60s · 1m · 5m", "Microstructure, flow and immediate regime"),
        ("MID", "Session context", "15m · 1h · 4h", "Momentum, participation and session continuity"),
        ("LONG", "Structural context", "1D · 1W", "Regime, macro context and durable market structure"),
    )
    cards = "".join(
        "<article class='horizon-card'>"
        f"<div class='horizon-card__head'><span class='horizon-key'>{_safe(key)}</span>"
        "<span class='badge badge--paused'>AWAITING INTELLIGENCE</span></div>"
        f"<h3>{_safe(title)}</h3><p class='horizon-timeframes'>{_safe(timeframes)}</p>"
        f"<p>{_safe(description)}</p><div class='horizon-track' aria-hidden='true'><span></span></div>"
        "</article>"
        for key, title, timeframes, description in horizons
    )
    return (
        "<section class='panel context-panel'><div class='panel__head'><div>"
        "<p class='eyebrow'>MARKET CONTEXT</p><h2>Intelligence horizons</h2>"
        "<p class='section-copy'>Clear separation of analysis windows. No directional signal is generated.</p>"
        "</div><span class='badge badge--paused'>PREPARED · INACTIVE</span></div>"
        f"<div class='horizon-grid'>{cards}</div></section>"
    )


def _overview(data: dict[str, Any]) -> str:
    security = data["security"]
    runtime = data["runtime"]
    cases = data["independent_cases"]
    gaps = data["gaps"]
    audit = data["audit"]
    headline = [
        _card("PostgreSQL Security", "", _source_note(security["listener_after"]["source"]), status=security["status"]),
        _card("Runtime Health", "", _source_note(runtime["collector_freshness"]["source"]), status=runtime["status"]),
        _card("Collector Freshness", runtime["collector_freshness"]["value"], "Sekunden seit letzter persistierter Marktdatenzeit", status=runtime["collector_freshness"]["status"]),
        _card("Queue Health", runtime["queue_depth"]["value"], _source_note(runtime["queue_depth"]["source"]), status=runtime["queue_depth"]["status"]),
        _card("Cursor Health", runtime["cursor_age"]["value"], _source_note(runtime["cursor_age"]["source"]), status=runtime["cursor_age"]["status"]),
        _card("Offene P0 / P1 Gaps", f"{gaps['p0']} / {gaps['p1']}", f"{gaps['total_loaded']} geladen · {gaps['scope']}"),
        _card("Independent Cases", cases["qualification"], f"Ziel {cases['required']} · Qualification", status=cases["status"]),
        _card("Manual Review", "", "Keine maschinelle Freigabe", status=cases["manual_review"]),
        _card("V2 Status", "", _source_note(data["readiness"]["source"]), status=data["readiness"]["status"]),
        _card("MCP Status", "", f"Case ID: {data['mcp']['case_id']}", status=data["mcp"]["status"]),
        _card("Letzter Test", audit["last_test"], f"{audit['passed']} pass · {audit['failed']} fail", status=audit["test_status"]),
        _card("Letzter Incident", audit["last_incident"] if isinstance(audit["last_incident"], str) else audit["last_incident"].get("event", UNAVAILABLE), "Persistierte Runtime-Timeline"),
    ]
    return (
        _hero(data["product"], "Sicherheits-, Laufzeit-, Daten- und Wissenschaftsstatus aus persistierter Evidenz.")
        + "<div class='terminal-strip' aria-label='Systemgrenzen'><span><i class='status-dot status-dot--green'></i>READ-ONLY</span><span>NO ORDERS</span><span>NO SHELL</span><span>NO GIT</span><span>NO SECRETS</span><strong>EXECUTION DISABLED</strong></div>"
        + "<section class='overview-section'><div class='section-heading'><div><p class='eyebrow'>OPERATIONAL HEALTH</p><h2>System control plane</h2></div><p>Live runtime and persisted evidence at a glance.</p></div>"
        + "<div class='grid operations-grid operations-grid--overview'>" + "".join(headline) + "</div></section>"
        + _market_contexts()
        + _dataset_section(data)
    )


def _security(data: dict[str, Any]) -> str:
    metrics = data["security"]
    return (
        _hero("Security", "Fail-closed Status der lokalen Betriebsgrenze; ohne Secrets.")
        + _metric_cards(metrics, (
            ("listener_before", "PostgreSQL Listener vorher"),
            ("listener_after", "PostgreSQL Listener nachher"),
            ("lan_exposure", "LAN Exposure Test"),
            ("hba", "HBA Status"),
            ("credential_rotation", "Credential Rotation"),
            ("secret_provider", "Secret Provider"),
            ("dashboard_binding", "Dashboard Binding"),
            ("observe_only", "OBSERVE-only"),
            ("trading_actions", "Trading Action Count"),
            ("safe_stop", "Safe Stop Status"),
        ))
        + f"<section class='panel'><h2>Letzter Security-Test</h2><p class='mono'>{_safe(metrics['last_test'])}</p>"
          "<p class='count-scope'>Fehlende oder nicht aktuelle Evidenz bleibt UNAVAILABLE und wird nicht als PASS interpretiert.</p></section>"
    )


def _runtime(data: dict[str, Any]) -> str:
    return (
        _hero("Runtime", "Echte, quellengebundene Messungen. Fehlende Instrumentierung bleibt sichtbar.")
        + _metric_cards(data["runtime"], (
            ("processes", "Prozesse"), ("uptime", "Uptime"), ("restarts", "Restarts"),
            ("queue_depth", "Queue Depth"), ("queue_age", "Queue Age"), ("cursor_age", "Cursor Age"),
            ("receive_rate", "Receive Rate"), ("persist_rate", "Persist Rate"), ("drop_count", "Drop Count"),
            ("duplicate_count", "Duplicate Count"), ("late_count", "Late Count"),
            ("source_to_store_latency", "Source-to-Store Latency"), ("event_loop_lag", "Event Loop Lag"),
            ("disk", "Disk"), ("logs", "Logs & Rotation"), ("watchdog", "Watchdog"),
        ))
    )


def _data_quality(data: dict[str, Any]) -> str:
    gaps = data["gaps"]
    return (
        _hero("Data Quality", "Getrennte Datenräume, Provenienz und offene Lücken.")
        + _dataset_section(data)
        + "<div class='grid operations-grid'>"
        + _card("Offene P0 Gaps", gaps["p0"], _source_note(gaps["source"]), status="FAIL" if gaps["p0"] else "PASS")
        + _card("Offene P1 Gaps", gaps["p1"], _source_note(gaps["source"]), status="FAIL" if gaps["p1"] else "PASS")
        + _card("Gap Scope", gaps["scope"], f"Antwort begrenzt auf {gaps['bounded_at']} Einträge")
        + "</div>"
    )


def _gap_explorer(data: dict[str, Any]) -> str:
    gaps = data["gaps"]
    rows = []
    for item in gaps["rows"]:
        evidence = item["evidence"] if isinstance(item["evidence"], str) else ", ".join(str(value) for value in item["evidence"])
        rows.append(
            "<tr>"
            f"<td class='mono'>{_safe(item['id'])}</td><td>{_safe(item['start'])}</td><td>{_safe(item['end'])}</td>"
            f"<td>{_badge(item['priority'])}</td><td>{_safe(item['root_cause'])}</td><td>{_safe(item['repairability'])}</td>"
            f"<td>{_safe(item['backfill_candidate'])}</td><td>{_safe(item['provenance'])}</td><td>{_badge(item['status'])}</td>"
            f"<td>{_safe(evidence)}</td></tr>"
        )
    body = "".join(rows) or "<tr><td colspan='10' class='empty'>Keine Gap-Evidenz verfügbar.</td></tr>"
    return (
        _hero("Gap Explorer", "Read-only Timeline und Ursachenregister; keine Rekonstruktion.")
        + f"<section class='panel'><div class='panel__head'><h2>Gap Inventory</h2><span class='badge badge--yellow'>{gaps['total_loaded']} · {_safe(gaps['scope'])}</span></div>"
          "<div class='table-wrap'><table><caption>Persistierte Datenlücken mit Ursachen- und Reparaturstatus</caption>"
          "<thead><tr><th>ID</th><th>Start UTC</th><th>Ende UTC</th><th>Priorität</th><th>Root Cause</th><th>Repairability</th><th>Backfill Candidate</th><th>Provenienz</th><th>Status</th><th>Evidenz</th></tr></thead>"
        + f"<tbody>{body}</tbody></table></div><p class='count-scope'>{_source_note(gaps['source'])} · maximal {gaps['bounded_at']} Einträge je Antwort.</p></section>"
    )


def _qualification(data: dict[str, Any]) -> str:
    campaign = data["qualification"]
    return (
        _hero("Qualification Campaign", "Vorregistrierter, prospektiver Evidenzraum mit unveränderlichen Tagesmanifesten.")
        + "<div class='grid operations-grid'>"
        + _card("Campaign Status", "", _source_note(campaign["source"]), status=campaign["status"])
        + _card("Campaign ID", campaign["campaign_id"], "Vorregistrierte Identität")
        + _card("Preregistered", campaign["preregistered_at"], "Keine rückwirkende Definition")
        + _card("Started", campaign["started_at"], "Start nur nach allen technischen Gates")
        + "</div>"
        + _dataset_section(data)
        + f"<section class='panel'><h2>Latest immutable daily manifest</h2><p class='mono'>{_safe(campaign['latest_manifest'])}</p></section>"
    )


def _cases(data: dict[str, Any]) -> str:
    cases = data["independent_cases"]
    return (
        _hero("Research & Independent Cases", "Unabhängige Einheiten, Kontrollen, Regime und menschliche Prüfung.")
        + "<div class='grid operations-grid'>"
        + _card("Frozen Independent Cases", cases["frozen"], "Historischer unveränderlicher Gate-Scope", status=cases["status"])
        + _card("Current Independent Cases", cases["current"], "Aktueller wissenschaftlicher Audit")
        + _card("Qualification Independent Cases", cases["qualification"], "Nur genehmigte Prospektivkampagne")
        + _card("Required Cases", cases["required"], "Gate-Minimum")
        + _card("Negative / Control Cases", cases["negative_controls"], "Keine synthetische Ergänzung")
        + _card("Regime Coverage", cases["regime_coverage"], "Vorregistrierte Strata")
        + _card("Manual Review", "", "Reale menschliche Prüfung erforderlich", status=cases["manual_review"])
        + _card("Human Approval", "", "Keine Selbstfreigabe durch TIM", status=cases["human_approval"])
        + "</div>"
        + "<section class='panel quick-links'><h2>Read-only Forschungsansichten</h2>"
          "<a href='/observations'>Observations</a><a href='/cases'>Research Cases</a><a href='/signals'>Signal Research</a>"
          "<a href='/analytics'>Analytics</a><a href='/insights'>Insights</a></section>"
    )


def _readiness(data: dict[str, Any]) -> str:
    rows = []
    for gate in data["readiness"]["gates"]:
        evidence = gate["evidence"] if isinstance(gate["evidence"], str) else ", ".join(str(value) for value in gate["evidence"])
        rows.append(
            f"<tr><td class='mono'>{_safe(gate['id'])}</td><td>{_safe(gate['name'])}</td><td>{_badge(gate['status'])}</td>"
            f"<td>{_safe(gate['limitation'])}</td><td>{_safe(gate['owner'])}</td><td>{_safe(evidence)}</td></tr>"
        )
    body = "".join(rows) or "<tr><td colspan='6' class='empty'>Keine Gate-Evidenz verfügbar.</td></tr>"
    return (
        _hero("V2 Readiness", "Einzelgates ohne künstliche Gesamtprozentzahl.")
        + f"<section class='panel'><div class='panel__head'><h2>V2 Gate Matrix</h2>{_badge(data['readiness']['status'])}</div>"
          "<div class='table-wrap'><table><caption>Readiness-Gates und reale Blocker</caption><thead><tr><th>Gate</th><th>Name</th><th>Status</th><th>Blocker / Limit</th><th>Zuständig</th><th>Evidenz</th></tr></thead>"
        + f"<tbody>{body}</tbody></table></div><p class='count-scope'>Zulässige Zustände: PASS · FAIL · BLOCKED · PENDING HUMAN APPROVAL · TIME GATE · EXTERNAL ACTION REQUIRED.</p></section>"
    )


def _mcp(data: dict[str, Any]) -> str:
    mcp = data["mcp"]
    return (
        _hero("Graphify & MCP", "Getrennter externer Supportpfad; kein Bestandteil der V2-Core-Freigabe.")
        + "<div class='grid operations-grid'>"
        + _card("Secure MCP", "", _source_note(mcp["source"]), status=mcp["status"])
        + _card("Support Case ID", mcp["case_id"], "UNAVAILABLE bedeutet: kein belegter Fall")
        + _card("Workspace", mcp["workspace"], "Externer Zustand")
        + _card("Developer Mode", mcp["developer_mode"], "Externer Zustand")
        + _card("Tunnel Permissions", mcp["tunnel_permissions"], "Read · Manage · Use getrennt prüfen")
        + "</div><section class='panel safety-callout'><b>Trennung:</b> MCP-Status kann die Security-, Daten- oder Science-Gates von TIM nicht überschreiben.</section>"
    )


def _audit(data: dict[str, Any]) -> str:
    audit = data["audit"]
    source_rows = "".join(
        f"<tr><td class='mono'>{_safe(item['path'])}</td><td>{_badge('PASS' if item['available'] else UNAVAILABLE)}</td><td>{_safe(item['scope'])}</td></tr>"
        for item in audit["sources"]
    ) or "<tr><td colspan='3' class='empty'>Keine Completion-Evidenz verfügbar.</td></tr>"
    return (
        _hero("Audit & Evidence", "Tests, Protected State, Vorfälle und quellengebundene Evidenz.")
        + "<div class='grid operations-grid'>"
        + _card("Full Suite", f"{audit['passed']} pass / {audit['failed']} fail", f"Warnungen: {audit['warnings']}", status=audit["test_status"])
        + _card("Doctor", "", "Repository-Diagnose", status=audit["doctor"])
        + _card("Validate", "", "Repository-Vertrag", status=audit["validate"])
        + _card("Protected State", "", "Geschützte Artefakte", status=audit["protected_state"])
        + "</div>"
        + f"<section class='panel'><h2>Letzter Test</h2><p class='mono'>{_safe(audit['last_test'])}</p><h2>Letzter Incident</h2><pre class='code'>{_safe(json.dumps(audit['last_incident'], ensure_ascii=False, sort_keys=True))}</pre></section>"
        + "<section class='panel'><div class='table-wrap'><table><caption>Geladene, read-only Evidenzquellen</caption><thead><tr><th>Quelle</th><th>Verfügbar</th><th>Scope</th></tr></thead>"
        + f"<tbody>{source_rows}</tbody></table></div></section>"
    )


OPERATIONS_PAGES = {
    "Overview": _overview,
    "Security": _security,
    "Runtime": _runtime,
    "Data Quality": _data_quality,
    "Gap Explorer": _gap_explorer,
    "Qualification Campaign": _qualification,
    "Research & Independent Cases": _cases,
    "V2 Readiness": _readiness,
    "Graphify & MCP": _mcp,
    "Audit & Evidence": _audit,
}


def render_operations_page(page: str, data: dict[str, Any]) -> str:
    renderer = OPERATIONS_PAGES.get(page)
    if renderer is None:
        raise ValueError(f"unsupported operations page: {page}")
    return renderer(data)
