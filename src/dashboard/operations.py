from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.dashboard.status_logic import build_current_status, current_report


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


def _current_server_snapshot(root: Path) -> dict[str, Any]:
    """Load an explicitly unapproved current-state audit, never a campaign."""
    value, source = _artifact(root, "current_state.json")
    coverage = _first(value, "result.coverage", default={})
    gap_rows = _first(value, "result.gaps")
    valid = (
        value.get("purpose") == "CURRENT_STATE_NOT_QUALIFICATION"
        and value.get("qualification_started") is False
        and value.get("historical_artifacts_modified") is False
        and isinstance(coverage, dict)
        and coverage.get("v2_approved") is False
        and coverage.get("trading_approved") is False
        and isinstance(coverage.get("product_calculation"), dict)
        and isinstance(gap_rows, list)
        and all(isinstance(row, dict) for row in gap_rows)
        and bool(value.get("start")) and bool(value.get("end"))
    )
    if not valid:
        return {"available": False, "source": source}
    return {
        "available": True,
        "source": source,
        "start": value["start"],
        "end": value["end"],
        "captured_at": _captured_at(coverage),
        "coverage": coverage["product_calculation"],
        "gap_ranges": _first(coverage, "gap_summary.ranges", default=UNAVAILABLE),
        "gap_rows": gap_rows[:MAX_GAP_ROWS],
        "missing_minutes": _first(coverage, "gap_summary.missing_minutes", default=UNAVAILABLE),
        "strict_cases": _first(value, "result.cases.current_cutoff_audit.strict_independent_30m_windows", default=UNAVAILABLE),
        "case_status": _first(value, "result.cases.current_cutoff_audit.gate_status", default=UNAVAILABLE),
        "case_scope": "ALL_PERSISTED_HISTORY_THROUGH_CUTOFF",
        "controls": _first(value, "result.cases.current_cutoff_audit.negative_or_control_sampling", default=UNAVAILABLE),
        "manual_review": _first(value, "result.cases.manual_review_status", default=UNAVAILABLE),
        "qualification_counted": False,
    }


def _source(path: str, available: bool, *, legacy: bool = False, captured_at: Any = None) -> dict[str, Any]:
    return {
        "path": path,
        "available": available,
        "scope": "LEGACY_BASELINE" if legacy else "V2_COMPLETION",
        "captured_at": captured_at,
    }


def _captured_at(value: dict[str, Any]) -> Any:
    """When an evidence file was measured, from its own content (not file mtime)."""
    return _first(value, "captured_at_utc", "updated_at_utc", "generated_at_utc", "computed_at_utc", "finished_at_utc", "tested_at_utc")


LIVE_FRESH_SECONDS = 120
LIVE_EVIDENCE_MAX_AGE_SECONDS = 600


def _seconds_since(value: Any) -> float | None:
    """Age of an ISO timestamp in seconds, or None when absent or unparsable."""
    from datetime import datetime, timezone

    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds()


