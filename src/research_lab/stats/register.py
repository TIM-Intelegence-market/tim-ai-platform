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

from src.research_lab.data.store import HoldoutPermission
from src.research_lab.protocol import MAX_REGISTER_ENTRIES, PROTOCOL_VERSION

GENESIS = "0" * 64
STATUSES = {"registered", "failed_train", "failed_validation", "candidate", "passed_holdout", "failed_holdout", "no_verdict"}


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
        if known[variant]["status"] in {"failed_train", "failed_validation", "failed_holdout", "passed_holdout"}:
            raise RegisterError(f"{variant} already has a final status")
        self._append({"kind": "status", "variant": variant, "status": status, "note": note})


def candidates_hash(candidates: list[str], register: HypothesisRegister) -> str:
    events = register.events()
    head = events[-1]["hash"] if events else GENESIS
    return hashlib.sha256(json.dumps({"candidates": sorted(candidates), "register": head}).encode()).hexdigest()


def claim_holdout(lock_path: Path | str, candidates: list[str], register: HypothesisRegister) -> HoldoutPermission:
    """Create the holdout lock exactly once. A second call raises FileExistsError."""
    unknown = [c for c in candidates if c not in register.variants()]
    if unknown:
        raise RegisterError(f"candidates not in register: {unknown}")
    digest = candidates_hash(candidates, register)
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:  # exclusive: refuses a second holdout run
        json.dump({"candidates": sorted(candidates), "candidates_hash": digest, "m": register.m, "protocol": PROTOCOL_VERSION}, handle, sort_keys=True)
    return HoldoutPermission(f"holdout {digest[:12]}")
