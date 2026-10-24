"""Evidence-driven evaluation of the prospective qualification start gates.

Every gate is judged from live, read-only evidence on the host that runs TIM (files written
by the runtime and its timers, PostgreSQL state, systemd or launchd state, git state). Nothing here starts
the campaign, writes to the database or changes the runtime. A gate passes only when its
evidence is present, fresh and explicit; anything missing or unreadable is PENDING or FAIL.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.v2_completion.qualification import REQUIRED_START_GATES

UTC = timezone.utc
SCHEMA_VERSION = "1.0.0"
OPEN_OUTBOX_STATES = ("PENDING", "PROCESSING", "RETRY")
MAX_OPEN_OUTBOX = 50_000
FRESH_STATUS = timedelta(minutes=10)
FRESH_CURSOR = timedelta(minutes=5)
MAX_SAFE_STOP_AGE = timedelta(days=14)
MAX_LOGROTATE_AGE = timedelta(hours=26)


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    evidence: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "evidence": self.evidence, "reasons": list(self.reasons)}


def _gate(name: str, reasons: list[str], evidence: dict[str, Any], *, missing: bool = False) -> GateResult:
    if not reasons:
        return GateResult(name, "PASS", evidence)
    return GateResult(name, "PENDING" if missing else "FAIL", evidence, tuple(reasons))


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _fresh(stamp: Any, now: datetime, limit: timedelta) -> bool:
    parsed = parse_time(stamp)
    return parsed is not None and timedelta(0) - timedelta(minutes=1) <= now - parsed <= limit


def listener_addresses(ss_output: str, port: int = 5432) -> list[str]:
    """Local addresses listening on ``port`` from ``ss -ltnH`` output."""
    addresses = []
    for line in ss_output.splitlines():
        parts = line.split()
        local = next((part for part in parts if part.endswith(f":{port}")), None)
        if local is None:
            continue
        host = local[: -len(f":{port}")].strip("[]")
        addresses.append(host.split("%", 1)[0])
    return addresses


def _is_loopback(host: str) -> bool:
    if host in {"localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_postgresql_security(ss_output: str | None, listen_addresses: str | None, *, port: int = 5432) -> GateResult:
    evidence: dict[str, Any] = {"listen_addresses_setting": listen_addresses}
    if ss_output is None:
        return _gate("postgresql_security", ["socket listing unavailable"], evidence, missing=True)
    hosts = listener_addresses(ss_output, port)
    evidence["listeners"] = hosts
    reasons = []
    if not hosts:
        reasons.append(f"no PostgreSQL listener found on port {port}")
    reasons += [f"non-loopback listener {host}" for host in hosts if not _is_loopback(host)]
    if listen_addresses is not None:
        configured = [item.strip() for item in listen_addresses.split(",") if item.strip()]
        reasons += [f"listen_addresses contains {item}" for item in configured if not _is_loopback(item)]
    return _gate("postgresql_security", reasons, evidence)


def check_postgresql_reachability(listen_addresses: str | None, probes: dict[str, bool] | None,
                                  *, port: int) -> GateResult:
    """macOS variant: PostgreSQL runs as another user, so its sockets are not listable.

    Evidence is the server's own listen_addresses plus a TCP connect to the database
    port on every non-loopback address of this machine; each connect must be refused.
    """
    evidence: dict[str, Any] = {"listen_addresses_setting": listen_addresses, "port": port, "probes": probes}
    if listen_addresses is None or probes is None:
        return _gate("postgresql_security", ["listen_addresses or interface probes unavailable"], evidence,
                     missing=True)
    configured = [item.strip() for item in listen_addresses.split(",") if item.strip()]
    reasons = [f"listen_addresses contains {item}" for item in configured if not _is_loopback(item)]
    if not configured:
        reasons.append("listen_addresses is empty")
    reasons += [f"PostgreSQL reachable on {host}:{port}" for host, reachable in sorted(probes.items()) if reachable]
    return _gate("postgresql_security", reasons, evidence)


def check_safe_stop(stop: dict[str, Any] | None, start: dict[str, Any] | None, now: datetime) -> GateResult:
    if stop is None or start is None:
        return _gate("safe_stop", ["last_safe_stop.json or last_safe_start.json missing"], {}, missing=True)
    checkpoint = stop.get("durable_ingestion_checkpoint") or {}
    evidence = {"stop_completed_at": stop.get("completed_at"), "start_completed_at": start.get("completed_at")}
    reasons = []
    if stop.get("status") != "PASS" or start.get("status") != "PASS":
        reasons.append("last safe stop/start not PASS")
    if stop.get("trading_actions") != 0 or start.get("trading_actions") != 0:
        reasons.append("trading actions recorded around safe stop")
    if stop.get("cursor") != "HASH_AND_VERSION_VALIDATED" or checkpoint.get("checkpoint_safe") is not True:
        reasons.append("cursor/checkpoint not validated at safe stop")
    if checkpoint.get("processing") not in (0, None):
        reasons.append("outbox still processing at safe stop")
    stopped, started = parse_time(stop.get("completed_at")), parse_time(start.get("completed_at"))
    if stopped is None or started is None or started < stopped:
        reasons.append("safe start does not follow the safe stop")
    elif now - stopped > MAX_SAFE_STOP_AGE:
        reasons.append("last safe stop older than 14 days")
    return _gate("safe_stop", reasons, evidence)


def check_durable_cursor(cursor: dict[str, Any] | None, now: datetime) -> GateResult:
    if cursor is None:
        return _gate("durable_cursor", ["no durable cursor row"], {}, missing=True)
    evidence = {key: str(cursor.get(key)) for key in ("cursor_version", "recovery_state", "last_persisted_at")}
    reasons = []
    if cursor.get("recovery_state") != "NORMAL":
        reasons.append(f"recovery_state {cursor.get('recovery_state')}")
    persisted = cursor.get("last_persisted_at")
    if not isinstance(persisted, datetime) or now - persisted.astimezone(UTC) > FRESH_CURSOR:
        reasons.append("cursor not persisted within 5 minutes")
    if not cursor.get("cursor_hash"):
        reasons.append("cursor hash missing")
    return _gate("durable_cursor", reasons, evidence)


def check_durable_outbox(counts: dict[str, int] | None) -> GateResult:
    if counts is None:
        return _gate("durable_outbox", ["outbox counts unavailable"], {}, missing=True)
    evidence = {"by_status": counts, "deferred_note": "DEFERRED is historical recovery work, reported, not counted as done"}
    reasons = []
    if counts.get("QUARANTINED", 0):
        reasons.append(f"{counts['QUARANTINED']} quarantined outbox rows")
    open_rows = sum(counts.get(state, 0) for state in OPEN_OUTBOX_STATES)
    if open_rows > MAX_OPEN_OUTBOX:
        reasons.append(f"open outbox backlog {open_rows} above {MAX_OPEN_OUTBOX}")
    return _gate("durable_outbox", reasons, evidence)


def check_durable_ingestion(open_gaps: int | None, liveness: dict[str, Any] | None, now: datetime) -> GateResult:
    if open_gaps is None or liveness is None:
        return _gate("durable_ingestion", ["gap incidents or rolling liveness unavailable"], {}, missing=True)
    evidence = {"open_gap_incidents": open_gaps, "liveness_computed_at": liveness.get("computed_at_utc"),
                "liveness_coverage": liveness.get("coverage_percent")}
    reasons = []
    if open_gaps:
        reasons.append(f"{open_gaps} open/catching-up gap incidents")
    if liveness.get("status") != "PASS" or not _fresh(liveness.get("computed_at_utc"), now, FRESH_STATUS):
        reasons.append("rolling 24h liveness not a fresh PASS")
    expected, valid = liveness.get("expected_observations"), liveness.get("valid_observations")
    if not isinstance(expected, int) or expected < 1440 or valid != expected:
        reasons.append("rolling liveness not complete over 1440 minutes")
    return _gate("durable_ingestion", reasons, evidence)


def check_watchdog(status: dict[str, Any] | None, unit_active: str | None, now: datetime) -> GateResult:
    evidence = {"unit_active": unit_active}
    if status is None:
        return _gate("watchdog", ["watchdog_status.json unreadable"], evidence, missing=True)
    stamp = status.get("checked_at") or status.get("timestamp") or status.get("updated_at")
    evidence.update({"status": status.get("status"), "checked_at": stamp})
    reasons = []
    if unit_active != "active":
        reasons.append("watchdog unit not active")
    if not _fresh(stamp, now, FRESH_STATUS):
        reasons.append("watchdog status not updated within 10 minutes")
    if str(status.get("status", "")).upper() not in {"PASS", "GREEN", "OK", "HEALTHY"}:
        reasons.append(f"watchdog status {status.get('status')}")
    return _gate("watchdog", reasons, evidence)


def check_log_rotation(timer_active: str | None, last_trigger: datetime | None, archives: list[str],
                       now: datetime) -> GateResult:
    evidence = {"logrotate_timer": timer_active, "last_trigger": last_trigger.isoformat() if last_trigger else None,
                "rotated_archives": len(archives)}
    reasons = []
    if timer_active != "active":
        reasons.append("logrotate.timer not active")
    if last_trigger is None or now - last_trigger > MAX_LOGROTATE_AGE:
        reasons.append("logrotate did not run within 26 hours")
    if not archives:
        reasons.append("no rotated operational log archives found")
    return _gate("log_rotation", reasons, evidence)


def check_log_rotation_in_process(archives: dict[str, datetime], oversized: list[str], now: datetime) -> GateResult:
    """macOS variant: TIM rotates its JSONL logs itself (StructuredLog), no logrotate.timer.

    Passes when a rotated archive was written within 26 hours and no operational log
    file has outgrown its bound.
    """
    newest = max(archives.values(), default=None)
    evidence = {"rotated_archives": len(archives), "newest_archive": newest.isoformat() if newest else None,
                "oversized_logs": oversized}
    reasons = []
    if newest is None:
        reasons.append("no rotated operational log archives found")
    elif now - newest > MAX_LOGROTATE_AGE:
        reasons.append("no log archive rotated within 26 hours")
    reasons += [f"log file {name} exceeds its size bound" for name in oversized]
    return _gate("log_rotation", reasons, evidence)


def check_observe_only(health: dict[str, Any] | None, liveness: dict[str, Any] | None) -> GateResult:
    if health is None or liveness is None:
        return _gate("observe_only", ["server_health.json or rolling_liveness.json missing"], {}, missing=True)
    evidence = {"mode": health.get("mode"), "health_trading_actions": health.get("trading_actions"),
                "liveness_trading_actions": liveness.get("trading_actions")}
    reasons = []
    if health.get("mode") != "OBSERVE":
        reasons.append(f"runtime mode {health.get('mode')}")
    if health.get("trading_actions") != 0 or liveness.get("trading_actions") != 0:
        reasons.append("non-zero trading actions")
    return _gate("observe_only", reasons, evidence)


def check_full_suite(head: str | None, suite_commit: str | None, suite_run: str | None) -> GateResult:
    evidence = {"head": head, "suite_commit": suite_commit, "suite_run": suite_run}
    if not suite_commit or not suite_run:
        return _gate("full_suite", ["no full-suite evidence supplied"], evidence, missing=True)
    reasons = [] if head and suite_commit == head else ["full suite evidence is for a different commit than HEAD"]
    return _gate("full_suite", reasons, evidence)


def check_frozen(head: str | None, dirty: list[str] | None, frozen_commit: str | None,
                 unit_drift: list[str] | None) -> GateResult:
    evidence = {"head": head, "frozen_commit": frozen_commit, "dirty_paths": dirty, "unit_drift": unit_drift}
    if not frozen_commit:
        return _gate("configuration_and_commit_frozen", ["no frozen commit declared"], evidence, missing=True)
    reasons = []
    if head != frozen_commit:
        reasons.append("server HEAD differs from the frozen commit")
    if dirty is None or dirty:
        reasons.append("server checkout has local changes or is unreadable")
    if unit_drift is None or unit_drift:
        reasons.append("installed service definitions differ from the repository")
    return _gate("configuration_and_commit_frozen", reasons, evidence)


def start_gate_report_hash(report: dict[str, Any]) -> str:
    """Existing report hash domain: sorted JSON, omitting only report_sha256."""
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def summarize(results: list[GateResult], *, now: datetime, context: dict[str, Any]) -> dict[str, Any]:
    names = [result.name for result in results]
    if sorted(names) != sorted(REQUIRED_START_GATES):
        raise ValueError("start-gate results must cover every required gate exactly once")
    blockers = [result.name for result in results if result.status != "PASS"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "kind": "V2_QUALIFICATION_START_GATE_EVALUATION",
        "evaluated_at_utc": now.isoformat(),
        "mode": "READ_ONLY",
        "trading_actions": 0,
        "all_start_gates_pass": not blockers,
        "blocking_start_gates": blockers,
        "campaign_started": False,
        "note": "Passing gates allow an explicit, human-approved start action; they never start the campaign.",
        "context": context,
        "gates": [result.to_dict() for result in results],
    }
    report["report_sha256"] = start_gate_report_hash(report)
    return report