def _evidence_age(value: Any) -> str:
    """Visible age of persisted evidence, so an old file is not read as current."""
    age = _seconds_since(value)
    if age is None or age < 0:
        return ""
    days = int(age // 86_400)
    if days < 1:
        return "heute"
    label = "vor 1 Tag" if days == 1 else f"vor {days} Tagen"
    return f"{label} · veraltet" if days > 7 else label


def _log_growth_text(value: Any) -> Any:
    """Readable form of the watchdog's largest-log finding instead of a raw dict."""
    if isinstance(value, dict) and isinstance(value.get("largest_bytes"), (int, float)):
        name = Path(str(value.get("path") or "")).name or "unbekannte Datei"
        return f"größte Logdatei {value['largest_bytes'] / 1_048_576:.1f} MB · {name}"
    return value


def _metric(value: Any, source: str, *, status: Any = None, unit: str | None = None) -> dict[str, Any]:
    present = value not in (None, "")
    return {
        "value": value if present else UNAVAILABLE,
        "status": _normalized_status(status, "MEASURED" if present else UNAVAILABLE),
        "unit": unit,
        "source": source,
    }


LIVE_TELEMETRY_FIELDS = (
    # runtime key, system_health key, unit, rounding
    ("restarts", "restart_total", None, 0),
    ("queue_age", "queue_oldest_age", "s", 1),
    ("cursor_age", "cursor_age", "s", 1),
    ("receive_rate", "receive_rate_per_second", "events/s", 2),
    ("persist_rate", "persist_rate_per_second", "events/s", 2),
    ("drop_count", "rejected_total", None, 0),
    ("duplicate_count", "duplicate_total", None, 0),
    ("late_count", "late_total", None, 0),
    ("source_to_store_latency", "source_to_store_latency", "s (last)", 3),
    ("event_loop_lag", "event_loop_lag", "s", 3),
)


def _apply_live_telemetry(runtime: dict[str, Any], live_system: dict[str, Any]) -> None:
    """Fill runtime metrics from the running process's own ingestion telemetry.

    The runtime samples ingestion_metrics every few seconds and publishes it in
    system_health. A sample older than the freshness window is not live and
    leaves the persisted value (or UNAVAILABLE) in place. Counters are lifetime
    totals since the metrics table was created, and are labelled as such.
    """
    age = _seconds_since(live_system.get("health_snapshot_observed_at"))
    if age is None or age > LIVE_FRESH_SECONDS:
        return
    source = f"/api/state system_health (ingestion_metrics, sampled {int(age)}s ago)"
    for key, field, unit, digits in LIVE_TELEMETRY_FIELDS:
        value = live_system.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        shown: Any = int(value) if digits == 0 else round(float(value), digits)
        if key in ("drop_count", "duplicate_count", "late_count", "restarts"):
            unit = "total"
        current = runtime.get(key) or {}
        runtime[key] = _metric(shown, source, status=current.get("status") if current.get("value") not in (None, UNAVAILABLE) else None, unit=unit)


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


def _running_campaign(root: Path) -> dict[str, Any]:
    """Read the prospective campaign that scripts/v2_qualification_daily.py maintains.

    The campaign lives in data/qualification (state file plus one immutable
    manifest per settled UTC day). The older artifacts/v2_completion files only
    describe the pre-registration, so without this the pages kept showing
    "NOT STARTED" and 0 cases while the campaign was running.
    """
    path = root / "qualification_campaign.json"
    campaign = _read_json(path)
    if not campaign.get("campaign_status"):
        return {}
    manifests: list[tuple[str, dict[str, Any]]] = []
    try:
        files = sorted(item for item in (root / "daily").iterdir() if item.is_file() and item.suffix == ".json")
    except OSError:
        files = []
    for item in files[-400:]:
        value = _read_json(item)
        if isinstance(value.get("metrics"), dict):
            manifests.append((item.as_posix(), value))
    latest_path, latest = manifests[-1] if manifests else ((root / "daily").as_posix(), {})
    metrics = latest.get("metrics") or {}

    def total(key: str) -> int | None:
        values = [entry["metrics"].get(key) for _, entry in manifests]
        if not values or not all(type(value) is int for value in values):
            return None
        return sum(values)

    # An abort is written as its own marker; the campaign state file itself is
    # frozen and keeps saying ACTIVE. The marker wins.
    abort_path = root / "campaign_aborted.json"
    aborted = _read_json(abort_path)
    is_aborted = str(aborted.get("status", "")).upper() == "ABORTED"
    return {
        "status": "ABORTED" if is_aborted else str(campaign.get("campaign_status")),
        "aborted_at": aborted.get("aborted_at_utc") if is_aborted else None,
        "abort_note": aborted.get("note") if is_aborted else None,
        "abort_source": abort_path.as_posix() if is_aborted else None,
        "dataset_id": campaign.get("dataset_id"),
        "started_at": campaign.get("start_utc") or campaign.get("activated_at_utc"),
        "minimum_days": _first(campaign, "duration.pre_registered_minimum_days"),
        "case_target": campaign.get("case_target") or metrics.get("independent_case_target"),
        "coverage_target": campaign.get("coverage_target"),
        "manifests_written": len(manifests),
        "latest_manifest": latest_path,
        "latest_day": latest.get("day") or latest.get("utc_date") or (Path(latest_path).stem if manifests else None),
        "independent_cases": metrics.get("independent_case_count"),
        "cumulative_coverage": metrics.get("cumulative_coverage"),
        "observed_minutes": total("observed_minutes"),
        "expected_minutes": total("expected_minutes"),
        "source": path.as_posix(),
    }


def _ci_test_of_deployment(deployment: dict[str, Any], recorded_last_test: Any) -> dict[str, Any] | None:
    """The full-suite CI run of the commit that is deployed, if it is newer.

    data/operational/deployment.json is written by scripts/record_deployment.py
    when ~/TIM-live is moved to a new commit. The CI job runs the whole suite on
    exactly that commit, so it is the current test evidence; the old summary
    file stays the fallback.
    """
    test = deployment.get("ci_test") if isinstance(deployment, dict) else None
    if not isinstance(test, dict) or not test.get("completed_at_utc"):
        return None
    newer = _seconds_since(test["completed_at_utc"])
    older = _seconds_since(recorded_last_test)
    if newer is None or (older is not None and older < newer):
        return None
    conclusion = str(test.get("conclusion", "")).lower()
    return {
        "status": "PASS" if conclusion == "success" else "FAIL" if conclusion else UNAVAILABLE,
        "completed_at": test["completed_at_utc"],
        "passed": test.get("passed", UNAVAILABLE),
        "failed": test.get("failed", UNAVAILABLE),
        "skipped": test.get("skipped", UNAVAILABLE),
        "source": f"data/operational/deployment.json · CI {test.get('url') or ''} · commit {str(deployment.get('commit') or '')[:7]}",
    }


def _dashboard_refresh(status: dict[str, Any], path: Path) -> dict[str, Any]:
    """State of the dashboard refresh agent (scripts/dashboard_refresh.py), for the evidence strip."""
    decision = status.get("decision") if isinstance(status, dict) else None
    if not isinstance(decision, dict):
        return {"status": UNAVAILABLE, "value": UNAVAILABLE, "note": "Agent noch nicht gelaufen", "source": path.as_posix()}
    age = _seconds_since(status.get("checked_at_utc"))
    action = str(decision.get("action", ""))
    deploy = status.get("deploy") if isinstance(status.get("deploy"), dict) else {}
    if age is None or age > 30 * 60:
        state = "STALE"
    elif deploy.get("result") == "ROLLED_BACK":
        state = "FAIL"
    elif status.get("health_ok") is False:
        state = "DEGRADED"
    elif action == "HOLD" and decision.get("reason") == "study_protected_paths":
        state = "WAITING"  # held on purpose until the study ends: not an alarm
    elif action == "HOLD":
        state = "BLOCKED"
    elif action == "WAIT":
        state = "WAITING"
    else:
        state = "PASS"
    minutes = "" if age is None else f"vor {int(age // 60)} min"
    text = str(decision.get("text") or decision.get("reason") or "")
    if state == "WAITING" and decision.get("reason") == "study_protected_paths":
        text = f"wartet bis Studienende · {text}"
    return {
        "status": state,
        "value": str(status.get("deployed_commit") or UNAVAILABLE)[:7],
        "note": " · ".join(part for part in (minutes, text) if part),
        "reason": decision.get("reason"),
        "source": path.as_posix(),
    }


def _recheck_gates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Put today's measured state next to each archived gate that has live evidence.

    The archived verdict stays as recorded; ``current_status`` and
    ``current_note`` say what the same question looks like today, with the
    source. Gates without a current machine measurement are left alone.
    """
    security = snapshot["security"]
    runtime = snapshot["runtime"]
    current = snapshot["current_status"]
    audit = snapshot["audit"]
    cases = snapshot["independent_cases"]
    datasets = snapshot["datasets"]
    rolling = datasets[-1] if datasets else {}
    qualification = snapshot["qualification"]
    checks: dict[str, tuple[Any, str]] = {}

    listener = security.get("listener_after") or {}
    if "runtime: SHOW listen_addresses" in str(listener.get("source")):
        checks["TECH-SECURITY"] = (
            security["status"],
            f"PostgreSQL lauscht nur auf {listener.get('value')} (live geprüft {str(security.get('last_test') or '')[:16]}); Zugangsdaten-Rotation hat keinen aktuellen Nachweis.",
        )
    watchdog_state = current.get("watchdog", {}).get("status")
    cursor_live = "system_health" in str(runtime["cursor_age"].get("source")) or runtime["cursor_age"].get("value") != UNAVAILABLE
    queue_live = str(runtime["queue_depth"].get("source", "")).startswith("/api/state")
    if watchdog_state and cursor_live and queue_live:
        checks["TECH-RUNTIME"] = (
            watchdog_state,
            f"Watchdog {watchdog_state}, Cursor-Alter {_metric_value(runtime['cursor_age'])}, Queue {_metric_value(runtime['queue_depth'])}, Log-Rotation {runtime['logs'].get('status')}.",
        )
    if audit.get("deployed_commit") not in (None, UNAVAILABLE) and audit.get("test_source", "").startswith("data/operational/deployment.json"):
        checks["TECH-FULL-SUITE"] = (
            audit["test_status"],
            f"CI-Volllauf für laufenden Commit {str(audit['deployed_commit'])[:7]}: {audit['passed']} bestanden, {audit['failed']} fehlgeschlagen ({str(audit['last_test'])[:16]}).",
        )
    if rolling.get("coverage") not in (None, UNAVAILABLE):
        checks["V2-B01"] = (
            rolling.get("status"),
            f"Abdeckung der letzten 24 h: {rolling.get('coverage')} ({rolling.get('observed')}/{rolling.get('expected')} Minuten).",
        )
    if str(qualification.get("status", "")).upper() == "ABORTED":
        checks["V2-B04"] = (
            cases["status"],
            f"Prospektive Kampagne abgebrochen; {cases['qualification']} von {cases['required']} unabhängigen Fällen bis zum Abbruch, zählen nicht.",
        )
    gates = []
    for gate in snapshot["readiness"]["gates"]:
        found = checks.get(str(gate.get("id")))
        if found:
            gate = {**gate, "current_status": _normalized_status(found[0]), "current_note": found[1]}
        gates.append(gate)
    return gates


READINESS_STALE_DAYS = 14


def _current_readiness(recorded: str, gates: list[dict[str, Any]], source: dict[str, Any], running: dict[str, Any]) -> dict[str, Any]:
    """V2 readiness as it stands now.

    The gate matrix comes from a completion audit that is only rewritten by
    hand. Once it is older than READINESS_STALE_DAYS it is shown as history,
    and the current verdict comes from the prospective campaign: an aborted
    campaign means V2 is not qualified, whatever the old matrix said.
    """
    result = {"status": recorded, "gates": gates, "source": source["path"], "recorded_status": None, "recorded_at": source.get("captured_at")}
    age = _seconds_since(source.get("captured_at"))
    stale = age is not None and age > READINESS_STALE_DAYS * 86400
    state = str(running.get("status", "")).upper() if running else ""
    if state == "ABORTED":
        result.update({
            "status": "NOT QUALIFIED — CAMPAIGN ABORTED",
            "source": running["abort_source"],
            "recorded_status": f"HISTORICAL — {recorded}",
            "current_reason": running.get("abort_note") or "",
        })
    elif stale and recorded not in (UNAVAILABLE, "", None):
        result.update({
            "status": f"STALE — {recorded}",
            "recorded_status": f"HISTORICAL — {recorded}",
        })
    return result


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
    rolling_liveness_path: Path = Path("data/operational/rolling_liveness.json"),
    qualification_root: Path = Path("data/qualification"),
) -> dict[str, Any]:
    """Build a bounded, read-only control-center contract from persisted evidence.

    Current runtime status uses fresh operational reports. Completion and legacy
    evidence remain available for their recorded scope and release gates.
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
        sources[name] = _source(path, bool(value), captured_at=_captured_at(value))

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
        sources[f"legacy/{name}"] = _source(path, bool(value), legacy=True, captured_at=_captured_at(value))
    live_watchdog = _read_json(live_watchdog_path)
    current_snapshot = _current_server_snapshot(legacy_root)
    sources["current/current_state.json"] = {
        "path": current_snapshot["source"],
        "available": current_snapshot["available"],
        "scope": "V2_COMPLETION",
        "purpose": "CURRENT_STATE_NOT_QUALIFICATION",
        "qualification_counted": False,
        "captured_at": current_snapshot.get("captured_at"),
    }
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
    # A live report wins even when stale/failed: an old green artifact must
    # never replace a current failure or conceal a stopped status producer.
    watchdog = live_watchdog or evidence["watchdog_status.json"]
    watchdog_source = (
        sources["watchdog_status.json"]["path"]
        if not live_watchdog
        else sources["live/watchdog_status.json"]["path"]
    )
    backfill = evidence["backfill_candidate_manifest.json"]
    prereg = evidence["qualification_preregistration.json"]
    independent = evidence["independent_case_audit.json"]
    tests = evidence["final_test_summary.json"] or legacy["final_test_summary.json"]
    protected = evidence["final_protected_state.json"]
    mcp = evidence["mcp_support_status.json"]
    daily, daily_source = _latest_daily_manifest(completion_root)
    running = _running_campaign(qualification_root)

    runtime_baseline = legacy["runtime_observability_snapshot.json"]
    legacy_coverage = legacy["coverage_final.json"]
    legacy_cases = legacy["validated_case_audit.json"]
    readiness = legacy["v2_readiness_matrix_final.json"]
    final_runtime = legacy["final_runtime_recheck.json"]

    live = base.get("operational_health", {})
    live_system = base.get("system_health", {})
    # A live measurement from the running process beats a persisted file: the
    # file is a snapshot of some earlier run and would otherwise freeze the
    # pipeline view on an old value (or on UNAVAILABLE while the header shows
    # the live depth).  A live value older than the freshness window is not live.
    live_queue_age = _seconds_since(live_system.get("queue_depth_measured_at"))
    if live_queue_age is not None and live_queue_age <= LIVE_FRESH_SECONDS and live_system.get("queue_depth") is not None:
        queue_depth = live_system.get("queue_depth")
        queue_source = "/api/state system_health.queue_depth"
    else:
        queue_depth = _first(queue, "queue_depth", "current.depth", "metrics.queue_depth")
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
    # A bare "0 trading actions" count is only substantiated when continuity
    # evidence (queue metrics, durable cursor) or a runtime-observed count
    # exists; otherwise the claim renders UNAVAILABLE instead of PASS.
    trading_action_continuity = bool(queue) or bool(cursor) or watchdog_trading_actions is not None
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

    live_listener = live_system.get("postgres_listener") if isinstance(live_system.get("postgres_listener"), dict) else {}
    listener_age = _seconds_since(live_listener.get("checked_at_utc"))
    listener_is_live = listener_age is not None and listener_age <= LIVE_EVIDENCE_MAX_AGE_SECONDS
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
        "trading_actions": {
            **_metric(
                trading_action_value,
                trading_action_source,
                status=(trading_action_value == 0) if trading_action_value is not None else None,
            ),
            "continuity": trading_action_continuity,
        },
        "safe_stop": _metric(
            _first(safe_stop, "status", "safe_stop_status", "result"),
            sources["safe_stop_test.json"]["path"],
            status=_first(safe_stop, "status", "safe_stop_status", "result"),
        ),
        "last_test": _first(listener_after, "tested_at_utc", "captured_at_utc", default=_first(tests, "finished_at_utc")),
    }
    security["status_source"] = (
        sources["implementation_state.json"]["path"]
        if _first(implementation, "security_status", "gates.security.status") is not None
        else sources["legacy/final_runtime_recheck.json"]["path"]
    )
    if listener_is_live:
        # The runtime checks the listener itself every minute; a weeks-old
        # audit file must not override what PostgreSQL reports right now.
        security["status"] = _normalized_status(live_listener.get("status"))
        security["listener_after"] = _metric(live_listener.get("listen_addresses"), str(live_listener.get("source")), status=live_listener.get("status"))
        security["lan_exposure"] = _metric(",".join(live_listener.get("exposed_addresses") or []) or "none (loopback only)", str(live_listener.get("source")), status=live_listener.get("status"))
        security["last_test"] = live_listener.get("checked_at_utc")
        security["status_source"] = str(live_listener.get("source"))

    runtime = {
        "status": _normalized_status(_first(implementation, "runtime_status", "gates.runtime.status", default=live.get("status"))),
        "processes": _metric(_first(watchdog, "processes", "runtime.processes", "checks.runtime_process.value", default=_first(tests, "runtime.pid")), watchdog_source),
        "uptime": _metric(_first(watchdog, "uptime_seconds", "runtime.uptime_seconds", default=live.get("runtime_started_at")), watchdog_source, unit="seconds or start time"),
        "restarts": _metric(_first(watchdog, "restart_count", "runtime.restart_count", default=base.get("validator", {}).get("restart_count")), watchdog_source),
        "queue_depth": _metric(queue_depth, queue_source, status=None if queue_source.startswith("/api/state") else _first(queue, "status", "queue_status")),
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
        "logs": _metric(_log_growth_text(_first(watchdog, "log_rotation_status", "logs.status", "log_retention.status", "checks.log_growth.value")), watchdog_source, status=_first(watchdog, "log_rotation_status", "logs.status", "checks.log_growth.status")),
        "watchdog": _metric(_first(watchdog, "status", "watchdog_status", "health.status"), watchdog_source, status=_first(watchdog, "status", "watchdog_status")),
        "collector_freshness": _metric(live.get("data_age_seconds"), "/api/state operational_health.data_age_seconds", status=live.get("stream"), unit="s"),
        "cursor": cursor,
        "queue": queue,
    }

    _apply_live_telemetry(runtime, live_system)

    gaps_raw, gaps_source, gaps_scope = _load_gaps(completion_root, legacy_root)
    if current_snapshot["available"]:
        gaps_raw = current_snapshot["gap_rows"]
        gaps_source = current_snapshot["source"]
        gaps_scope = "V2_COMPLETION"
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
    rolling_source = sources["legacy/coverage_final.json"]["path"]
    rolling_live = _read_json(rolling_liveness_path)
    if isinstance(rolling_live, dict) and rolling_live.get("valid_observations") is not None:
        # Fresh DB-derived rolling window wins over the frozen August baseline.
        rolling_record = dict(rolling_live)
        rolling_source = str(rolling_liveness_path)
        rolling_age = _seconds_since(rolling_live.get("computed_at_utc"))
        if rolling_age is None or rolling_age > LIVE_EVIDENCE_MAX_AGE_SECONDS:
            rolling_record["status"] = f"STALE — {_normalized_status(rolling_live.get('status'))} {_evidence_age(rolling_live.get('computed_at_utc'))}".strip()
    operational_root = live_watchdog_path.parent
    server_health_path = operational_root / "server_health.json"
    maintenance_path = operational_root / "maintenance_last_run.json"
    horizon_path = operational_root / "horizon_readiness.json"
    horizon_report = _read_json(horizon_path)
    horizon_report_status = current_report(horizon_report, str(horizon_path), now=datetime.now(timezone.utc))
    history_path = operational_root / "history_recovery.json"
    history_report = _read_json(history_path)
    history_status = current_report(history_report, str(history_path), now=datetime.now(timezone.utc))
    maintenance_report = _read_json(maintenance_path)
    maintenance_source = str(maintenance_path)
    if not maintenance_report and history_report:
        # The Mac runs no tim_maintenance.py timer; com.tim.history-recovery does
        # the gap maintenance there (every 30 s), so its report is the evidence.
        maintenance_report = history_report
        maintenance_source = str(history_path)
    current_status = build_current_status(
        _read_json(server_health_path), rolling_live, maintenance_report, live_watchdog,
        sources={"runtime": str(server_health_path), "data": str(rolling_liveness_path),
                 "maintenance": maintenance_source, "watchdog": str(live_watchdog_path)},
    )
    runtime["status"] = current_status["runtime"]["status"]
    runtime["status_source"] = current_status["runtime"]["source"]
    runtime["watchdog"]["status"] = current_status["watchdog"]["status"]
    backfill_status = _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.gate_status", "status", "gate_status", "governance_disposition")
    if _normalized_status(backfill_status) == "PASS" and backfill.get("readiness_counted") is False:
        backfill_status = "CANDIDATE PASS — NOT APPROVED"
    datasets = [
        frozen,
        _coverage_card("Backfill Candidate", _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.coverage", "coverage", "coverage_percent", "candidate.coverage"), _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.valid_minutes", "valid_observations", "candidate.valid_observations", "imported_rows"), _first(backfill, "coverage_metrics.backfill_eligible_if_governance_approved.expected_minutes", "expected_observations", "candidate.expected_observations"), backfill_status, sources["backfill_candidate_manifest.json"]["path"]),
        _coverage_card("Approved Qualification Dataset", _first(daily, "approved_dataset.coverage", "qualification_dataset.coverage", default=_first(prereg, "approved_dataset.coverage")), _first(daily, "approved_dataset.valid_observations", "qualification_dataset.valid_observations"), _first(daily, "approved_dataset.expected_observations", "qualification_dataset.expected_observations"), _first(daily, "approved_dataset.status", "qualification_dataset.status", default=_first(prereg, "approved_dataset.status")), daily_source),
        _coverage_card("Prospective Qualification Campaign", running["cumulative_coverage"], running["observed_minutes"], running["expected_minutes"], running["status"], running["latest_manifest"] if running["manifests_written"] else running["source"])
        if running else
        _coverage_card("Prospective Qualification Campaign", _first(daily, "metrics.coverage", "coverage", "coverage_percent", "campaign.coverage", default=_first(prereg, "campaign.coverage")), _first(daily, "metrics.valid_observations", "valid_observations", "campaign.valid_observations"), _first(daily, "metrics.expected_observations", "expected_observations", "campaign.expected_observations"), _first(daily, "status", "campaign.status", default=_first(prereg, "campaign_status", "status", default=_first(backfill, "coverage_metrics.prospective_qualification.status"))), daily_source if daily else sources["qualification_preregistration.json"]["path"]),
        _coverage_card("Rolling Liveness", _first(rolling_record, "coverage", "coverage_percent"), _first(rolling_record, "valid_observations"), _first(rolling_record, "expected_observations"), _first(rolling_record, "status", default=live.get("stream")), rolling_source),
    ]
    # Frozen capture is immutable historical evidence: its FAIL is a recorded
    # fact, not an open repair task. Label it as such so the room reads as
    # historical/superseded rather than actionable.
    datasets[0]["disposition"] = "HISTORICAL / IMMUTABLE — frozen window, SUPERSEDED for coverage purposes, NOT APPROVAL SOURCE"
    # The frozen window never changes, so its result must not look like a live
    # alarm next to the current rooms. Keep the recorded verdict visible, but
    # mark it historical (neutral severity) instead of a red current FAIL.
    if datasets[0]["status"] not in (UNAVAILABLE, "", None):
        datasets[0]["recorded_status"] = datasets[0]["status"]
        datasets[0]["status"] = f"HISTORICAL — {datasets[0]['status']}"

    if current_snapshot["available"]:
        measured = current_snapshot["coverage"]
        card = _coverage_card(
            "Server-Bestandsaufnahme", measured.get("coverage"),
            measured.get("valid_observations"), measured.get("expected_observations"),
            measured.get("status"), current_snapshot["source"],
        )
        card["disposition"] = (
            f"{current_snapshot['start']} → {current_snapshot['end']} · "
            "Bestandsaufnahme; keine Qualifizierung oder V2-/Handelsfreigabe."
        )
        # Keep the historical first row and the rolling last row stable.
        datasets.insert(1, card)

    current_cases = _first(independent, "current.strict_independent_cases", "current.strict_independent_units", "current.strict_independent_30m_windows", "strict_independent_cases", default=_first(legacy_cases, "current_cutoff_audit.strict_independent_30m_windows"))
    current_case_source = sources["independent_case_audit.json"]["path"] if independent else sources["legacy/validated_case_audit.json"]["path"]
    current_case_cutoff = _first(independent, "current.cutoff_utc", default=_first(legacy_cases, "current_cutoff_utc"))
    snapshot_cases = current_snapshot.get("strict_cases")
    if current_snapshot["available"] and isinstance(snapshot_cases, int) and not isinstance(snapshot_cases, bool) and snapshot_cases >= 0:
        current_cases = snapshot_cases
        current_case_source = current_snapshot["source"]
        current_case_cutoff = current_snapshot["end"]
    frozen_cases = _first(independent, "frozen.strict_independent_cases", "frozen.strict_independent_units", "frozen_strict_independent_cases", default=_first(implementation, "frozen_strict_independent_cases", default=_first(legacy_cases, "frozen_cutoff_audit.strict_independent_30m_windows")))
    qualification_cases = _first(independent, "qualification.strict_independent_cases", "qualification.strict_independent_units", "qualification_independent_cases", default=_first(daily, "metrics.independent_case_count", "independent_cases"))
    required_cases = _first(independent, "required_independent_cases", "qualification.required_units", "current.required_units", "frozen.required_units", default=_first(legacy_cases, "current_cutoff_audit.required_independent_cases", default=1000 if legacy_cases else None))
    case_status = _first(independent, "status", "gate_status", "scientific_gate", default=_first(legacy_cases, "current_cutoff_audit.gate_status"))

    if running:
        # The running campaign is the only source that may count qualification
        # cases. Until the target is reached the gate waits for time, it has not failed.
        qualification_cases = running["independent_cases"] if running["independent_cases"] is not None else 0
        required_cases = running["case_target"] or required_cases
        if str(running["status"]).upper() == "ACTIVE":
            reached = isinstance(qualification_cases, int) and isinstance(required_cases, int) and qualification_cases >= required_cases
            case_status = "PENDING HUMAN APPROVAL" if reached else "TIME GATE"
        elif str(running["status"]).upper() == "ABORTED":
            case_status = "ABORTED — NOT COUNTED"
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
    deployment_path = live_watchdog_path.parent / "deployment.json"
    deployment = _read_json(deployment_path)
    ci_test = _ci_test_of_deployment(deployment, last_test)
    refresh_path = live_watchdog_path.parent / "dashboard_refresh.json"
    dashboard_refresh = _dashboard_refresh(_read_json(refresh_path), refresh_path)
    incidents = [item for item in base.get("timeline", []) if str(item.get("severity", "")).upper() in {"ERROR", "CRITICAL", "HIGH"}]
    last_incident = incidents[-1] if incidents else None
    audit_sources = list(sources.values())

    snapshot = {
        "schema_version": "1.0.0",
        "product": "TIM OPERATIONS & RESEARCH CONTROL CENTER",
        "generated_at_utc": base.get("timestamp"),
        "mode": "OBSERVE",
        "read_only": True,
        "execution_disabled": True,
        "trading_locked": True,
        "current_status": current_status,
        "horizon_evidence": {"report": horizon_report, **horizon_report_status},
        "history_recovery": {"report": history_report, **history_status},
        "security": security,
        "runtime": runtime,
        "datasets": datasets,
        "current_server_snapshot": current_snapshot,
        "evidence_dates": {item["path"]: item["captured_at"] for item in sources.values() if item.get("captured_at")},
        "gaps": {
            "rows": gaps,
            "total_loaded": len(gaps),
            "p0": priorities.get("P0", 0),
            "p1": priorities.get("P1", 0),
            "source": gaps_source,
            "scope": gaps_scope,
            "purpose": "CURRENT_STATE_NOT_QUALIFICATION" if current_snapshot["available"] else gaps_scope,
            "bounded_at": MAX_GAP_ROWS,
        },
        "qualification": {
            "status": _normalized_status(_first(daily, "status", "campaign.status", default=_first(prereg, "campaign_status", "status"))),
            "campaign_id": _first(prereg, "campaign_id", "dataset_id", "program_id", default=UNAVAILABLE),
            "preregistered_at": _first(prereg, "preregistered_at_utc", "generated_at_utc", "created_at_utc", default=UNAVAILABLE),
            "started_at": _first(daily, "started_at_utc", "campaign.started_at_utc", default=_first(prereg, "start_utc", default=UNAVAILABLE)),
            "latest_manifest": daily_source,
            "source": sources["qualification_preregistration.json"]["path"],
            "manifests_written": UNAVAILABLE,
            "minimum_days": UNAVAILABLE,
        } if not running else {
            "status": _normalized_status(running["status"]),
            "campaign_id": running["dataset_id"] or _first(prereg, "campaign_id", "dataset_id", "program_id", default=UNAVAILABLE),
            "preregistered_at": _first(prereg, "preregistered_at_utc", "generated_at_utc", "created_at_utc", default=UNAVAILABLE),
            "started_at": running["started_at"] or UNAVAILABLE,
            "latest_manifest": running["latest_manifest"],
            "source": running["source"],
            "manifests_written": running["manifests_written"],
            "minimum_days": running["minimum_days"] if running["minimum_days"] is not None else UNAVAILABLE,
        },
        "independent_cases": {
            "status": _normalized_status(case_status),
            "frozen": frozen_cases if frozen_cases is not None else UNAVAILABLE,
            "current": current_cases if current_cases is not None else UNAVAILABLE,
            "current_source": current_case_source,
            "current_cutoff": current_case_cutoff,
            "qualification": qualification_cases if qualification_cases is not None else UNAVAILABLE,
            "required": required_cases if required_cases is not None else UNAVAILABLE,
            "negative_controls": _first(independent, "negative_control_cases", "negative_controls", "current_negative_or_control_sampling", default=_first(legacy_cases, "current_cutoff_audit.negative_or_control_sampling", default=UNAVAILABLE)),
            "regime_coverage": _first(independent, "regime_coverage", "regimes.status", default=UNAVAILABLE),
            "manual_review": _normalized_status(manual_review, "PENDING HUMAN APPROVAL"),
            "human_approval": _normalized_status(human_approval, "PENDING HUMAN APPROVAL"),
            "source": running["latest_manifest"] if running and running["manifests_written"] else (sources["independent_case_audit.json"]["path"] if independent else sources["legacy/validated_case_audit.json"]["path"]),
        },
        "readiness": _current_readiness(
            _normalized_status(_first(implementation, "overall_status", "v2_status", default=_first(readiness, "overall_status"))),
            normalized_gates,
            sources["implementation_state.json"] if implementation else sources["legacy/v2_readiness_matrix_final.json"],
            running,
        ),
        "mcp": {
            "status": _normalized_status(mcp_status, "EXTERNAL ACTION REQUIRED"),
            "case_id": _first(mcp, "support_case_id", "case_id", default=_first(implementation, "mcp_support_case_id", default=UNAVAILABLE)),
            "workspace": _first(mcp, "workspace", "workspace_status", default=UNAVAILABLE),
            "developer_mode": _first(mcp, "developer_mode", "developer_mode_status", default=UNAVAILABLE),
            "tunnel_permissions": _first(mcp, "tunnel_permissions", "permissions", default=UNAVAILABLE),
            "source": sources["mcp_support_status.json"]["path"],
        },
        "audit": {
            "test_status": ci_test["status"] if ci_test else _normalized_status(_first(tests, "overall_test_status", "status")),
            "last_test": ci_test["completed_at"] if ci_test else (last_test if last_test else UNAVAILABLE),
            "passed": ci_test["passed"] if ci_test else _first(tests, "full_suite.passed", "passed", default=UNAVAILABLE),
            "failed": ci_test["failed"] if ci_test else _first(tests, "full_suite.failed", "failed", default=UNAVAILABLE),
            "warnings": ci_test["skipped"] if ci_test else _first(tests, "full_suite.warnings", "warnings.count", "warnings", default=UNAVAILABLE),
            "test_source": ci_test["source"] if ci_test else sources["final_test_summary.json"]["path"],
            "deployed_commit": deployment.get("commit") or UNAVAILABLE,
            "deployed_at": deployment.get("deployed_at_utc") or UNAVAILABLE,
            "dashboard_refresh": dashboard_refresh,
            "doctor": _normalized_status(_first(tests, "doctor.status")),
            "validate": _normalized_status(_first(tests, "validate.status")),
            "protected_state": _normalized_status(_first(protected, "status", "result", default=_first(tests, "protected_state.status"))),
            "last_incident": last_incident or UNAVAILABLE,
            "sources": audit_sources,
            "incidents": list(reversed(incidents[-20:])),
        },
        "live": {
            "database": live.get("database"),
            "stream": live.get("stream"),
            "status": live.get("status"),
            "last_data_at": live.get("last_data_at"),
            "data_age_seconds": live.get("data_age_seconds"),
            "checked_at": live.get("checked_at"),
            "runtime_started_at": live.get("runtime_started_at"),
            "queue_depth": live.get("queue_depth"),
            "queue_model": live.get("queue_model"),
        },
        "gate_model": base.get("gate_model", {}),
        "sources": sources,
    }
    snapshot["readiness"]["gates"] = _recheck_gates(snapshot)
    return snapshot


