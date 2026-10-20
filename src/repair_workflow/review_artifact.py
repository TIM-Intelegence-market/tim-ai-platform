"""Build deterministic, human-reviewable repair artifacts."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


_PATCH_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_non_empty_text(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")


def build_review_artifact(
    *,
    incident_id: str,
    task_id: str,
    reproduction_ref: dict,
    patch_sha256: str,
    diff_check: dict,
    test_reports: dict,
    gate_decision: dict,
) -> dict:
    """Validate inputs and return a deterministic repair review artifact."""
    _require_non_empty_text(incident_id, "incident_id")
    _require_non_empty_text(task_id, "task_id")

    if not isinstance(patch_sha256, str) or not _PATCH_SHA256_RE.fullmatch(patch_sha256):
        raise ValueError("patch_sha256 must be 64 lowercase hexadecimal characters")

    if (
        not isinstance(reproduction_ref, dict)
        or not isinstance(reproduction_ref.get("status"), str)
        or not reproduction_ref["status"]
    ):
        raise ValueError("reproduction_ref must contain a non-empty string status")

    if not isinstance(diff_check, dict) or not isinstance(diff_check.get("ok"), bool):
        raise ValueError("diff_check must contain a boolean ok")

    if (
        not isinstance(test_reports, dict)
        or not test_reports
        or not all(isinstance(status, str) for status in test_reports.values())
    ):
        raise ValueError("test_reports must be a non-empty dict of string statuses")

    if not isinstance(gate_decision, dict) or not isinstance(gate_decision.get("status"), str):
        raise ValueError("gate_decision must contain a string status")

    reproduction_copy = copy.deepcopy(reproduction_ref)
    diff_copy = copy.deepcopy(diff_check)
    reports_copy = copy.deepcopy(test_reports)
    gate_copy = copy.deepcopy(gate_decision)

    verdict = (
        "READY_FOR_HUMAN_REVIEW"
        if (
            reproduction_copy["status"] == "REPRODUCED"
            and diff_copy["ok"] is True
            and all(status == "PASS" for status in reports_copy.values())
            and gate_copy["status"] == "PASS"
        )
        else "BLOCKED"
    )

    artifact = {
        "schema_version": 1,
        "incident_id": incident_id,
        "task_id": task_id,
        "reproduction_ref": reproduction_copy,
        "patch_sha256": patch_sha256,
        "diff_check": diff_copy,
        "test_reports": reports_copy,
        "gate_decision": gate_copy,
        "verdict": verdict,
    }
    canonical = json.dumps(artifact, sort_keys=True, separators=(",", ":"))
    artifact["artifact_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return artifact
