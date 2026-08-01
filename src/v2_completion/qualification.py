"""Pre-registration and resumable evidence for the prospective V2 campaign."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


UTC = timezone.utc
DATASET_ID = "V2_PROSPECTIVE_QUALIFICATION_V1"
SCHEMA_VERSION = "1.0.0"
REQUIRED_INDEPENDENT_CASES = 1000
INDEPENDENCE_MINUTES = 30
TARGET_COVERAGE = 0.95
REQUIRED_START_GATES = (
    "postgresql_security",
    "safe_stop",
    "durable_ingestion",
    "durable_cursor",
    "durable_outbox",
    "watchdog",
    "log_rotation",
    "observe_only",
    "full_suite",
    "configuration_and_commit_frozen",
)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class StartGate:
    name: str
    status: str
    evidence: str

    def __post_init__(self) -> None:
        if self.name not in REQUIRED_START_GATES:
            raise ValueError(f"unknown qualification start gate: {self.name}")
        if self.status not in {"PASS", "FAIL", "BLOCKED", "PENDING"}:
            raise ValueError("start-gate status must be PASS, FAIL, BLOCKED or PENDING")
        if not self.evidence.strip():
            raise ValueError("start-gate evidence must be explicit")


def validate_start_gates(gates: list[StartGate]) -> tuple[bool, list[str]]:
    names = [gate.name for gate in gates]
    if len(names) != len(set(names)):
        raise ValueError("duplicate qualification start gate")
    missing = sorted(set(REQUIRED_START_GATES) - set(names))
    if missing:
        raise ValueError("missing qualification start gates: " + ", ".join(missing))
    blockers = [gate.name for gate in gates if gate.status != "PASS"]
    return not blockers, blockers


def campaign_duration(
    *, current_independent_cases: int,
    observed_minutes: int,
    required_cases: int = REQUIRED_INDEPENDENT_CASES,
) -> dict[str, Any]:
    mathematical_minutes = required_cases * INDEPENDENCE_MINUTES
    empirical_minutes_per_case: float | None = None
    if current_independent_cases > 0 and observed_minutes > 0:
        empirical_minutes_per_case = observed_minutes / current_independent_cases
    empirical_projection = (
        math.ceil(required_cases * empirical_minutes_per_case)
        if empirical_minutes_per_case is not None
        else mathematical_minutes
    )
    conservative = max(mathematical_minutes, empirical_projection)
    planned = math.ceil(conservative / 1440) * 1440
    return {
        "mathematical_lower_bound_minutes": mathematical_minutes,
        "mathematical_lower_bound_duration": str(timedelta(minutes=mathematical_minutes)),
        "empirical_reference_minutes_per_strict_unit": (
            round(empirical_minutes_per_case, 6)
            if empirical_minutes_per_case is not None
            else None
        ),
        "empirical_projection_minutes": empirical_projection,
        "pre_registered_minimum_minutes": planned,
        "pre_registered_minimum_days": planned // 1440,
        "rule": "MAX_1000_X_30M_NON_OVERLAP_AND_CURRENT_STRICT_UNIT_RATE_ROUNDED_UP_TO_FULL_UTC_DAY",
        "completion_still_requires": [
            "coverage_at_least_95_percent",
            "1000_quality_valid_non_overlapping_units",
            "negative_and_neutral_controls",
            "required_regime_coverage",
            "replay_lookahead_leakage_and_determinism_pass",
            "real_human_review_and_approval",
        ],
    }


def build_preregistration(
    *,
    gates: list[StartGate],
    software_commit: str,
    configuration_hash: str,
    current_independent_cases: int,
    observed_minutes: int,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    gate_pass, blockers = validate_start_gates(gates)
    generated = generated_at or datetime.now(UTC)
    duration = campaign_duration(
        current_independent_cases=current_independent_cases,
        observed_minutes=observed_minutes,
    )
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "generated_at_utc": iso(generated),
        "campaign_status": (
            "ELIGIBLE_TO_START_EXPLICIT_START_ACTION_REQUIRED"
            if gate_pass
            else "NOT_STARTED_START_GATE_BLOCKED"
        ),
        "start_utc": None,
        "expected_end_utc": None,
        "retrospective_start_prohibited": True,
        "symbol": "BTCUSDT",
        "market": "BINANCE_SPOT",
        "data_type": "PUBLIC_AGGTRADES_DERIVED_CLOSED_1M_AND_CANONICAL_CASE_UNITS",
        "frequency": "PT1M",
        "coverage_target": TARGET_COVERAGE,
        "case_target": REQUIRED_INDEPENDENT_CASES,
        "independent_unit": "STRICT_NON_OVERLAPPING_PT30M_SOURCE_WINDOW_V1",
        "gap_rules": {
            "missing_minute": "EXPECTED_CLOSED_1M_WITHOUT_VALID_SOURCE_BACKED_CANDLE",
            "no_fill": ["synthetic", "interpolation", "forward_fill", "cross_market_substitution"],
            "incident_required": True,
        },
        "exclusion_rules": [
            "incomplete_5_15_30_minute_horizons",
            "source_gap_overlap",
            "missing_or_non_closed_case",
            "case_outcome_mismatch",
            "incomplete_provenance",
            "duplicate_or_near_duplicate_source_window",
            "look_ahead_or_leakage_detected",
        ],
        "quality_rules": [
            "public_binance_spot_source_only",
            "transactionally_persisted_raw_event_cursor_and_outbox",
            "deterministic_hash_bound_inputs_and_outputs",
            "positive_negative_and_neutral_control_sampling",
            "volatility_liquidity_session_weekday_regime_strata",
        ],
        "software_commit": software_commit,
        "configuration_hash": configuration_hash,
        "dataset_schema_version": SCHEMA_VERSION,
        "abort_conditions": [
            "postgresql_lan_exposure",
            "observe_only_violation",
            "trading_action_count_nonzero",
            "unrecoverable_cursor_or_outbox_integrity_failure",
            "unbounded_or_silent_queue_loss",
            "protected_state_change",
        ],
        "restart_rules": [
            "use_scripts_timctl_only",
            "persist_cursor_and_checkpoint_before_stop",
            "resume_open_outbox_before_live_ingress",
            "catch_up_public_data_before_live_continuation",
            "append_incident_and_daily_manifest",
        ],
        "reviewer_requirements": {
            "minimum_reviewers": 2,
            "reviewer_identity_required": True,
            "timestamp_and_rationale_required": True,
            "inter_rater_conflict_resolution_required": True,
            "release_authority_signature_required": True,
            "automated_signature_prohibited": True,
        },
        "duration": duration,
        "start_gates": [
            {"name": gate.name, "status": gate.status, "evidence": gate.evidence}
            for gate in gates
        ],
        "blocking_start_gates": blockers,
        "daily_manifest_policy": "ONE_IMMUTABLE_MANIFEST_PER_UTC_DAY_AFTER_REAL_START",
        "daily_manifests_written": 0,
        "readiness_counted": False,
        "human_approval": False,
        "trading_approved": False,
    }
    payload["preregistration_hash"] = stable_hash(payload)
    return payload


def activate_campaign(
    preregistration: dict[str, Any], *, start: datetime, actual_commit: str
) -> dict[str, Any]:
    if preregistration.get("campaign_status") != "ELIGIBLE_TO_START_EXPLICIT_START_ACTION_REQUIRED":
        raise RuntimeError("qualification campaign cannot start while any start gate is not PASS")
    if preregistration.get("blocking_start_gates"):
        raise RuntimeError("qualification campaign has blocking start gates")
    if start.tzinfo is None:
        raise ValueError("campaign start must be timezone-aware")
    if actual_commit != preregistration.get("software_commit"):
        raise RuntimeError("campaign software commit differs from pre-registration")
    value = dict(preregistration)
    value["campaign_status"] = "ACTIVE"
    value["start_utc"] = iso(start)
    minutes = int(value["duration"]["pre_registered_minimum_minutes"])
    value["expected_end_utc"] = iso(start + timedelta(minutes=minutes))
    value["activated_at_utc"] = iso(datetime.now(UTC))
    value["readiness_counted"] = False
    value["preregistration_hash"] = stable_hash(
        {key: item for key, item in value.items() if key != "preregistration_hash"}
    )
    return value


def build_daily_manifest(
    preregistration: dict[str, Any], *, day: datetime, metrics: dict[str, Any]
) -> dict[str, Any]:
    if preregistration.get("campaign_status") != "ACTIVE":
        raise RuntimeError("daily qualification evidence requires an active campaign")
    if day.tzinfo is None:
        raise ValueError("manifest day must be timezone-aware")
    required = {
        "coverage",
        "gap_count",
        "case_count",
        "independent_case_count",
        "runtime_status",
        "security_status",
        "incident_ids",
    }
    missing = required - set(metrics)
    if missing:
        raise ValueError("daily metrics missing: " + ", ".join(sorted(missing)))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": DATASET_ID,
        "utc_date": day.astimezone(UTC).date().isoformat(),
        "generated_at_utc": iso(datetime.now(UTC)),
        "preregistration_hash": preregistration["preregistration_hash"],
        "software_commit": preregistration["software_commit"],
        "configuration_hash": preregistration["configuration_hash"],
        "metrics": metrics,
        "trading_actions": 0,
        "human_approval": False,
    }
    payload["manifest_hash"] = stable_hash(payload)
    return payload


def write_immutable_json(path: Path, payload: dict[str, Any]) -> str:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    if path.exists():
        if path.read_bytes() != encoded:
            raise FileExistsError(f"immutable manifest already exists with different content: {path}")
        return "UNCHANGED"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)
    return "CREATED"