"""Control Center page renderers (UI-V3).

Presentation layer only: every value shown here comes from the operations
contract produced by :func:`build_operations_snapshot` or is explicitly
rendered as UNAVAILABLE. Severity classification lives in
``src.dashboard.design_system`` so identical states look identical everywhere.
"""

from src.dashboard.design_system import (
    UNAVAILABLE,
    attention_list,
    cell_state,
    attention_row,
    chip,
    coverage_rows,
    evidence_chip,
    gate_rows,
    horizon_panel,
    incident_card,
    metric_strip,
    page_head,
    pipeline,
    section,
    severity,
    state_banner,
    status_rows,
)


def _short_time(value: Any) -> str:
    text = str(value) if value not in (None, "") else ""
    return text[:19].replace("T", " ") if len(text) >= 19 else (text or UNAVAILABLE)


def _human_duration(seconds: Any) -> str:
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return UNAVAILABLE
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 36:
        return f"{hours}h {minutes % 60}m"
    days = hours // 24
    return f"{days}d {hours % 24}h"


def _metric_value(metric: dict[str, Any], *, unit: bool = True) -> str:
    value = metric.get("value", UNAVAILABLE)
    suffix = f" {metric['unit']}" if unit and metric.get("unit") and value != UNAVAILABLE else ""
    return f"{value}{suffix}"


