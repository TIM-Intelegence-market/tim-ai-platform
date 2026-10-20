"""Isolated throw-away workspaces and a deterministic double replay."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import pathlib
import shutil
import tempfile
from collections.abc import Callable, Iterator
from typing import Any

from src.repair_repro import result as _result
from src.repair_repro.result import ReproResult


def _status(name: str) -> Any:
    for enum_name in ("ReproStatus", "ReproOutcome", "Status"):
        enum = getattr(_result, enum_name, None)
        if enum is not None and hasattr(enum, name):
            return getattr(enum, name)
    return name


@contextlib.contextmanager
def isolated_workspace(prefix: str = "tim-repro-") -> Iterator[pathlib.Path]:
    if not isinstance(prefix, str) or not prefix:
        raise ValueError("prefix must be a non-empty str")
    if "/" in prefix or "\\" in prefix or ".." in prefix:
        raise ValueError("prefix must not contain '/', '\\' or '..'")
    path = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _insufficient(case_id: str, reason: str) -> ReproResult:
    return ReproResult(
        case_id=case_id, status=_status("INSUFFICIENT_EVIDENCE"), reason=reason
    )


def replay_twice(
    case_id: str, fn: Callable[[pathlib.Path, Any], Any], payload: Any
) -> ReproResult:
    results = []
    try:
        for _ in range(2):
            with isolated_workspace() as workspace:
                results.append(fn(workspace, copy.deepcopy(payload)))
    except Exception as exc:
        return _insufficient(case_id, "reproduction raised: " + type(exc).__name__)
    if not all(isinstance(item, bool) for item in results):
        return _insufficient(case_id, "reproduction returned a non-boolean")
    if results[0] != results[1]:
        return _insufficient(case_id, "non-deterministic reproduction")
    if not results[0]:
        return ReproResult(case_id=case_id, status=_status("NOT_REPRODUCED"))
    blob = json.dumps(
        {"case_id": case_id, "payload": payload, "result": True},
        sort_keys=True,
        default=str,
    )
    digest = "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return ReproResult(
        case_id=case_id,
        status=_status("REPRODUCED"),
        evidence_refs=(digest,),
    )
