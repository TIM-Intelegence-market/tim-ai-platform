"""Critical integrity gates: determinism, lookahead, database and queue.

Each function is pure and never raises: malformed input yields FAIL.
"""

import re

from src.repair_gates.result import GateResult, GateStatus
from src.repair_repro.guards import cutoff_filter, database_guard

_DIGEST = re.compile(r"[0-9a-f]{64}")


def _pass(name: str) -> GateResult:
    return GateResult(name, GateStatus.PASS)


def _fail(name: str, reason: str) -> GateResult:
    return GateResult(name, GateStatus.FAIL, reason)


def _is_digest(value: object) -> bool:
    return type(value) is str and _DIGEST.fullmatch(value) is not None


def _is_count(value: object) -> bool:
    return type(value) is int and value >= 0


def determinism(first_digest: object, second_digest: object) -> GateResult:
    name = "determinism"
    if not _is_digest(first_digest) or not _is_digest(second_digest):
        return _fail(name, "digests must be 64-character lowercase hex strings")
    if first_digest != second_digest:
        return _fail(name, "digests differ between runs")
    return _pass(name)


def lookahead_safety(events: object, cutoff: object) -> GateResult:
    name = "lookahead_safety"
    if type(events) is not list:
        return _fail(name, "events must be a list")
    try:
        kept = cutoff_filter(events, cutoff)
    except Exception:
        return _fail(name, "invalid event or cutoff timestamp")
    late = len(events) - len(kept)
    if late:
        return _fail(name, "%d event(s) after cutoff" % late)
    return _pass(name)


def db_integrity(test_url: object, runtime_url: object) -> GateResult:
    name = "db_integrity"
    try:
        isolated, reason = database_guard(test_url, runtime_url)
    except Exception:
        return _fail(name, "invalid database guard input")
    if isolated is not True:
        return _fail(name, reason or "database not isolated")
    return _pass(name)


def _queue_shape_ok(snapshot: object) -> bool:
    if not isinstance(snapshot, dict):
        return False
    attempts = snapshot.get("attempts")
    return (
        _is_count(snapshot.get("pending"))
        and isinstance(attempts, dict)
        and all(type(key) is str and _is_count(count) for key, count in attempts.items())
    )


def queue_integrity(before: object, after: object) -> GateResult:
    name = "queue_integrity"
    if not _queue_shape_ok(before) or not _queue_shape_ok(after):
        return _fail(name, "invalid queue snapshot")
    if before["pending"] > 0 and after["pending"] == 0:
        return _fail(name, "queue cleared globally")
    previous, current = before["attempts"], after["attempts"]
    if any(key not in current or current[key] < count for key, count in previous.items()):
        return _fail(name, "attempts reset")
    return _pass(name)