def _duration_between(start: Any, end: Any) -> str:
    from datetime import datetime

    def _parse(value: Any) -> Any:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    parsed_start, parsed_end = _parse(start), _parse(end)
    if not parsed_start or not parsed_end:
        return UNAVAILABLE
    return _human_duration((parsed_end - parsed_start).total_seconds())


def _attention_rows(data: dict[str, Any]) -> list[str]:
    """Derive the active problem list strictly from persisted/live evidence.

    Only states that are not validated-healthy produce rows; archived findings
    are labelled as historical instead of being presented as current failures.
    """
    live = data.get("live", {})
    security = data["security"]
    runtime = data["runtime"]
    cases = data["independent_cases"]
    gaps = data["gaps"]
    readiness = data["readiness"]
    mcp = data["mcp"]
    audit = data["audit"]
    current = data["current_status"]
    rows: list[tuple[int, str]] = []

    dates = data.get("evidence_dates") or {}

    def add(status: Any, title: str, detail: str, source: str = "") -> None:
        key = severity(status)
        if key == "ok":
            return
        # Every file-based problem carries the day it was measured, so an old
        # audit result is never read as something that broke just now.
        captured = dates.get(source)
        if captured:
            source = f"{source} · Stand {str(captured)[:10]} ({_evidence_age(captured) or 'heute'})"
        weight = {"fail": 0, "blocked": 1, "degraded": 2, "warn": 3, "info": 4, "unknown": 5, "disabled": 6}[key]
        rows.append((weight, attention_row(status, title, detail, source)))

    for key, title in (("runtime", "Runtime process"), ("data", "Current candle coverage"),
                       ("maintenance", "Gap maintenance"), ("watchdog", "Independent watchdog")):
        item = current[key]
        findings = ", ".join(str(finding["check"]) for finding in item.get("findings", []))
        add(item["status"], title,
            f"reported={item['reported_status']} · checked={item['checked_at'] or UNAVAILABLE} · "
            + (f"age={item['age_seconds']}s" if item["age_seconds"] is not None else "age=—")
            + (f" · checks: {findings}" if findings else ""),
            item["source"])
    if security["status"] not in ("PASS",) and severity(security["status"]) != "ok":
        add(security["status"], "PostgreSQL security gate", str(security["status"]), str(security.get("status_source") or security["listener_after"]["source"]))
    if severity(live.get("stream")) != "ok":
        add(live.get("stream", UNAVAILABLE), "Live market data stream", f"stream={live.get('stream', UNAVAILABLE)} · last data {live.get('last_data_at') or UNAVAILABLE}", "/api/state operational_health.stream")
    if runtime["cursor_age"]["value"] == UNAVAILABLE:
        add(UNAVAILABLE, "Cursor age not instrumented", "No durable cursor age evidence is loaded; queue/database continuity cannot be verified from the dashboard.", str(runtime["cursor_age"]["source"]))
    if severity(runtime["queue_depth"]["status"]) not in ("ok", "unknown") :
        add(runtime["queue_depth"]["status"], "Queue health degraded", f"depth={runtime['queue_depth']['value']}", str(runtime["queue_depth"]["source"]))
    if isinstance(gaps["p0"], int) and gaps["p0"] > 0:
        add("FAIL", "Open P0 data gaps", f"{gaps['p0']} P0 · {gaps['p1']} P1 · {gaps['total_loaded']} loaded ({gaps['scope']})", str(gaps["source"]))
    elif isinstance(gaps["p1"], int) and gaps["p1"] > 0:
        add("WARN", "Open P1 data gaps", f"{gaps['p1']} P1 · {gaps['total_loaded']} loaded ({gaps['scope']})", str(gaps["source"]))
    if severity(cases["status"]) != "ok":
        add(cases["status"], "Independent qualification cases", f"{cases['qualification']} of {cases['required']} required independent cases", str(cases["source"]))
    if cases["manual_review"] == "PENDING HUMAN APPROVAL":
        add("PENDING HUMAN APPROVAL", "Manual scientific review pending", "No machine-side approval exists; a real human review is required before qualification counts.", str(cases["source"]))
    if severity(readiness["status"]) != "ok":
        detail = str(readiness["status"])
        if readiness.get("current_reason"):
            detail += f" · {readiness['current_reason']}"
        if readiness.get("recorded_status"):
            detail += f" · alte Gate-Matrix: {readiness['recorded_status']} (Stand {str(readiness.get('recorded_at') or '')[:10]})"
        add(readiness["status"], "V2 readiness gate", detail, str(readiness["source"]))
    if severity(mcp["status"]) == "blocked":
        add(mcp["status"], "MCP external action required", f"support case {mcp['case_id']}", str(mcp["source"]))
    last_incident = audit.get("last_incident")
    if isinstance(last_incident, dict) and last_incident:
        add("WARN", "Runtime incident in bounded timeline",
            " · ".join(str(part) for part in (last_incident.get("timestamp"), last_incident.get("event", UNAVAILABLE), last_incident.get("summary")) if part),
            "see Incidents & Gaps")
    history = data.get("history_recovery", {})
    if history.get("report") and history.get("status") != "PASS":
        add(history.get("status"), "Historical data recovery",
            ", ".join(str(error) for error in history["report"].get("errors", [])) or "Check recovery report freshness.",
            history.get("source", ""))
    rows.sort(key=lambda item: item[0])
    return [row for _, row in rows[:12]]


