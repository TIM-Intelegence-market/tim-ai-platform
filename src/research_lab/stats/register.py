"""Hypothesis register and one-time holdout lock (protocol sections 6, 8, 10).

The register is an append-only JSON-lines file with a hash chain: every attempt
counts, discarded ones included, and m never decreases. The holdout lock is a
file created exclusively; a second holdout run is refused.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.research_lab.data.store import HoldoutPermission, _issue_permission
from src.research_lab.protocol import MAX_REGISTER_ENTRIES, PROTOCOL_VERSION

GENESIS = "0" * 64
STATUSES = {"registered", "failed_train", "failed_validation", "candidate", "passed_holdout", "failed_holdout", "no_verdict", "not_selected"}


class RegisterError(ValueError):
    pass


def _digest(previous: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True)).encode()).hexdigest()


class HypothesisRegister:
    def __init__(self, path: Path | str, *, limit: int = MAX_REGISTER_ENTRIES) -> None:
        self.path = Path(path)
        self.limit = limit

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events = [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
        previous = GENESIS
        for event in events:
            body = {k: v for k, v in event.items() if k != "hash"}
            if body.get("previous") != previous or event.get("hash") != _digest(previous, body):
                raise RegisterError("register hash chain is broken; the file was edited")
            previous = event["hash"]
        return events

    def _append(self, body: dict[str, Any]) -> None:
        events = self.events()
        previous = events[-1]["hash"] if events else GENESIS
        body = {**body, "previous": previous, "protocol": PROTOCOL_VERSION}
        event = {**body, "hash": _digest(previous, body)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")

    def variants(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for event in self.events():
            if event["kind"] == "register":
                result[event["variant"]] = {"hypothesis": event["hypothesis"], "params": event["params"], "status": "registered"}
            else:
                result[event["variant"]]["status"] = event["status"]
        return result

    @property
    def m(self) -> int:
        return len(self.variants())

    def register(self, variant: str, hypothesis: str, params: dict[str, Any]) -> None:
        known = self.variants()
        if variant in known:
            raise RegisterError(f"{variant} is already registered")
        if len(known) >= self.limit:
            raise RegisterError(f"register limit of {self.limit} reached; a new holdout period is needed")
        self._append({"kind": "register", "variant": variant, "hypothesis": hypothesis, "params": params})

    def set_status(self, variant: str, status: str, note: str = "") -> None:
        known = self.variants()
        if variant not in known:
            raise RegisterError(f"{variant} is not registered")
        if status not in STATUSES:
            raise RegisterError(f"unknown status {status}")
        current = known[variant]["status"]
        if current in {"failed_train", "failed_validation", "not_selected", "failed_holdout", "passed_holdout", "no_verdict"}:
            raise RegisterError(f"{variant} already has a final status")
        if current == "candidate" and status not in {"passed_holdout", "failed_holdout", "no_verdict"}:
            raise RegisterError(f"{variant} is a frozen candidate; only the holdout can decide it")
        self._append({"kind": "status", "variant": variant, "status": status, "note": note})


def candidates_hash(candidates: list[str], register: HypothesisRegister) -> str:
    events = register.events()
    head = events[-1]["hash"] if events else GENESIS
    return hashlib.sha256(json.dumps({"candidates": sorted(candidates), "register": head}).encode()).hexdigest()


def claim_holdout(lock_path: Path | str, candidates: list[str], register: HypothesisRegister) -> HoldoutPermission:
    """Create the holdout lock exactly once. A second call raises FileExistsError.

    The lock records m and the register head hash. Commit the register and the
    lock to git so that a later truncation of the register is visible."""
    variants = register.variants()
    unknown = [c for c in candidates if c not in variants]
    if unknown:
        raise RegisterError(f"candidates not in register: {unknown}")
    not_candidates = [c for c in candidates if variants[c]["status"] != "candidate"]
    if not_candidates:
        raise RegisterError(f"variants without candidate status: {not_candidates}")
    per_hypothesis: dict[str, int] = {}
    for c in candidates:
        per_hypothesis[variants[c]["hypothesis"]] = per_hypothesis.get(variants[c]["hypothesis"], 0) + 1
    if max(per_hypothesis.values(), default=0) > 2:
        raise RegisterError("at most two candidates per hypothesis (protocol section 8)")
    events = register.events()
    digest = candidates_hash(candidates, register)
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:  # exclusive: refuses a second holdout run
        json.dump({"candidates": sorted(candidates), "candidates_hash": digest, "m": len(variants),
                   "register_head": events[-1]["hash"], "protocol": PROTOCOL_VERSION}, handle, sort_keys=True)
    return _issue_permission(f"holdout {digest[:12]}", tuple(sorted(candidates)), len(variants))
