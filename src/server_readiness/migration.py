"""Track migration progress over stage receipts S0..S11.

Pure evaluation only: cutover is never authorized by this module.
"""
from __future__ import annotations

import re
from typing import Any

STAGES = tuple("S" + str(n) for n in range(12))

_EVIDENCE_RE = re.compile(r"sha256:[0-9a-f]{64}")
_REQUIRED_KEYS = frozenset({"stage", "status", "evidence_ref"})
_STATUSES = frozenset({"PASS", "PARTIAL", "FAIL", "SAFE_STOP"})


def _result(status: str, completed: list, next_stage: str | None, reasons: set) -> dict:
    return {
        "status": status,
        "completed": list(completed),
        "next_stage": next_stage,
        "reasons": sorted(reasons),
        "cutover_authorized": False,
    }


def _blocked(reasons: set) -> dict:
    return _result("BLOCKED", [], STAGES[0], reasons)


def migration_progress(receipts: Any) -> dict:
    """Return progress over the consecutive PASS prefix S0, S1, ...

    SAFE_STOP in any stage wins the status but ``completed``/``next_stage`` still
    describe the consecutive PASS prefix.
    """
    try:
        if not isinstance(receipts, list):
            return _blocked({"receipts must be a list"})
        if not receipts:
            return _blocked({"no receipts"})

        reasons: set = set()
        by_stage: dict = {}
        for receipt in receipts:
            if not isinstance(receipt, dict) or set(receipt) != _REQUIRED_KEYS:
                reasons.add("invalid receipt")
                continue
            stage = receipt["stage"]
            if not isinstance(stage, str) or stage not in STAGES:
                reasons.add("unknown stage")
                continue
            status = receipt["status"]
            if not isinstance(status, str) or status not in _STATUSES:
                reasons.add(f"{stage}: invalid status")
            evidence = receipt["evidence_ref"]
            if not isinstance(evidence, str) or _EVIDENCE_RE.fullmatch(evidence) is None:
                reasons.add(f"{stage}: invalid evidence_ref")
            if stage in by_stage:
                reasons.add(f"{stage}: duplicate receipt")
            by_stage[stage] = status
        if reasons:
            return _blocked(reasons)

        completed = []
        for stage in STAGES:
            if by_stage.get(stage) != "PASS":
                break
            completed.append(stage)
        next_stage = STAGES[len(completed)] if len(completed) < len(STAGES) else None

        if next_stage is not None:
            status = by_stage.get(next_stage)
            reasons.add(f"{next_stage}: missing receipt" if status is None else f"{next_stage}: status {status}")
            for stage in STAGES[len(completed) + 1:]:
                if by_stage.get(stage) == "PASS":
                    reasons.add(f"{stage}: PASS not counted, prerequisite {next_stage} not passed")

        safe_stops = [stage for stage, status in by_stage.items() if status == "SAFE_STOP"]
        if safe_stops:
            reasons.update(f"{stage}: status SAFE_STOP" for stage in safe_stops)
            return _result("SAFE_STOP", completed, next_stage, reasons)
        if next_stage is None:
            return _result("PASS", completed, None, set())
        return _result("BLOCKED", completed, next_stage, reasons)
    except Exception:
        return _blocked({"invalid input"})
