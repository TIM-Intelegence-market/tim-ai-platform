"""Bounded reconnect repair recipe."""

from src.repair_gates import forbidden

RECONNECT_BUDGET = 8


def reconnect_step(attempt):
    if type(attempt) is not int or attempt < 0:
        return {"decision": "ESCALATED", "reason": "invalid attempt"}
    if attempt >= RECONNECT_BUDGET:
        return {"decision": "ESCALATED", "reason": "reconnect budget exhausted"}
    return {"decision": "RECONNECT", "delay_seconds": min(30, 2 ** min(attempt, 5))}


def _field(result, name):
    if isinstance(result, dict):
        return result.get(name)
    return getattr(result, name, None)


def _gate_failure(result):
    """Return the gate reason when the result is a FAIL, otherwise None."""
    status = _field(result, "status")
    if status is None:
        status = _field(result, "verdict")
    status = getattr(status, "name", status)
    failed = isinstance(status, str) and status.upper() == "FAIL"
    if not failed:
        for flag in ("ok", "passed"):
            if _field(result, flag) is False:
                failed = True
                break
    if not failed:
        return None
    reason = _field(result, "reason")
    return reason if isinstance(reason, str) and reason else "forbidden action"


def plan(category, action, attempt):
    try:
        reason = _gate_failure(forbidden.check_action(action))
        if reason is not None:
            return {"decision": "REJECTED", "reason": reason}
        if category in ("TERMINAL_BLOCKED", "INVARIANT_VIOLATION"):
            return {"decision": "SAFE_STOP"}
        if category == "NETWORK" and action == "bounded_reconnect":
            return reconnect_step(attempt)
    except Exception:
        return {"decision": "REJECTED", "reason": "gate error"}
    return {"decision": "ESCALATED", "reason": "no proven recipe"}
