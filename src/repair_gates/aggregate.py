"""Aggregate individual repair gate results into one verdict.

A task can only be considered repaired when every required gate passed.
The function never raises on bad input: malformed input yields FAIL.
"""

from src.repair_gates.result import GateResult, GateStatus

CRITICAL_GATES = frozenset(
    {"determinism", "lookahead_safety", "db_integrity", "queue_integrity"}
)

_PASS = GateStatus.PASS.name
_FAIL = GateStatus.FAIL.name


def _status_name(status):
    return str(getattr(status, "name", status)).upper()


def _gate_name(result):
    name = getattr(result, "gate", None)
    if name is None:
        name = getattr(result, "name", None)
    return name


def decide(required, results):
    reasons = set()
    critical_fail = False

    try:
        required_set = {str(name) for name in required}
    except Exception:
        required_set = set()
        reasons.add("required gates are not iterable")
    try:
        items = list(results)
    except Exception:
        items = []
        reasons.add("results are not iterable")

    if not required_set:
        reasons.add("no required gates")

    seen = {}
    for item in items:
        if not isinstance(item, GateResult):
            reasons.add("invalid result item: %s" % type(item).__name__)
            continue
        name = str(_gate_name(item))
        status = _status_name(getattr(item, "status", None))
        seen.setdefault(name, []).append(status)
        if name not in required_set:
            reasons.add("unexpected gate: %s" % name)
        if name in CRITICAL_GATES and status == _FAIL:
            critical_fail = True

    for name in required_set:
        statuses = seen.get(name, [])
        if not statuses:
            reasons.add("missing gate: %s" % name)
        elif len(statuses) > 1:
            reasons.add("duplicate gate: %s" % name)
        elif statuses[0] != _PASS:
            reasons.add("gate %s is %s" % (name, statuses[0]))

    if critical_fail:
        reasons.add("critical gate failed")
        return {"status": "SAFE_STOP", "escalate": True, "reasons": sorted(reasons)}
    if reasons:
        return {"status": "FAIL", "escalate": False, "reasons": sorted(reasons)}
    return {"status": "PASS", "escalate": False, "reasons": []}
