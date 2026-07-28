from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .models import ClaimRecord, ContradictionRecord
from .scanner import stable_id


CLAIM_TYPES = {
    "observed_fact",
    "validated_result",
    "research_observation",
    "model_inference",
    "agent_interpretation",
    "human_decision",
    "recommendation",
    "unknown",
}

CLAIM_PRIORITY = {
    "validated_result": 700,
    "observed_fact": 600,
    "human_decision": 500,
    "research_observation": 400,
    "agent_interpretation": 200,
    "model_inference": 100,
    "recommendation": 50,
    "unknown": 0,
}

STATUS_VALUES = {
    "complete": "complete",
    "completed": "complete",
    "done": "complete",
    "pass": "complete",
    "passed": "complete",
    "blocked": "blocked",
    "not complete": "not_complete",
    "not_complete": "not_complete",
    "incomplete": "not_complete",
    "in progress": "in_progress",
    "in_progress": "in_progress",
    "running": "in_progress",
    "pending": "pending",
    "failed": "failed",
    "fail": "failed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

INTERPRETATION_TYPES = {"model_inference", "agent_interpretation"}
EVIDENCE_TYPES = {
    "validated_result",
    "observed_fact",
    "human_decision",
    "research_observation",
}


def _identifier(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def _claim_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    return value


def _canonical_claim_value(predicate: str, value: Any) -> Any:
    if predicate == "status" and isinstance(value, str):
        return STATUS_VALUES.get(value.casefold().strip())
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.casefold().strip() in {"true", "false"}:
        return value.casefold().strip() == "true"
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _interval(claim: dict[str, Any]) -> tuple[datetime | None, datetime | None] | None:
    valid_at = _parse_time(claim.get("valid_at"))
    if valid_at is not None:
        return valid_at, valid_at
    start = _parse_time(claim.get("valid_from"))
    end = _parse_time(claim.get("valid_to"))
    if start is None and end is None:
        return None
    return start, end


def _temporal_relation(left: dict[str, Any], right: dict[str, Any]) -> tuple[bool, str]:
    left_interval = _interval(left)
    right_interval = _interval(right)
    if left_interval is None or right_interval is None:
        return True, "unknown"
    left_start, left_end = left_interval
    right_start, right_end = right_interval
    if left_end is not None and right_start is not None and left_end < right_start:
        return False, "non_overlapping"
    if right_end is not None and left_start is not None and right_end < left_start:
        return False, "non_overlapping"
    return True, "overlapping"


def _incompatible(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_method = left.get("measurement_method")
    right_method = right.get("measurement_method")
    if left_method and right_method and left_method != right_method:
        return False
    left_value = _canonical_claim_value(left["predicate"], left["value"])
    right_value = _canonical_claim_value(right["predicate"], right["value"])
    return left_value is not None and right_value is not None and left_value != right_value


def _claim_payload(raw: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any] | None:
    subject = _identifier(raw.get("subject", ""))
    predicate = _identifier(raw.get("predicate", ""))
    value = _claim_value(raw.get("value", raw.get("object")))
    raw_evidence_refs = raw.get("evidence_refs")
    if not isinstance(raw_evidence_refs, (list, tuple, set)):
        raw_evidence_refs = [artifact.get("artifact_id")]
    evidence_refs = tuple(
        sorted(
            {
                str(item)
                for item in raw_evidence_refs
                if item
            }
        )
    )
    if not subject or not predicate or value is None or not evidence_refs:
        return None
    claim_type = str(raw.get("claim_type", "unknown"))
    if claim_type not in CLAIM_TYPES:
        claim_type = "unknown"
    temporal = {
        "valid_at": raw.get("valid_at"),
        "valid_from": raw.get("valid_from"),
        "valid_to": raw.get("valid_to"),
    }
    superseded_by = raw.get("superseded_by")
    status = "superseded" if superseded_by or raw.get("status") == "superseded" else "active"
    identity = json.dumps(
        {
            "subject": subject,
            "predicate": predicate,
            "value": value,
            "claim_type": claim_type,
            "evidence_refs": evidence_refs,
            **temporal,
            "superseded_by": superseded_by,
            "measurement_method": raw.get("measurement_method"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    claim = ClaimRecord(
        claim_id=stable_id("claim", identity),
        subject=subject,
        predicate=predicate,
        object=value,
        claim_type=claim_type,
        status=status,
        evidence_refs=evidence_refs,
        freshness=str(raw.get("freshness", "unknown")),
        valid_at=temporal["valid_at"],
        valid_from=temporal["valid_from"],
        valid_to=temporal["valid_to"],
        superseded_by=str(superseded_by) if superseded_by else None,
        source_classification=artifact.get("classification"),
    ).to_dict()
    claim["value"] = claim.pop("object")
    claim["measurement_method"] = raw.get("measurement_method")
    return claim


def extract_claims(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for artifact in sorted(artifacts, key=lambda item: item.get("artifact_id", "")):
        metadata = artifact.get("metadata") or {}
        raw_claims = metadata.get("claims")
        if raw_claims is None and isinstance(metadata.get("claim"), dict):
            raw_claims = [metadata["claim"]]
        if not isinstance(raw_claims, list):
            continue
        for raw in raw_claims:
            if not isinstance(raw, dict):
                continue
            claim = _claim_payload(raw, artifact)
            if claim is not None:
                claims.append(claim)
    return sorted(
        claims,
        key=lambda item: (tuple(item["evidence_refs"]), item["claim_id"]),
    )


def detect_contradictions(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    claims = extract_claims(artifacts)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for claim in claims:
        grouped.setdefault((claim["subject"], claim["predicate"]), []).append(claim)

    contradictions: list[dict[str, Any]] = []
    for (subject, predicate), candidates in sorted(grouped.items()):
        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                if left["status"] == "superseded" or right["status"] == "superseded":
                    continue
                if not _incompatible(left, right):
                    continue
                overlaps, temporal_resolution = _temporal_relation(left, right)
                if not overlaps:
                    continue
                priorities = (
                    CLAIM_PRIORITY[left["claim_type"]],
                    CLAIM_PRIORITY[right["claim_type"]],
                )
                preferred: dict[str, Any] | None = None
                if priorities[0] != priorities[1]:
                    preferred = left if priorities[0] > priorities[1] else right
                claim_types = {left["claim_type"], right["claim_type"]}
                contradiction_type = (
                    "interpretation_conflict"
                    if claim_types & INTERPRETATION_TYPES and claim_types & EVIDENCE_TYPES
                    else "direct_fact_conflict"
                )
                contradiction_id = stable_id(
                    "contradiction",
                    subject,
                    predicate,
                    *sorted((left["claim_id"], right["claim_id"])),
                )
                contradiction_claims = tuple(
                    {
                        **claim,
                        "contradiction_refs": sorted(
                            {*claim["contradiction_refs"], contradiction_id}
                        ),
                    }
                    for claim in (left, right)
                )
                contradictions.append(
                    ContradictionRecord(
                        contradiction_id=contradiction_id,
                        subject=subject,
                        predicate=predicate,
                        claims=contradiction_claims,
                        severity="medium",
                        resolution_status=(
                            "provisionally_resolved" if preferred else "unresolved"
                        ),
                        contradiction_type=contradiction_type,
                        temporal_resolution=temporal_resolution,
                        preferred_claim_id=preferred["claim_id"] if preferred else None,
                        preference_reason=(
                            f"higher deterministic claim priority: {preferred['claim_type']}"
                            if preferred
                            else None
                        ),
                    ).to_dict()
                )
    return sorted(contradictions, key=lambda item: item["contradiction_id"])