def _pipeline_stages(data: dict[str, Any]) -> list[tuple[str, Any, str, str]]:
    live = data.get("live", {})
    runtime = data["runtime"]
    cases = data["independent_cases"]
    readiness = data["readiness"]
    freshness = live.get("data_age_seconds")
    fresh = isinstance(freshness, (int, float)) and 0 <= freshness <= 120
    candle_status = "PASS" if fresh and live.get("stream") == "GREEN" else ("WARN" if live.get("stream") == "GREEN" else "FAIL")
    rolling = data["datasets"][-1]
    return [
        ("Source", live.get("stream", UNAVAILABLE), "public market feed", f"stream={live.get('stream', UNAVAILABLE)}"),
        ("Ingest", runtime["collector_freshness"]["status"], _metric_value(runtime["collector_freshness"]), "seconds since last persisted market time"),
        ("Queue", runtime["queue_depth"]["status"], f"{runtime['queue_depth']['value']} ev", str(live.get("queue_model") or runtime["queue_depth"]["source"])),
        ("Persist", live.get("database", UNAVAILABLE), "durable outbox", f"database={live.get('database', UNAVAILABLE)}"),
        ("Cursor", runtime["cursor_age"]["status"], _metric_value(runtime["cursor_age"]), "durable cursor age"),
        ("Candles", candle_status, _short_time(live.get("last_data_at")), "latest persisted candle close"),
        ("Quality", rolling.get("status", UNAVAILABLE), f"rolling {rolling.get('coverage', UNAVAILABLE)}", "rolling 1440m coverage gate"),
        ("Research", cases["status"], f"{cases['qualification']} / {cases['required']} cases", "independent qualification"),
        ("Readiness", readiness["status"], "V2 gate matrix", f"{len(readiness['gates'])} gates"),
    ]


def _horizons(data: dict[str, Any]) -> list[tuple[str, str, str, str, list[tuple[str, Any]]]]:
    """Render measured inputs; descriptive features never imply qualification."""
    evidence = data.get("horizon_evidence", {})
    records = evidence.get("report", {}).get("horizons", {})
    records = records if isinstance(records, dict) else {}
    horizons = []
    for key, name, timeframes, description in (
        ("SHORT", "Intraday structure", "60s · 1m · 5m", "Microstructure, flow and immediate regime"),
        ("MID", "Session context", "15m · 1h · 4h", "Momentum, participation and session continuity"),
        ("LONG", "Structural context", "1D · 1W", "Regime, macro context and durable market structure"),
    ):
        record = records.get(key, {})
        record = record if isinstance(record, dict) else {}
        fresh = evidence.get("status") == "PASS"
        missing = "STALE" if evidence.get("status") == "STALE" else UNAVAILABLE
        dimensions = [(label, record.get(field, UNAVAILABLE) if fresh else missing)
                      for label, field in (("Data", "data"), ("Features", "features"),
                                          ("Quality", "quality"), ("Qualification", "qualification"),
                                          ("Readiness", "readiness"))]
        if fresh and record:
            description += (f" · {record.get('valid_minutes', UNAVAILABLE)}/{record.get('expected_minutes', UNAVAILABLE)}"
                            " closed 1m inputs; candle continuity and descriptive features only.")
        if not record and evidence.get("status") != "STALE":
            dimensions[-1] = ("Readiness", "AWAITING INTELLIGENCE")
        horizons.append((key, name, timeframes, description, dimensions))
    return horizons


def _overview(data: dict[str, Any]) -> str:
    live = data.get("live", {})
    runtime = data["runtime"]
    cases = data["independent_cases"]
    readiness = data["readiness"]
    audit = data["audit"]

    current = data["current_status"]
    history = data.get("history_recovery", {})
    history_report = history.get("report", {})
    runtime_status = current["runtime"]["status"]
    if live.get("status") == "RED":
        runtime_status = "FAIL"
    status_word = {"PASS": "RUNNING", "WARN": "DEGRADED", "FAIL": "IMPAIRED",
                   "STALE": "STALE"}.get(runtime_status, "STATE UNKNOWN")
    freshness = live.get("data_age_seconds")
    stream_raw = live.get("stream", UNAVAILABLE)
    fresh = isinstance(freshness, (int, float)) and 0 <= freshness <= 120
    if stream_raw == "GREEN" and fresh:
        data_label = "LIVE"
    elif stream_raw == "GREEN":
        data_label = "STALE"
    elif stream_raw in ("RED", "FAIL"):
        data_label = "DOWN"
    else:
        data_label = "UNKNOWN"

    level1 = state_banner(
        runtime_status,
        status_word,
        f"Live operational state at { _short_time(live.get('checked_at')) } UTC · OBSERVE mode, no execution path",
        metrics=[
            ("Live data", data_label, f"stream={stream_raw}"),
            ("Freshness", f"{freshness}s" if isinstance(freshness, (int, float)) else UNAVAILABLE, "since last persisted market time"),
            ("Queue", f"{live.get('queue_depth')} events" if live.get("queue_depth") is not None else UNAVAILABLE, str(live.get("queue_model") or "")),
            ("Database", live.get("database", UNAVAILABLE), "postgres write path"),
            ("Last event", _short_time(live.get("last_data_at")), "latest persisted candle close"),
            ("Uptime", _duration_between(live.get("runtime_started_at"), live.get("checked_at")), "current runtime process"),
        ],
    )

    status_strip = section(
        "Aktueller Status", "Betrieb und Demo-Bereitschaft",
        metric_strip([
            ("Runtime", current["runtime"]["status"], "", current["runtime"]["status"]),
            ("Kerzenabdeckung", current["data"]["coverage_percent"], "%", current["data"]["status"]),
            ("Wartung", current["maintenance"]["status"], "", current["maintenance"]["status"]),
            ("Watchdog", current["watchdog"]["status"], "", current["watchdog"]["status"]),
            ("Demo-Trading", "INAKTIV", "", current["demo"]["status"]),
            ("Historische Reparatur", history_report.get("candles_rebuilt"),
             "Kerzen im letzten Lauf", history.get("status", UNAVAILABLE)),
        ]),
        note="Aktuelle Berichte verfallen nach 5 Minuten. Demo-Trading benötigt eine eigene Bereitschaftsprüfung.",
    )
    level2 = section(
        "Active problems",
        "Needs attention",
        attention_list(_attention_rows(data), "No active problem detected from the currently loaded evidence."),
        note="Derived only from loaded evidence. Absent evidence is listed as unavailable instead of being silently ignored.",
    )

    level3 = section(
        "Pipeline",
        "Source to readiness",
        pipeline(_pipeline_stages(data)),
        note="Each stage shows its current evidence-backed state. Stages without instrumentation show UNKNOWN, never a substitute value.",
    )

    gate_summary = gate_rows(readiness["gates"][:6])
    gate_link = f"<p class='cc-note'>All {len(readiness['gates'])} gates, blockers and owners: <a href='/v2-readiness'>V2 Readiness →</a></p>"
    horizon_body = horizon_panel(_horizons(data))
    qualification_strip = metric_strip([
        ("Qualification cases", cases["qualification"], f"of {cases['required']} required", cases["status"]),
        ("Frozen scope", cases["frozen"], "historical gate scope", None),
        ("Current audit", cases["current"], cases.get("current_cutoff") or "strict independent units", None),
        ("Manual review", cases["manual_review"], "no machine approval", cases["manual_review"]),
    ])
    level4 = section(
        "Research readiness",
        "Horizons and gates",
        metric_strip([
            ("Historische Sicherheitsbefunde", data["security"]["status"], "Archiv", data["security"]["status"]),
            ("Historische Lückenbefunde", data["gaps"]["total_loaded"], "Archiv", None),
        ])
        + attention_row(cases["manual_review"], "Manual scientific review pending" if cases["manual_review"] == "PENDING HUMAN APPROVAL" else "Scientific review",
                        "Release gate from recorded evidence; separate from current runtime health.", cases["source"])
        + horizon_body
        + f"<div class='block-gap'>{qualification_strip}</div>"
        + f"<div class='block-gap'>{gate_summary}{gate_link}</div>",
        note="Research readiness is reported separately from runtime health. No directional signal, forecast or trading recommendation is generated.",
        meta=f"readiness gate {readiness['status']}",
    )

    evidence_strip = metric_strip([
        ("Last full test", audit["last_test"], _evidence_age(audit["last_test"]), audit["test_status"]),
        ("Test result", f"{audit['passed']} pass / {audit['failed']} fail", f"Commit {str(audit.get('deployed_commit') or UNAVAILABLE)[:7]}", None),
        ("Last incident", str((audit.get("last_incident") or {}).get("event", UNAVAILABLE)) if isinstance(audit.get("last_incident"), dict) else str(audit.get("last_incident", UNAVAILABLE)), "", None),
        ("Data spaces", str(len(data["datasets"])), "coverage rooms", None),
        ("Dashboard-Agent", (audit.get("dashboard_refresh") or {}).get("value", UNAVAILABLE),
         (audit.get("dashboard_refresh") or {}).get("note", ""), (audit.get("dashboard_refresh") or {}).get("status", UNAVAILABLE)),
    ])
    evidence = section(
        "Latest evidence",
        "Tests, incidents and datasets",
        evidence_strip
        + "<p class='cc-note'>Details: <a href='/gaps'>Incidents & Gaps →</a> · <a href='/data-quality'>Data Quality →</a> · <a href='/audit-evidence'>Audit & Evidence →</a></p>",
    )

    return (
        page_head("Operations Overview", "Immediate system health, active problems, pipeline state and research readiness from persisted evidence.", generated_at=data.get("generated_at_utc"))
        + level1 + status_strip + level2 + level3 + level4 + evidence
    )


