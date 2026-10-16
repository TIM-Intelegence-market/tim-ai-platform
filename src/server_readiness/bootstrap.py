"""Evaluate server bootstrap gate evidence records.

Pure evaluation only: nothing is executed (``executed`` is always False).
"""
from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any

REQUIRED_GATES = (
    "debian_13",
    "encrypted_reboot",
    "key_only_ssh",
    "direct_github",
    "worker_smoke",
    "portal_systemd",
    "network_acceptance",
    "operations_acceptance",
    "git_reconciliation",
)

_EVIDENCE_RE = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED_KEYS = frozenset({"gate", "status", "observed_at", "evidence_ref"})
_STATUSES = frozenset({"PASS", "FAIL", "BLOCKED"})


def _result(status: str, reasons: set, missing: set) -> dict:
    return {
        "status": status,
        "reasons": sorted(reasons),
        "missing": sorted(missing),
        "executed": False,
    }


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _max_age(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        finite = math.isfinite(float(value))
    except (OverflowError, ValueError):
        return None
    if not finite or value < 0:
        return None
    return value


def evaluate_bootstrap(records: Any, *, now: Any, max_age_seconds: Any = 86400) -> dict:
    """Return PASS only when every required gate has exactly one valid, fresh PASS record.

    ``missing`` lists required gates with no record at all. A well-formed record with
    status FAIL (known gate, valid evidence_ref, aware observed_at) yields FAIL regardless
    of freshness, missing gates or other problems. ``age == max_age_seconds`` is fresh.
    """
    try:
        reasons: set = set()
        parsed_now = now
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            reasons.add("now must be a timezone-aware datetime")
            parsed_now = None
        age_limit = _max_age(max_age_seconds)
        if age_limit is None:
            reasons.add("max_age_seconds must be a finite non-negative number")
        if not isinstance(records, list):
            reasons.add("records must be a list")
            return _result("BLOCKED", reasons, set(REQUIRED_GATES))

        counts = {gate: 0 for gate in REQUIRED_GATES}
        failed = False
        passed: set = set()
        candidates = []
        for record in records:
            if not isinstance(record, dict) or set(record) != _REQUIRED_KEYS:
                reasons.add("invalid record")
                continue
            gate = record["gate"]
            if not isinstance(gate, str) or gate not in counts:
                reasons.add("unknown gate")
                continue
            counts[gate] += 1
            status = record["status"]
            observed = _timestamp(record["observed_at"])
            evidence = record["evidence_ref"]
            well_formed = True
            if not isinstance(status, str) or status not in _STATUSES:
                reasons.add(f"{gate}: invalid status")
                well_formed = False
            if observed is None:
                reasons.add(f"{gate}: invalid observed_at")
                well_formed = False
            if not isinstance(evidence, str) or _EVIDENCE_RE.fullmatch(evidence) is None:
                reasons.add(f"{gate}: invalid evidence_ref")
                well_formed = False
            if not well_formed:
                continue
            if status == "FAIL":
                failed = True
                reasons.add(f"{gate}: status FAIL")
                continue
            if status == "BLOCKED":
                reasons.add(f"{gate}: status BLOCKED")
                continue
            candidates.append((gate, observed))

        for gate, count in counts.items():
            if count > 1:
                reasons.add(f"{gate}: duplicate record")

        if parsed_now is not None and age_limit is not None:
            for gate, observed in candidates:
                age = (parsed_now - observed).total_seconds()
                if age < 0:
                    reasons.add(f"{gate}: observed_at is in the future")
                elif age > age_limit:
                    reasons.add(f"{gate}: observed_at is stale")
                elif counts[gate] == 1:
                    passed.add(gate)

        missing = {gate for gate, count in counts.items() if count == 0}
        for gate in missing:
            reasons.add(f"{gate}: missing record")

        if failed:
            return _result("FAIL", reasons, missing)
        if reasons or missing or passed != set(REQUIRED_GATES):
            if not reasons:
                reasons.add("not all gates passed")
            return _result("BLOCKED", reasons, missing)
        return _result("PASS", set(), set())
    except Exception:
        return _result("BLOCKED", {"invalid input"}, set(REQUIRED_GATES))
