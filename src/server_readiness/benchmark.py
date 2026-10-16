"""Compare Mac and server benchmark runs for identical results and relative speed.

Pure comparison only: no network, subprocess, filesystem reads or model calls.
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any

_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_REQUIRED_KEYS = frozenset(
    {"case_id", "input_sha256", "output_sha256", "code_sha", "model", "duration_seconds"}
)
_COMPARED_FIELDS = ("input_sha256", "code_sha", "output_sha256")


def _result(status: str, reasons: set, case_count: int = 0, ratio: float | None = None) -> dict:
    return {
        "status": status,
        "reasons": sorted(reasons),
        "case_count": case_count,
        "median_speed_ratio": ratio,
    }


def _duration(value: Any) -> float | None:
    """Return a positive finite float, or None. Bool and unconvertible ints are invalid."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError, TypeError):
        return None
    if not math.isfinite(converted) or converted <= 0:
        return None
    return converted


def _valid_row(row: Any) -> bool:
    if not isinstance(row, dict) or set(row) != _REQUIRED_KEYS:
        return False
    if not isinstance(row["case_id"], str) or not row["case_id"]:
        return False
    for key in ("input_sha256", "output_sha256"):
        if not isinstance(row[key], str) or _HEX64.fullmatch(row[key]) is None:
            return False
    if not isinstance(row["code_sha"], str) or _HEX40.fullmatch(row["code_sha"]) is None:
        return False
    if not isinstance(row["model"], str) or not row["model"]:
        return False
    return _duration(row["duration_seconds"]) is not None


def _index(runs: Any, name: str, reasons: set) -> dict | None:
    if not isinstance(runs, list) or not runs:
        reasons.add(f"{name} must be a non-empty list")
        return None
    indexed: dict = {}
    ok = True
    for row in runs:
        if not _valid_row(row):
            reasons.add(f"{name} contains an invalid row")
            ok = False
            continue
        case_id = row["case_id"]
        if case_id in indexed:
            reasons.add(f"{name} contains duplicate case_id {case_id}")
            ok = False
            continue
        indexed[case_id] = row
    return indexed if ok else None


def compare_runs(mac_runs: Any, server_runs: Any, *, required_model: Any) -> dict:
    try:
        reasons: set = set()
        if not isinstance(required_model, str) or not required_model:
            reasons.add("required_model must be a non-empty string")
        mac = _index(mac_runs, "mac_runs", reasons)
        server = _index(server_runs, "server_runs", reasons)
        if reasons or mac is None or server is None:
            return _result("BLOCKED", reasons)

        for case_id in set(mac) - set(server):
            reasons.add(f"case {case_id} missing from server_runs")
        for case_id in set(server) - set(mac):
            reasons.add(f"case {case_id} missing from mac_runs")
        if reasons:
            return _result("BLOCKED", reasons)

        for case_id, server_row in server.items():
            mac_row = mac[case_id]
            if server_row["model"] != required_model:
                reasons.add(f"case {case_id}: model does not match required_model")
            for field in _COMPARED_FIELDS:
                if mac_row[field] != server_row[field]:
                    reasons.add(f"case {case_id}: {field} mismatch")
        if reasons:
            return _result("FAIL", reasons)

        ratios = [
            _duration(mac[case_id]["duration_seconds"]) / _duration(server[case_id]["duration_seconds"])
            for case_id in sorted(server)
        ]
        if not all(math.isfinite(ratio) for ratio in ratios):
            return _result("BLOCKED", {"speed ratio is not finite"})
        median = float(statistics.median(ratios))
        if not math.isfinite(median):
            return _result("BLOCKED", {"speed ratio is not finite"})
        return _result("PASS", set(), len(ratios), median)
    except Exception:
        return _result("BLOCKED", {"invalid input"})
