from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from typing import Any


REQUIRED_CASES = {
    ("admin", "idrac"): True,
    ("admin", "server_ssh"): True,
    ("admin", "timec"): True,
    ("member", "idrac"): False,
    ("member", "server_ssh"): False,
    ("member", "timec"): True,
    ("outsider", "idrac"): False,
    ("outsider", "server_ssh"): False,
    ("outsider", "timec"): False,
}

_EVIDENCE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REQUIRED_KEYS = {"role", "target", "reachable", "observed_at", "evidence_ref"}


def _result(status: str, violations: set[str], missing: set[str]) -> dict[str, Any]:
    return {
        "status": status,
        "violations": sorted(violations),
        "missing": sorted(missing),
        "changes_applied": False,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def evaluate_access_matrix(
    observations: Any,
    *,
    now: datetime,
    max_age_seconds: int | float = 3600,
) -> dict[str, Any]:
    required_names = {f"{role}/{target}" for role, target in REQUIRED_CASES}
    missing = set(required_names)
    violations: set[str] = set()

    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return _result("BLOCKED", {"invalid_now"}, missing)
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float)):
        return _result("BLOCKED", {"invalid_max_age_seconds"}, missing)
    if not math.isfinite(float(max_age_seconds)) or max_age_seconds < 0:
        return _result("BLOCKED", {"invalid_max_age_seconds"}, missing)
    if not isinstance(observations, list):
        return _result("BLOCKED", {"invalid_observations"}, missing)

    seen: set[tuple[str, str]] = set()
    valid: dict[tuple[str, str], bool] = {}
    safe_stop = False

    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != _REQUIRED_KEYS:
            violations.add("invalid_observation")
            continue

        role = observation["role"]
        target = observation["target"]
        case = (role, target) if isinstance(role, str) and isinstance(target, str) else None
        if case not in REQUIRED_CASES:
            violations.add("unknown_case")
            continue
        if case in seen:
            violations.add("duplicate_case")
        seen.add(case)

        reachable = observation["reachable"]
        timestamp = _parse_timestamp(observation["observed_at"])
        evidence_ref = observation["evidence_ref"]
        well_formed = (
            type(reachable) is bool
            and timestamp is not None
            and isinstance(evidence_ref, str)
            and _EVIDENCE_RE.fullmatch(evidence_ref) is not None
        )
        if not well_formed:
            violations.add("invalid_observation")
            continue

        age = (now - timestamp).total_seconds()
        if age < 0:
            violations.add("future_observation")
            continue
        if age > max_age_seconds:
            violations.add("stale_observation")
            continue

        if not REQUIRED_CASES[case] and reachable:
            safe_stop = True
        valid[case] = reachable

    for case, expected in REQUIRED_CASES.items():
        name = f"{case[0]}/{case[1]}"
        if case not in valid:
            missing.add(name)
        elif valid[case] != expected:
            violations.add("policy_mismatch")
        else:
            missing.discard(name)

    if safe_stop:
        return _result("SAFE_STOP", violations, missing)
    if violations or missing:
        return _result("BLOCKED", violations, missing)
    return _result("PASS", set(), set())
