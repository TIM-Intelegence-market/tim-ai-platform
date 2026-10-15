"""Read-only validation gates for repair evidence reports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPORT_GATES = (
    "targeted_tests",
    "regression_tests",
    "runtime",
    "safety",
    "integrity",
    "recurrence",
    "pre_repair_repro",
    "post_repair_repro",
)


@dataclass
class GateResult:
    name: str
    status: str
    reason: str
    evidence_refs: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def gate(self) -> str:
        return self.name


def _fail(name: str, reason: str, path: str | None = None) -> GateResult:
    return GateResult(name=name, status="FAIL", reason=reason,
                      evidence_refs=[] if path is None else [path])


def gates_from_refs(refs: dict[str, Any]) -> list[GateResult]:
    """Validate each required evidence report without executing anything."""
    results: list[GateResult] = []

    for name in REPORT_GATES:
        ref = refs.get(name) if isinstance(refs, dict) else None
        if not isinstance(ref, dict):
            results.append(_fail(name, "missing evidence reference"))
            continue

        path = ref.get("path")
        expected_hash = ref.get("sha256")
        if not isinstance(path, str) or not path:
            results.append(_fail(name, "missing evidence path"))
            continue
        if not isinstance(expected_hash, str) or not expected_hash:
            results.append(_fail(name, "missing expected sha256", path))
            continue

        try:
            data = Path(path).read_bytes()
        except (OSError, ValueError) as exc:
            results.append(_fail(name, f"unreadable evidence file: {exc}", path))
            continue

        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != expected_hash:
            results.append(_fail(name, "sha256 mismatch", path))
            continue

        try:
            report = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            results.append(_fail(name, f"invalid JSON: {exc}", path))
            continue

        if not isinstance(report, dict) or "status" not in report:
            results.append(_fail(name, "missing status", path))
            continue

        expected_status = "FAIL_AS_EXPECTED" if name == "pre_repair_repro" else "PASS"
        status = report["status"]
        if status != expected_status:
            results.append(_fail(name, f"unexpected status: {status!r}", path))
            continue

        results.append(GateResult(name=name, status="PASS", reason="evidence valid",
                                  evidence_refs=[path]))

    return results