def _security(data: dict[str, Any]) -> str:
    security = data["security"]
    rows = status_rows([
        ("Listener before hardening", "recorded listener state", security["listener_before"]["status"], _metric_value(security["listener_before"]), str(security["listener_before"]["source"])),
        ("Listener after hardening", "current binding evidence", security["listener_after"]["status"], _metric_value(security["listener_after"]), str(security["listener_after"]["source"])),
        ("LAN exposure", "external reachability test", security["lan_exposure"]["status"], _metric_value(security["lan_exposure"]), str(security["lan_exposure"]["source"])),
        ("HBA configuration", "host-based access rules", security["hba"]["status"], _metric_value(security["hba"]), str(security["hba"]["source"])),
        ("Credential rotation", "fail-closed migration evidence", security["credential_rotation"]["status"], _metric_value(security["credential_rotation"]), str(security["credential_rotation"]["source"])),
        ("Secret provider", "no secrets in UI or repo", security["secret_provider"]["status"], _metric_value(security["secret_provider"]), str(security["secret_provider"]["source"])),
        ("Dashboard binding", "loopback-only HTTP server", security["dashboard_binding"]["status"], _metric_value(security["dashboard_binding"]), str(security["dashboard_binding"]["source"])),
        ("OBSERVE mode", "mode of the running runtime", security["observe_only"]["status"], _metric_value(security["observe_only"]), "/api/state mode"),
        ("Trading actions", "executed trading actions", security["trading_actions"]["status"], _metric_value(security["trading_actions"]), str(security["trading_actions"]["source"])),
        ("Safe stop", "controlled shutdown test", security["safe_stop"]["status"], _metric_value(security["safe_stop"]), str(security["safe_stop"]["source"])),
    ])
    body = (
        page_head("Security", "Fail-closed state of the local operating boundary. Secrets are never rendered.", generated_at=data.get("generated_at_utc"))
        + section("Security gate", "Boundary status", rows, note="Missing or stale evidence stays UNAVAILABLE and is never interpreted as PASS.")
    )
    return body


def _runtime(data: dict[str, Any]) -> str:
    runtime = data["runtime"]

    def strip(*keys: str) -> str:
        return metric_strip([
            (key.replace("_", " "), runtime[key]["value"], runtime[key].get("unit"), runtime[key]["status"])
            for key in keys
        ])

    process = section("Process", "Runtime process", strip("processes", "uptime", "restarts", "watchdog"))
    queue = section("Queue & throughput", "Live event flow", strip("queue_depth", "queue_age", "receive_rate", "persist_rate"))
    integrity = section("Integrity counters", "Delivery quality", strip("drop_count", "duplicate_count", "late_count"))
    latency = section("Latency", "End-to-end timing", strip("source_to_store_latency", "event_loop_lag", "cursor_age"))
    storage = section("Storage", "Disk and logs", strip("disk", "logs"))
    cursor_detail = runtime.get("cursor") or {}
    cursor_rows = status_rows([
        ("Durable cursor", "persisted cursor record", runtime["cursor_age"]["status"], runtime["cursor_age"]["value"], str(runtime["cursor_age"]["source"])),
    ]) if not cursor_detail else ""
    collector = status_rows([
        ("Collector freshness", "live measurement", runtime["collector_freshness"]["status"], _metric_value(runtime["collector_freshness"]), str(runtime["collector_freshness"]["source"])),
    ])
    return (
        page_head("Runtime", "Real, source-bound measurements. Missing instrumentation stays visible as UNAVAILABLE.", generated_at=data.get("generated_at_utc"))
        + section("Live input", "Collector freshness", collector)
        + f"<div class='split'>{process}{queue}</div>"
        + f"<div class='split'>{integrity}{latency}</div>"
        + storage
        + (f"<div class='block-gap'>{cursor_rows}</div>" if cursor_rows else "")
    )


# A measured snapshot older than this no longer describes the current state.
STALE_SNAPSHOT_SECONDS = 48 * 3600


def _archive_reason(room: dict[str, Any], snapshot_end: Any = None) -> str | None:
    """Why an evidence room is old stock (finished, frozen, never approved), or None when current."""
    label = str(room.get("label", ""))
    status = str(room.get("status", "")).upper()
    if status.startswith("HISTORICAL") or label == "Frozen Live Capture":
        return "eingefroren: historisches Fenster, ändert sich nie"
    if "ABORTED" in status:
        return "abgebrochen: zählt nicht mehr"
    if "NOT APPROVED" in status:
        return "Kandidat: nie freigegeben"
    if status in ("", UNAVAILABLE) or room.get("coverage") == UNAVAILABLE:
        return "keine Daten: nichts erzeugt"
    if label == "Server-Bestandsaufnahme":
        age = _seconds_since(snapshot_end)
        if age is None or age > STALE_SNAPSHOT_SECONDS:
            return f"Stand {str(snapshot_end or UNAVAILABLE)[:10]}: seitdem nicht neu gemessen"
    return None


