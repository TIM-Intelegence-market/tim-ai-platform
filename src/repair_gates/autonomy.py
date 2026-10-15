"""Autonomy repair gate adapter."""

from typing import Any

from src.bugfixer.remediation import _gate
from src.repair_gates.result import GateResult, GateStatus


def _gate_result(result: Any) -> tuple[str, str]:
    if isinstance(result, tuple) and len(result) == 2:
        return str(result[0]), str(result[1])
    if isinstance(result, dict):
        return str(result.get("decision", result.get("status", ""))), str(result.get("reason", ""))
    return str(getattr(result, "decision", getattr(result, "status", ""))), str(getattr(result, "reason", ""))


def evaluate(row: dict, category: str, satisfied: dict) -> GateResult:
    """Evaluate the remediation decision as the autonomy gate."""
    decision, reason = _gate(row, category, satisfied)
    if decision == "PROPOSED":
        status = GateStatus.PASS
    elif decision in {"OBSERVE_ONLY", "BLOCKED", "REVIEW_REQUIRED"}:
        status = GateStatus.BLOCKED
    else:
        status = GateStatus.FAIL

    if decision == "SAFE_STOP":
        reason = f"SAFE_STOP: {reason}"
    if status is not GateStatus.PASS and not reason:
        reason = decision or "no decision"
    return GateResult("autonomy", status, reason)
