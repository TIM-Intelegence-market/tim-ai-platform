"""Bounded content review of reviewed files between two SHA-256 manifests.

Pure comparison only: no Git, subprocess, network, writes or deletion.
"""
from __future__ import annotations

import re
from typing import Any

_DIGEST = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_SEGMENTS = frozenset({".git", ".env", "secrets", "credentials", "keychain"})


def _valid_path(path: Any) -> bool:
    if not isinstance(path, str) or not path:
        return False
    if path.startswith("/") or "\\" in path:
        return False
    for segment in path.split("/"):
        if segment in ("", ".", "..") or segment.lower() in _FORBIDDEN_SEGMENTS:
            return False
    return True


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _result(status: str, present: list, missing: list, changed: list, reasons: set) -> dict:
    return {
        "status": status,
        "present": sorted(present),
        "missing": sorted(missing),
        "changed": sorted(changed),
        "reasons": sorted(reasons),
        "automatic_merge": False,
    }


def compare_reviewed_files(candidate: Any, current: Any, *, reviewed_paths: Any) -> dict:
    """Compare only ``reviewed_paths`` between candidate and current manifests.

    Reasons are fixed codes; raw invalid input values are never echoed.
    """
    reasons: set = set()
    if not isinstance(candidate, dict):
        reasons.add("candidate_not_mapping")
    if not isinstance(current, dict):
        reasons.add("current_not_mapping")
    if not isinstance(reviewed_paths, list) or not reviewed_paths:
        reasons.add("reviewed_paths_invalid")
    elif not all(_valid_path(p) for p in reviewed_paths):
        reasons.add("reviewed_path_invalid")
    elif len(set(reviewed_paths)) != len(reviewed_paths):
        reasons.add("reviewed_path_duplicate")
    if reasons:
        return _result("BLOCKED", [], [], [], reasons)

    for path in reviewed_paths:
        if path not in candidate:
            reasons.add("candidate_entry_missing")
        elif not _valid_digest(candidate[path]):
            reasons.add("candidate_digest_invalid")
        if path in current and not _valid_digest(current[path]):
            reasons.add("current_digest_invalid")
    if reasons:
        return _result("BLOCKED", [], [], [], reasons)

    present: list = []
    missing: list = []
    changed: list = []
    for path in reviewed_paths:
        if path not in current:
            missing.append(path)
        elif current[path] == candidate[path]:
            present.append(path)
        else:
            changed.append(path)

    if not missing and not changed:
        return _result("ALREADY_PRESENT", present, missing, changed, set())
    if missing:
        reasons.add("reviewed_files_missing")
    if changed:
        reasons.add("reviewed_files_changed")
    return _result("REVIEW_REQUIRED", present, missing, changed, reasons)