def _split_rooms(datasets: list[dict[str, Any]], snapshot_end: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current, archived = [], []
    for room in datasets:
        reason = _archive_reason(room, snapshot_end)
        if reason is None:
            current.append(room)
        else:
            archived.append({**room, "disposition": f"Altbestand · {reason}" + (f" · {room['disposition']}" if room.get("disposition") else "")})
    return current, archived


def _data_quality(data: dict[str, Any]) -> str:
    gaps = data["gaps"]
    snapshot = data.get("current_server_snapshot", {})
    current_panel = ""
    if snapshot.get("available"):
        current_panel = section(
            "Server-Bestandsaufnahme", "Gemessener Datenbestand",
            metric_strip([
                ("Fehlende Minuten", snapshot["missing_minutes"], "im gemessenen Zeitraum", None),
                ("Lückenbereiche", snapshot["gap_ranges"], "aktuelle Bestandsaufnahme", None),
                ("Fälle im Gesamtbestand", snapshot["strict_cases"], "strikte 30-Minuten-Fenster bis zum Cut-off", snapshot["case_status"]),
                ("Kontrollen", snapshot["controls"], "Negativ-/Neutralkontrollen", None),
                ("Menschliche Prüfung", snapshot["manual_review"], "eigene Freigabe erforderlich", snapshot["manual_review"]),
                ("Qualifizierung", "Nicht angerechnet", "separate Freigabe und Laufzeit erforderlich", None),
            ]),
            note=f"Abdeckung: {snapshot['start']} bis {snapshot['end']}. Fälle: gesamter persistierter Bestand bis zum Cut-off, einschließlich älterer Historie. Erfasst: {snapshot.get('captured_at') or UNAVAILABLE}. Keine V2- oder Handelsfreigabe.",
        )
    gap_strip = metric_strip([
        ("Open P0 gaps", gaps["p0"], "severity P0", "FAIL" if isinstance(gaps["p0"], int) and gaps["p0"] else "PASS"),
        ("Open P1 gaps", gaps["p1"], "severity P1", "FAIL" if isinstance(gaps["p1"], int) and gaps["p1"] else "PASS"),
        ("Loaded gap records", gaps["total_loaded"], f"bounded at {gaps['bounded_at']}", None),
        ("Gap evidence scope", "Server-Bestandsaufnahme" if gaps.get("purpose") == "CURRENT_STATE_NOT_QUALIFICATION" else gaps["scope"], "", None),
    ])
    current_rooms, archived_rooms = _split_rooms(data["datasets"], snapshot.get("end") if snapshot.get("available") else None)
    datasets = section(
        "Dataset coverage",
        "Aktuelle Evidenzräume",
        coverage_rows(current_rooms) if current_rooms else "<p class='empty'>Kein aktueller Evidenzraum.</p>",
        note="Nur Räume, die laufend gemessen werden. Jeder Raum behält sein eigenes Fenster und seine Quelle; Räume werden nie vermischt.",
        meta=f"{len(current_rooms)} aktuell · {len(archived_rooms)} Altbestand",
    )
    snapshot_stale = bool(snapshot.get("available")) and _archive_reason({"label": "Server-Bestandsaufnahme", "status": "MEASURED"}, snapshot.get("end")) is not None
    archive = ""
    if archived_rooms or (current_panel and snapshot_stale):
        archive = (
            "<details class='panel readiness'><summary>Altbestand anzeigen: "
            f"{len(archived_rooms)} abgeschlossene, eingefrorene oder nie freigegebene Räume"
            + (" und die alte Server-Bestandsaufnahme" if current_panel and snapshot_stale else "")
            + "</summary>"
            + (coverage_rows(archived_rooms) if archived_rooms else "")
            + (current_panel if snapshot_stale else "")
            + "<p class='count-scope'>Altbestand bleibt unverändert sichtbar, zählt aber nicht als aktueller Zustand.</p></details>"
        )
        if snapshot_stale:
            current_panel = ""
    freshness = status_rows([
        ("Collector freshness", "live pipeline measurement", data["runtime"]["collector_freshness"]["status"], _metric_value(data["runtime"]["collector_freshness"]), str(data["runtime"]["collector_freshness"]["source"])),
        ("Gap inventory", "persisted gap ledger", "MEASURED", f"{gaps['total_loaded']} rows", str(gaps["source"])),
    ])
    return (
        page_head("Data Quality", "Can the persisted data be trusted? Coverage, gaps and live freshness from separate evidence rooms.", generated_at=data.get("generated_at_utc"))
        + section("Live freshness", "Current pipeline state", freshness)
        + datasets
        + current_panel
        + section("Gap register", "Open data gaps", gap_strip,
                  note="Gap rows list cause, repairability and backfill status per window.")
        + "<p class='cc-note'>Full register with evidence: <a href='/gaps'>Incidents & Gaps →</a></p>"
        + archive
    )


def _incidents(data: dict[str, Any]) -> str:
    gaps = data["gaps"]
    audit = data["audit"]
    incidents = audit.get("incidents") or []
    incident_rows = "".join(
        "<tr>"
        f"<td class='mono'>{_safe(item.get('timestamp_utc') or item.get('timestamp') or item.get('ts') or UNAVAILABLE)}</td>"
        f"<td>{evidence_chip(item.get('severity') or 'WARN')}</td>"
        f"<td class='mono'>{_safe(item.get('event', UNAVAILABLE))}</td>"
        f"<td>{_safe(item.get('component_id', UNAVAILABLE))}</td>"
        f"<td>{_safe(item.get('reason_code') or item.get('summary') or UNAVAILABLE)}</td>"
        "</tr>"
        for item in incidents[:20]
    ) or "<tr><td colspan='5' class='empty'>No incident in the bounded timeline window.</td></tr>"
    gap_rows = []
    for item in gaps["rows"]:
        evidence = item["evidence"] if isinstance(item["evidence"], str) else ", ".join(str(value) for value in item["evidence"])
        if len(evidence) > 160:
            evidence = evidence[:157] + "…"
        gap_rows.append(
            "<tr>"
            f"<td class='mono'>{_safe(item['id'])}</td>"
            f"<td class='mono'>{_safe(item['start'])}<br><span class='muted'>→ {_safe(item['end'])}</span></td>"
            f"<td>{cell_state(item['priority'])}</td>"
            f"<td>{_safe(item['root_cause'])}<br><span class='muted'>{_safe(item['provenance'])}</span></td>"
            f"<td>{_safe(item['repairability'])}<br><span class='muted'>backfill: {_safe(item['backfill_candidate'])}</span></td>"
            f"<td>{cell_state(item['status'])}</td>"
            f"<td>{_safe(evidence)}</td></tr>"
        )
    gap_body = "".join(gap_rows) or "<tr><td colspan='9' class='empty'>No gap evidence available.</td></tr>"
    return (
        page_head("Incidents & Gaps", "Active and historical incidents plus the persisted data-gap register; diagnosis without reconstruction.", generated_at=data.get("generated_at_utc"))
        + section("Latest incident", "Most recent recorded incident", incident_card(audit.get("last_incident")),
                  note="Sourced from the bounded runtime timeline. Historical findings stay frozen and are not counted as current failures.")
        + f"<section class='panel'><div class='panel__head'><h2>Incident timeline</h2><span class='badge badge--snapshot'>BOUNDED · NEWEST FIRST</span></div>"
          "<div class='table-wrap'><table><caption>Incidents from the persisted runtime timeline</caption>"
          "<thead><tr><th>Timestamp UTC</th><th>Severity</th><th>Event</th><th>Component</th><th>Reason</th></tr></thead>"
          f"<tbody>{incident_rows}</tbody></table></div></section>"
        + f"<section class='panel'><div class='panel__head'><h2>Gap inventory</h2><span class='badge badge--yellow'>{gaps['total_loaded']} · {_safe(gaps['scope'])}</span></div>"
          "<div class='table-wrap'><table class='table--gaps'><caption>Persisted data gaps with cause and repair status</caption>"
          "<colgroup><col class='u-col-185'><col class='u-col-150'><col class='u-col-84'><col class='u-col-165'><col class='u-col-195'><col class='u-col-124'><col></colgroup>"
          "<thead><tr><th>ID</th><th>Window UTC</th><th>Priority</th><th>Root cause · Provenance</th><th>Repairability · Backfill</th><th>Status</th><th>Evidence</th></tr></thead>"
          + f"<tbody>{gap_body}</tbody></table></div><p class='count-scope'>Quelle: {_safe(gaps['source'])} · Antwort auf maximal {gaps['bounded_at']} Einträge begrenzt.</p></section>"
    )


def _qualification(data: dict[str, Any]) -> str:
    campaign = data["qualification"]
    strip = metric_strip([
        ("Campaign status", None, "", campaign["status"]),
        ("Campaign ID", campaign["campaign_id"], "preregistered identity", None),
        ("Preregistered at", _short_time(campaign["preregistered_at"]), "no retroactive definition", None),
        ("Started at", _short_time(campaign["started_at"]), "only after all technical gates", None),
        ("Tagesmanifeste", campaign.get("manifests_written", UNAVAILABLE),
         f"vorregistriertes Minimum {campaign.get('minimum_days', UNAVAILABLE)} Tage", None),
    ])
    return (
        page_head("Qualification", "Pre-registered prospective evidence space with immutable daily manifests.", generated_at=data.get("generated_at_utc"))
        + section("Campaign", "Qualification campaign", strip)
        + section(
            "Dataset coverage",
            "Separated evidence rooms",
            coverage_rows(data["datasets"]),
            note="The qualification campaign consumes only the approved dataset room; frozen and candidate rooms stay separate.",
        )
        + f"<section class='panel'><h2>Latest immutable daily manifest</h2><p class='mono'>{_safe(campaign['latest_manifest'])}</p>"
          f"<p class='count-scope'>Quelle: {_safe(campaign['source'])}</p></section>"
    )


def _cases(data: dict[str, Any]) -> str:
    cases = data["independent_cases"]
    strip = metric_strip([
        ("Frozen scope", cases["frozen"], "historical gate scope", None),
        ("Current audit", cases["current"], cases.get("current_cutoff") or "strict independent units", None),
        ("Qualification", cases["qualification"], f"of {cases['required']} required", cases["status"]),
        ("Negative / controls", cases["negative_controls"], "no synthetic additions", None),
    ])
    rows = status_rows([
        ("Gate status", "scientific gate", cases["status"], cases["status"], str(cases["source"])),
        ("Regime coverage", "pre-registered strata", None, cases["regime_coverage"], ""),
        ("Manual review", "real human verification required", cases["manual_review"], cases["manual_review"], ""),
        ("Human approval", "no self-approval by TIM", cases["human_approval"], cases["human_approval"], ""),
    ])
    return (
        page_head("Independent Cases", "Independent units, controls, regimes and human review for scientific qualification.", generated_at=data.get("generated_at_utc"))
        + section("Case counts", "Independent case scope", strip,
                  note=f"Current audit: {cases.get('current_source', cases['source'])}. A current-state count does not add qualification cases.")
        + section("Gate evidence", "Scientific gate state", rows)
        + "<section class='panel quick-links'><h2>Read-only research views</h2>"
          "<a href='/observations'>Observations</a><a href='/cases'>Research Cases</a><a href='/signals'>Signal Research</a>"
          "<a href='/analytics'>Analytics</a><a href='/insights'>Insights</a></section>"
    )


def _gate_bands(data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Read the operator-owned current gate model from the operations contract."""
    model = data.get("gate_model") or {}
    bands = model.get("bands")
    return bands if isinstance(bands, dict) else {}


def _gate_age_days(checked_at: Any) -> float | None:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    from datetime import timezone

    return max((datetime.now(timezone.utc) - parsed).total_seconds() / 86_400.0, 0.0)


def _gate_rows_from_model(gates: list[dict[str, Any]], stale_after_days: float) -> str:
    rows = []
    for gate in gates or []:
        if not isinstance(gate, dict):
            continue
        checked_at = gate.get("checked_at")
        age = _gate_age_days(checked_at)
        open_human_state = str(gate.get("status", "")).upper().replace("_", " ") in {
            "HUMAN ACTION REQUIRED", "PENDING HUMAN APPROVAL", "TIME GATE", "PENDING",
        }
        checkpoint = gate.get("checkpoint")
        checkpoint_html = ""
        checkpoint_fresh = False
        if isinstance(checkpoint, dict) and checkpoint.get("trades") is not None:
            checkpoint_html = (
                f"<span class='mono'>live checkpoint: {_safe(checkpoint.get('trades'))} trades · "
                f"{_safe(checkpoint.get('pages'))} pages · state {_safe(checkpoint.get('checkpoint_mtime'))}</span><br>"
            )
            from datetime import datetime, timezone

            try:
                checkpoint_age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(checkpoint.get("checkpoint_mtime")))).total_seconds()
                checkpoint_fresh = 0 <= checkpoint_age <= 3600
            except (TypeError, ValueError):
                checkpoint_fresh = False
        stale = (
            gate.get("status") not in (None, "NO_EVIDENCE")
            and not open_human_state
            and not checkpoint_fresh
            and age is not None
            and age > stale_after_days
        )
        evidence = gate.get("evidence")
        note_parts = [gate.get("note")] if gate.get("note") else []
        if evidence:
            note_parts.append(f"Evidence: {evidence}")
        if checked_at:
            note_parts.append(f"checked {checked_at}")
        note_html = "<br>".join(f"<small>{_safe(part)}</small>" for part in note_parts if part)
        status_chip = evidence_chip("STALE" if stale else gate.get("status"))
        if gate.get("status") in (None, "", "NO_EVIDENCE"):
            status_chip = evidence_chip("UNAVAILABLE", raw=gate.get("status") or UNAVAILABLE)
        stale_note = "<small>STALE — älter als das Aktualitätsfenster; nicht als aktueller Wert lesen.</small><br>" if stale else ""
        rows.append(
            "<div class='statusrow'>"
            f"<dt>{_safe(gate.get('id'))}{note_html}</dt>"
            f"<dd>{stale_note}{checkpoint_html if checkpoint_html else ''}</dd>"
            f"<dd class='statusrow__state'>{status_chip}</dd></div>"
        )
    return f"<dl class='statusrows'>{''.join(rows)}</dl>" if rows else (
        "<div class='attention attention--empty'>Gate model not loaded — every bound gate stays UNAVAILABLE until data/research/status/current_gate_model.json exists.</div>"
    )


def _readiness(data: dict[str, Any]) -> str:
    readiness = data["readiness"]
    horizons = _horizons(data)
    bands = _gate_bands(data)
    stale_after_days = float((data.get("gate_model") or {}).get("stale_after_days") or 14)
    archived = (data.get("gate_model") or {}).get("archived_snapshots") or []

    system_health = bands.get("system_health") or []
    runtime_rows = status_rows([
        ("Runtime process", "live operational health", data["live"].get("status") or UNAVAILABLE,
         f"status {data['live'].get('status', UNAVAILABLE)} · db {data['live'].get('database', UNAVAILABLE)} · stream {data['live'].get('stream', UNAVAILABLE)}",
         f"freshness {data['live'].get('data_age_seconds', UNAVAILABLE)}s · uptime {_duration_between(data['live'].get('runtime_started_at'), data['live'].get('checked_at'))}"),
    ])
    system_body = runtime_rows + _gate_rows_from_model(system_health, stale_after_days)

    trading_band = bands.get("trading") or []
    trading_value = data["security"]["trading_actions"]["value"]
    trading_substantiated = bool(data["security"]["trading_actions"].get("continuity"))
    if isinstance(trading_value, (int, float)) and trading_value > 0:
        trading_state = "FAIL"
    elif trading_value == 0 and trading_substantiated:
        trading_state = "PASS"
    else:
        trading_state = UNAVAILABLE
    trading_rows = status_rows([
        ("Mode", "running runtime mode", "PASS" if (data.get("mode") or "OBSERVE") == "OBSERVE" else "FAIL", data.get("mode") or UNAVAILABLE, "/api/state mode"),
        ("Trading actions", "executed trading actions across recorded evidence", trading_state, _metric_value(data["security"]["trading_actions"]), str(data["security"]["trading_actions"]["source"])),
    ]) + _gate_rows_from_model(trading_band, stale_after_days)

    governance_band = bands.get("governance") or []
    pending_human = [g for g in readiness["gates"] if "PENDING HUMAN" in str(g.get("status", "")).upper()]
    governance_body = _gate_rows_from_model(governance_band, stale_after_days)
    if pending_human:
        governance_body += (
            "<p class='cc-note'>Offene menschliche Freigaben (aus dem archivierten Snapshot, weiter unverändert): "
            + ", ".join(_safe(g.get("name") or g.get("id")) for g in pending_human)
            + ".</p>"
        )

    archived_note = "; ".join(
        f"{_safe(item.get('label') or item.get('id'))} {_safe(item.get('status'))} (frozen {_safe((item.get('frozen_at') or '')[:10])})"
        for item in archived if isinstance(item, dict)
    )
    archived_rows = gate_rows(readiness["gates"]) or "<div class='attention attention--empty'>No archived gate rows available.</div>"
    stale_callout = (
        "<div class='safety-callout safety-callout--info'><b>STALE:</b> "
        + (_safe(archived_note) if archived_note else "No archived snapshot registered.")
        + " Diese Werte beschreiben den Cut-off-Zustand vom 01.08.2026 und bleiben unverändert dokumentiert. Wo es heute eine Messung gibt, steht der aktuelle Wert unter „Heute“ direkt dabei.</div>"
    )
    return (
        page_head("V2 Readiness", "Current gate model first, archived governance snapshots explicitly labelled stale. PENDING HUMAN APPROVAL is a governance state, not a technical failure.", generated_at=data.get("generated_at_utc"))
        + section("Band 1 · System health", "Runtime, determinism, autonomy capability", system_body,
                  note="PASS requires evidence. Gates without a machine-readable source render UNAVAILABLE, never PASS.")
        + section("Band 2 · Data pipeline", "Data basis, quality scope, live ingestion, historical extension",
                  _gate_rows_from_model(bands.get("data_pipeline") or [], stale_after_days),
                  note="Current-collection quality and global legacy quality are reported separately and must not be merged.")
        + section("Band 3 · Research readiness", "SHORT · MID · LONG",
                  _gate_rows_from_model(bands.get("research_readiness") or [], stale_after_days)
                  + f"<div class='block-gap'>{horizon_panel(horizons)}</div>",
                  note="Horizon dimension detail below; per-horizon intelligence evidence stays NOT AVAILABLE until real evidence exists.")
        + section("Band 4 · Governance / human approval", "States that only humans can close", governance_body,
                  note="PENDING HUMAN APPROVAL and TIME GATE are expected governance states — shown blue, not red. No agent may self-approve.")
        + section("Band 5 · Trading authorization", "Execution path", trading_rows,
                  note="TRADING stays LOCKED until a human release authority signs the opposite; no UI element can change this.")
        + section("Archived snapshots", "Frozen governance evidence — not current failures",
                  stale_callout
                  + f"<div class='block-gap'>{archived_rows}</div>",
                  note="Allowed snapshot gate states: PASS · FAIL · BLOCKED · PENDING HUMAN APPROVAL · TIME GATE · EXTERNAL ACTION REQUIRED.",
                  badge="<span class='sev sev--unknown'>STALE SNAPSHOT</span>")
    )


def _mcp(data: dict[str, Any]) -> str:
    mcp = data["mcp"]
    rows = status_rows([
        ("Secure MCP", "external support path", mcp["status"], mcp["status"], str(mcp["source"])),
        ("Support case", "UNAVAILABLE means no documented case", None, mcp["case_id"], ""),
        ("Workspace", "external state", None, mcp["workspace"], ""),
        ("Developer mode", "external state", None, mcp["developer_mode"], ""),
        ("Tunnel permissions", "read · manage · use checked separately", None, mcp["tunnel_permissions"], ""),
    ])
    return (
        page_head("Graphify & MCP", "Separate external support path; never part of the V2 core release gate.", generated_at=data.get("generated_at_utc"))
        + section("MCP status", "External integration", rows)
        + "<section class='panel safety-callout'><b>Separation:</b> the MCP status cannot override TIM security, data or science gates.</section>"
    )


def _audit(data: dict[str, Any]) -> str:
    audit = data["audit"]
    strip = metric_strip([
        ("Full suite", f"{audit['passed']} pass / {audit['failed']} fail", f"warnings: {audit['warnings']}", audit["test_status"]),
        ("Doctor", None, "repository diagnostics", audit["doctor"]),
        ("Validate", None, "repository contract", audit["validate"]),
        ("Protected state", None, "protected artifacts", audit["protected_state"]),
    ])
    source_rows = "".join(
        f"<tr><td class='mono'>{_safe(item['path'])}</td><td>{evidence_chip('PASS' if item['available'] else UNAVAILABLE)}</td><td>{_safe(item['scope'])}</td></tr>"
        for item in audit["sources"]
    ) or "<tr><td colspan='3' class='empty'>No completion evidence available.</td></tr>"
    incidents = audit.get("incidents") or []
    incident_links = "".join(
        f"<tr><td class='mono'>{_safe(item.get('timestamp_utc') or UNAVAILABLE)}</td><td>{evidence_chip(item.get('severity') or 'WARN')}</td>"
        f"<td class='mono'>{_safe(item.get('event', UNAVAILABLE))}</td><td>{_safe(item.get('component_id', UNAVAILABLE))}</td></tr>"
        for item in incidents[:10]
    ) or "<tr><td colspan='4' class='empty'>No incident in the bounded timeline window.</td></tr>"
    return (
        page_head("Audit & Evidence", "Tests, protected state, incidents and source-bound evidence for traceability.", generated_at=data.get("generated_at_utc"))
        + section("Last test run", "Test evidence", strip
                  + f"<p class='cc-note'>Last finished test: <span class='mono'>{_safe(audit['last_test'])}</span></p>")
        + section("Incidents", "Recorded incidents", incident_card(audit.get("last_incident"))
                  + f"<div class='table-wrap block-gap-sm'><table><caption>Bounded incident timeline</caption>"
                    "<thead><tr><th>Timestamp UTC</th><th>Severity</th><th>Event</th><th>Component</th></tr></thead>"
                    f"<tbody>{incident_links}</tbody></table></div>",
                  note="Every UI state traces to a source path listed below.")
        + "<section class='panel'><div class='table-wrap'><table><caption>Loaded read-only evidence sources</caption>"
          "<thead><tr><th>Source</th><th>Available</th><th>Scope</th></tr></thead>"
          f"<tbody>{source_rows}</tbody></table></div></section>"
    )


OPERATIONS_PAGES = {
    "Overview": _overview,
    "Security": _security,
    "Runtime": _runtime,
    "Data Quality": _data_quality,
    "Incidents & Gaps": _incidents,
    "Qualification": _qualification,
    "Independent Cases": _cases,
    "V2 Readiness": _readiness,
    "Graphify & MCP": _mcp,
    "Audit & Evidence": _audit,
}


def render_operations_page(page: str, data: dict[str, Any]) -> str:
    renderer = OPERATIONS_PAGES.get(page)
    if renderer is None:
        raise ValueError(f"unsupported operations page: {page}")
    return renderer(data)
