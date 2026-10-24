"""Canonical independent-unit and manual scientific review contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any, Iterable


UTC = timezone.utc
REQUIRED_DURATION = timedelta(minutes=30)
ALLOWED_SAMPLE_CLASSES = {"POSITIVE", "NEGATIVE", "NEUTRAL_CONTROL"}


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("canonical-unit timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class CanonicalIndependentUnit:
    unit_id: str
    start_utc: datetime
    end_utc: datetime
    source_window: str
    data_complete: bool
    gap_exposure: bool
    observation_id: str | None
    label: str
    sample_class: str
    volatility_regime: str
    liquidity_regime: str
    session: str
    weekday: str
    trend_regime: str
    reviewer_id: str | None
    provenance: str
    input_hash: str

    def __post_init__(self) -> None:
        if self.start_utc.tzinfo is None or self.end_utc.tzinfo is None:
            raise ValueError("canonical-unit timestamps must be timezone-aware")
        if self.end_utc - self.start_utc != REQUIRED_DURATION:
            raise ValueError("canonical independent unit must span exactly 30 minutes")
        if self.sample_class not in ALLOWED_SAMPLE_CLASSES:
            raise ValueError("invalid scientific sample class")
        if len(self.input_hash) != 64:
            raise ValueError("canonical unit input hash must be SHA-256")

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "start_utc": iso(self.start_utc),
            "end_utc": iso(self.end_utc),
            "source_window": self.source_window,
            "data_complete": self.data_complete,
            "gap_exposure": self.gap_exposure,
            "observation_id": self.observation_id,
            "label": self.label,
            "sample_class": self.sample_class,
            "volatility_regime": self.volatility_regime,
            "liquidity_regime": self.liquidity_regime,
            "session": self.session,
            "weekday": self.weekday,
            "trend_regime": self.trend_regime,
            "reviewer_id": self.reviewer_id,
            "provenance": self.provenance,
            "input_hash": self.input_hash,
        }


def validate_independent_units(
    units: Iterable[CanonicalIndependentUnit],
) -> dict[str, Any]:
    values = sorted(units, key=lambda item: (item.start_utc, item.unit_id))
    duplicate_ids = len({item.unit_id for item in values}) != len(values)
    duplicate_inputs = len({item.input_hash for item in values}) != len(values)
    overlaps: list[dict[str, str]] = []
    for prior, current in zip(values, values[1:]):
        if current.start_utc < prior.end_utc:
            overlaps.append({"left": prior.unit_id, "right": current.unit_id})
    invalid_quality = [
        item.unit_id
        for item in values
        if not item.data_complete or item.gap_exposure or not item.provenance
    ]
    class_counts = {
        name: sum(item.sample_class == name for item in values)
        for name in sorted(ALLOWED_SAMPLE_CLASSES)
    }
    passed = not duplicate_ids and not duplicate_inputs and not overlaps and not invalid_quality
    return {
        "unit_count": len(values),
        "duplicate_unit_ids": duplicate_ids,
        "duplicate_input_hashes": duplicate_inputs,
        "overlaps": overlaps,
        "invalid_quality_unit_ids": invalid_quality,
        "sample_class_counts": class_counts,
        "gate_status": "PASS" if passed else "FAIL",
    }


def build_completion_audit(
    *, baseline: dict[str, Any], preregistration: dict[str, Any]
) -> dict[str, Any]:
    cases = baseline["scientific_case_audit"]
    frozen = cases["frozen_cutoff_audit"]
    current = cases["current_cutoff_audit"]
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "audit_method": "STRICT_30M_NON_OVERLAPPING_QUALITY_SCREEN_V1",
        "canonical_independent_unit": {
            "start": "UTC_TIMEZONE_AWARE",
            "end": "START_PLUS_PT30M",
            "non_overlap": "NEXT_START_GREATER_THAN_OR_EQUAL_PRIOR_END",
            "source_window": "BINANCE_SPOT_BTCUSDT_PUBLIC_AGGTRADES",
            "data_completeness": "EVERY_EXPECTED_SOURCE_BACKED_MINUTE_PRESENT",
            "gap_exposure": "MUST_BE_FALSE",
            "observation_id": "REQUIRED_FOR_POSITIVE_LABELS_NULL_ALLOWED_FOR_CONTROLS",
            "label": "PRE_REGISTERED_CLASS_ONLY",
            "sample_class": sorted(ALLOWED_SAMPLE_CLASSES),
            "regime": ["volatility", "liquidity", "session", "weekday", "trend_or_range"],
            "reviewer": "REAL_ID_REQUIRED_FOR_HUMAN_GATE",
            "provenance": "HASH_BOUND_PUBLIC_SOURCE_AND_SOFTWARE_VERSION",
        },
        "frozen": {
            "raw_complete_labels": frozen["raw_complete_validation_rows"],
            "quality_eligible_labels": frozen["quality_eligible_labels"],
            "unique_source_windows": frozen["quality_eligible_underlying_windows"],
            "strict_independent_units": frozen["strict_independent_30m_windows"],
            "required_units": frozen["required_independent_cases"],
            "audit_hash": frozen["audit_hash"],
            "gate_status": frozen["gate_status"],
        },
        "current": {
            "cutoff_utc": cases["current_cutoff_utc"],
            "raw_complete_labels": current["raw_complete_validation_rows"],
            "quality_eligible_labels": current["quality_eligible_labels"],
            "unique_source_windows": current["quality_eligible_underlying_windows"],
            "strict_independent_units": current["strict_independent_30m_windows"],
            "required_units": current["required_independent_cases"],
            "audit_hash": current["audit_hash"],
            "gate_status": current["gate_status"],
        },
        "qualification": {
            "dataset_id": preregistration["dataset_id"],
            "campaign_status": preregistration["campaign_status"],
            "strict_independent_units": 0,
            "required_units": preregistration["case_target"],
            "gate_status": "TIME_GATE_NOT_STARTED",
        },
        "sampling_requirements": {
            "non_overlap": True,
            "near_duplicate_input_hashes_prohibited": True,
            "time_blocked": True,
            "required_classes": sorted(ALLOWED_SAMPLE_CLASSES),
            "required_strata": [
                "volatility_regime",
                "liquidity_regime",
                "utc_session",
                "weekday",
                "trend_or_range_if_preregistered",
            ],
            "cherry_picking_prohibited": True,
        },
        "frozen_negative_or_control_sampling": frozen["negative_or_control_sampling"],
        "current_negative_or_control_sampling": current["negative_or_control_sampling"],
        "manual_review_status": "PENDING_REAL_HUMAN_REVIEW",
        "human_approval": False,
        "scientific_gate": "FAIL",
        "scientific_gate_reasons": [
            "qualification_independent_units_below_1000",
            "qualification_campaign_not_started",
            "negative_and_neutral_controls_not_yet_collected",
            "real_human_review_absent",
            "real_human_approval_absent",
        ],
    }
    payload["audit_hash"] = stable_hash(payload)
    return payload


def build_review_workbook(sample_manifest: dict[str, Any]) -> dict[str, Any]:
    cases = []
    for selected in sample_manifest.get("selected_cases", []):
        cases.append(
            {
                "selection_rank": selected["selection_rank"],
                "observation_id": selected["observation_id"],
                "case_id": selected["case_id"],
                "source_window_signature": selected["source_window_signature"],
                "observed_at_utc": selected["observed_at_utc"],
                "validated_through_utc": selected["validated_through_utc"],
                "observation_kind": selected["observation_kind"],
                "persisted_outcome": selected["outcome"],
                "input_hash": selected["input_hash"],
                "validation_hash": selected["validation_hash"],
                "review": {
                    "reviewer_id": None,
                    "reviewed_at_utc": None,
                    "data_quality": None,
                    "observation_correct": None,
                    "label_correct": None,
                    "future_information_absent": None,
                    "narrative_adjustment_absent": None,
                    "confidence_0_to_1": None,
                    "decision": None,
                    "exclusion_reason": None,
                    "rationale": None,
                    "inter_rater_conflict": None,
                    "conflict_resolution": None,
                },
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "packet_status": "AUTOMATED_SELECTION_COMPLETE_PENDING_REAL_HUMAN_REVIEW",
        "source_sample_hash": sample_manifest.get("sample_hash"),
        "source_manifest_hash": sample_manifest.get("manifest_hash"),
        "selected_cases": cases,
        "selected_count": len(cases),
        "human_decisions_recorded": 0,
        "approval": False,
        "reviewer_signature": None,
        "release_authority_signature": None,
    }
    payload["workbook_hash"] = stable_hash(payload)
    return payload


def validate_review_workbook(workbook: dict[str, Any]) -> dict[str, Any]:
    decisions = 0
    invalid_partial = []
    for item in workbook.get("selected_cases", []):
        review = item.get("review", {})
        populated = [value for value in review.values() if value not in (None, "")]
        if populated:
            required = (
                "reviewer_id",
                "reviewed_at_utc",
                "data_quality",
                "observation_correct",
                "label_correct",
                "future_information_absent",
                "narrative_adjustment_absent",
                "confidence_0_to_1",
                "decision",
                "rationale",
                "inter_rater_conflict",
            )
            if any(review.get(name) in (None, "") for name in required):
                invalid_partial.append(item.get("observation_id"))
            else:
                decisions += 1
    return {
        "selected_count": len(workbook.get("selected_cases", [])),
        "complete_human_decisions": decisions,
        "invalid_partial_reviews": invalid_partial,
        "approval": bool(workbook.get("approval", False)),
        "status": (
            "PASS"
            if decisions > 0
            and decisions == len(workbook.get("selected_cases", []))
            and not invalid_partial
            and workbook.get("approval") is True
            else "PENDING_OR_FAIL"
        ),
    }


# --------------------------------------------------------------------------------------
# T04 extension (2026-10-22): completeness, approval and authorization are three separate
# findings, and every attestation is bound to the exact content it was given for.
# `validate_review_workbook` above stays unchanged (completeness of the case rows plus the
# supplied approval flag). `validate_review_packet` adds typed decisions, contradiction
# checks, source binding and hash-bound signatures. A signature here is a recorded
# attestation (who, when, over which content hash), not a cryptographic proof.
# --------------------------------------------------------------------------------------

REVIEW_DECISIONS = ("ACCEPT", "REJECT", "EXCLUDE")
REVIEW_BOOLEAN_FIELDS = (
    "observation_correct",
    "label_correct",
    "future_information_absent",
    "narrative_adjustment_absent",
)
REVIEW_REQUIRED_FIELDS = (
    "reviewer_id",
    "reviewed_at_utc",
    "data_quality",
    *REVIEW_BOOLEAN_FIELDS,
    "confidence_0_to_1",
    "decision",
    "rationale",
    "inter_rater_conflict",
)
SIGNATURE_ROLES = {"reviewer_signature": "reviewer", "release_authority_signature": "release_authority"}
CONTENT_HASH_EXCLUDED = ("workbook_hash", "reviewer_signature", "release_authority_signature", "approval")


def review_content_hash(workbook: dict[str, Any]) -> str:
    """Hash of what a signature attests: the case rows with their decisions and the source
    references. The approval flag, the legacy `workbook_hash` and the signatures themselves are
    excluded, so a signature cannot be re-used for a workbook whose decisions changed."""
    return stable_hash({key: value for key, value in workbook.items() if key not in CONTENT_HASH_EXCLUDED})


def _is_bool(value: Any) -> bool:
    return isinstance(value, bool)


def _check_review_row(item: dict[str, Any]) -> tuple[str, list[str]]:
    """Return (state, problems). state: EMPTY, COMPLETE, INVALID."""
    review = item.get("review")
    if not isinstance(review, dict):
        return "INVALID", ["review is not an object"]
    populated = [k for k, v in review.items() if v not in (None, "")]
    if not populated:
        return "EMPTY", []
    problems: list[str] = []
    missing = [name for name in REVIEW_REQUIRED_FIELDS if review.get(name) in (None, "")]
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
        return "INVALID", problems
    if not isinstance(review["reviewer_id"], str):
        problems.append("reviewer_id must be a string")
    try:
        parse_time(str(review["reviewed_at_utc"]))
    except (ValueError, TypeError):
        problems.append("reviewed_at_utc must be a timezone-aware ISO timestamp")
    for name in (*REVIEW_BOOLEAN_FIELDS, "inter_rater_conflict"):
        if not _is_bool(review[name]):
            problems.append(f"{name} must be true or false, not {review[name]!r}")
    confidence = review["confidence_0_to_1"]
    if _is_bool(confidence) or not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        problems.append("confidence_0_to_1 must be a number between 0 and 1")
    decision = review["decision"]
    if decision not in REVIEW_DECISIONS:
        problems.append(f"decision must be one of {REVIEW_DECISIONS}, not {decision!r}")
    elif all(_is_bool(review[name]) for name in REVIEW_BOOLEAN_FIELDS):
        flags = [review[name] for name in REVIEW_BOOLEAN_FIELDS]
        if decision == "ACCEPT" and not all(flags):
            problems.append("ACCEPT contradicts a false quality flag")
        if decision == "REJECT" and all(flags):
            problems.append("REJECT without any false quality flag")
        if decision == "EXCLUDE" and review.get("exclusion_reason") in (None, ""):
            problems.append("EXCLUDE requires exclusion_reason")
    if review.get("inter_rater_conflict") is True and review.get("conflict_resolution") in (None, ""):
        problems.append("inter_rater_conflict requires conflict_resolution")
    return ("INVALID" if problems else "COMPLETE"), problems


def _check_signature(workbook: dict[str, Any], field: str, content_hash: str) -> tuple[bool, list[str], str | None]:
    signature = workbook.get(field)
    if signature in (None, ""):
        return False, [f"{field} missing"], None
    if not isinstance(signature, dict):
        return False, [f"{field} must be an object"], None
    problems: list[str] = []
    signer = signature.get("signer_id")
    if not isinstance(signer, str) or not signer.strip():
        problems.append(f"{field}.signer_id missing")
    if signature.get("role") != SIGNATURE_ROLES[field]:
        problems.append(f"{field}.role must be {SIGNATURE_ROLES[field]!r}")
    try:
        parse_time(str(signature.get("signed_at_utc")))
    except (ValueError, TypeError):
        problems.append(f"{field}.signed_at_utc must be a timezone-aware ISO timestamp")
    if signature.get("bound_content_hash") != content_hash:
        problems.append(f"{field}.bound_content_hash does not match the review content")
    return (not problems), problems, (signer if isinstance(signer, str) else None)


def validate_review_packet(
    workbook: dict[str, Any], source_sample: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Three separate findings for a manual review workbook.

    completeness: every selected case carries one complete, typed, non-contradictory decision.
    approval:     the supplied `approval` flag, reported, never inferred.
    authorization: reviewer and release-authority signatures exist, are bound to the current
                   review content hash, name distinct persons, and the release authority is not
                   one of the reviewers.
    source_binding (when `source_sample` is given): the workbook references the sample's hash
                   and each case row matches the sample row by observation id, input hash and
                   validation hash.

    `verdict` is REVIEW_AUTHORIZED only if completeness is PASS, approval is true, authorization
    is AUTHORIZED and source binding is not MISMATCH. Nothing here authenticates a person; it
    records who claimed what over which bytes, so a later change is detectable."""
    cases = workbook.get("selected_cases", [])
    if not isinstance(cases, list):
        cases = []
    complete, empty, invalid = 0, 0, []
    decisions = {name: 0 for name in REVIEW_DECISIONS}
    reviewers: set[str] = set()
    for item in cases:
        state, problems = _check_review_row(item if isinstance(item, dict) else {})
        if state == "COMPLETE":
            complete += 1
            decisions[item["review"]["decision"]] += 1
            reviewers.add(item["review"]["reviewer_id"])
        elif state == "EMPTY":
            empty += 1
        else:
            invalid.append({"observation_id": item.get("observation_id") if isinstance(item, dict) else None,
                            "problems": problems})
    completeness = "PASS" if cases and complete == len(cases) and not invalid else "PENDING_OR_FAIL"

    approval_flag = workbook.get("approval", False)
    approval = approval_flag is True

    content_hash = review_content_hash(workbook)
    problems: list[str] = []
    signers: dict[str, str | None] = {}
    for field in SIGNATURE_ROLES:
        ok, field_problems, signer = _check_signature(workbook, field, content_hash)
        problems.extend(field_problems)
        signers[field] = signer
    reviewer_signer, authority_signer = signers["reviewer_signature"], signers["release_authority_signature"]
    if reviewer_signer and authority_signer and reviewer_signer == authority_signer:
        problems.append("release authority must not be the reviewer signer")
    if authority_signer and authority_signer in reviewers:
        problems.append("release authority must not have reviewed cases")
    authorization = "AUTHORIZED" if not problems else "NOT_AUTHORIZED"

    source_binding = "NOT_CHECKED"
    source_problems: list[str] = []
    if source_sample is not None:
        if workbook.get("source_sample_hash") != source_sample.get("sample_hash"):
            source_problems.append("source_sample_hash differs from the sample")
        by_id = {row.get("observation_id"): row for row in source_sample.get("selected_cases", [])}
        if len(by_id) != len(cases):
            source_problems.append(f"sample has {len(by_id)} cases, workbook {len(cases)}")
        for item in cases:
            if not isinstance(item, dict):
                continue
            row = by_id.get(item.get("observation_id"))
            if row is None:
                source_problems.append(f"{item.get('observation_id')} not in sample")
            elif (row.get("input_hash"), row.get("validation_hash"), row.get("outcome")) != (
                item.get("input_hash"), item.get("validation_hash"), item.get("persisted_outcome")
            ):
                source_problems.append(f"{item.get('observation_id')} differs from sample row")
        source_binding = "BOUND" if not source_problems else "MISMATCH"

    verdict = (
        "REVIEW_AUTHORIZED"
        if completeness == "PASS" and approval and authorization == "AUTHORIZED" and source_binding != "MISMATCH"
        else "NOT_AUTHORIZED"
    )
    return {
        "schema_version": workbook.get("schema_version"),
        "review_content_hash": content_hash,
        "selected_count": len(cases),
        "complete_human_decisions": complete,
        "empty_reviews": empty,
        "invalid_reviews": invalid,
        "decisions": decisions,
        "reviewers": sorted(reviewers),
        "completeness": completeness,
        "approval": approval,
        "approval_flag_type_ok": _is_bool(approval_flag),
        "authorization": authorization,
        "authorization_problems": problems,
        "source_binding": source_binding,
        "source_binding_problems": source_problems,
        "verdict": verdict,
    }
