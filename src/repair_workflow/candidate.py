"""Classify a repair candidate record for human review. Never merges, never marks fixed."""

from src.repair_repro.result import ReproResult

READY = "READY_FOR_REVIEW"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
SAFE_STOP = "SAFE_STOP"


def _result(status, reasons):
    return {
        "status": status,
        "reasons": sorted(str(r) for r in reasons),
        "auto_merge": False,
        "fixed": False,
    }


def _non_empty_str(value):
    return isinstance(value, str) and bool(value.strip())


def _repro_status(repro):
    raw = repro.get("status") if isinstance(repro, dict) else getattr(repro, "status", None)
    raw = getattr(raw, "value", raw)
    if not isinstance(raw, str):
        return None
    return raw.strip().upper()


def _classify(record):
    if not isinstance(record, dict):
        return _result(BLOCKED, ["record is not a dict"])

    reasons = []
    for key in ("incident_id", "task_id"):
        if not _non_empty_str(record.get(key)):
            reasons.append(f"invalid or missing {key}")
    if "reproduction_waiver" in record and not _non_empty_str(record["reproduction_waiver"]):
        reasons.append("invalid reproduction_waiver")
    for key in ("reproduction", "diff_check", "gate_decision"):
        if not isinstance(record.get(key), dict):
            reasons.append(f"invalid or missing {key}")
    gate = record.get("gate_decision")
    if isinstance(gate, dict) and not isinstance(gate.get("status"), str):
        reasons.append("invalid gate_decision status")
    if reasons:
        return _result(BLOCKED, reasons)

    try:
        repro = ReproResult.from_dict(record["reproduction"])
    except Exception as exc:
        return _result(BLOCKED, [f"reproduction rejected: {type(exc).__name__}"])
    repro_status = _repro_status(repro)
    if repro_status is None:
        return _result(BLOCKED, ["reproduction status unreadable"])

    gate_status = gate["status"]
    if gate_status == "SAFE_STOP":
        return _result(SAFE_STOP, ["gate decision is SAFE_STOP"])
    if gate_status != "PASS":
        return _result(FAILED, [f"gate decision is {gate_status}"])
    if record["diff_check"].get("ok") is not True:
        return _result(FAILED, ["diff check not ok"])
    if repro_status == "NOT_REPRODUCED":
        return _result(BLOCKED, ["incident not reproduced"])

    waiver = record.get("reproduction_waiver")
    if repro_status == "INSUFFICIENT_EVIDENCE":
        if not waiver:
            return _result(BLOCKED, ["insufficient reproduction evidence without waiver"])
        return _result(READY, ["ready for review with reproduction waiver"])
    return _result(READY, ["ready for review"])


def candidate_status(record):
    try:
        return _classify(record)
    except Exception as exc:
        return _result(BLOCKED, [f"unexpected error: {type(exc).__name__}"])
