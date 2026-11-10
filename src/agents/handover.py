"""Übergabezettel ``TIM_HANDOVER_V1``: one form for every handover between roles.

Paket P1 of ``docs/MULTI_AGENTEN_SYSTEM.md`` (Uzi, 10.11.2026, "go P1"). Until now a handover had three
shapes (``TIM_QWEN_TASK_V1`` for the issue worker, the bugfixer's own task model, ``TaskRecord`` in
``contract.py``) and none of them says who hands over to whom, what proves the work, how often it has been
tried and which approval the next step needs. This module is the form and its checker, nothing else:

- It reads a fenced block from an issue or PR body and says whether it is a valid slip.
- It changes no behaviour. No worker reads it yet; the attempt limit is checked here and enforced in P2.
- A slip never grants anything. ``gate`` names the approval Uzi still has to give ("go", "merge", card);
  the approval itself is his word, never a field in a slip.

Check a file: ``python -m src.agents.handover FILE`` (exit 0 valid, 1 invalid).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from src.agents.contract import _ident, _text, canonical_json

SCHEMA = "TIM_HANDOVER_V1"
BLOCK = re.compile(r"```json\s+TIM_HANDOVER_V1\s*\n(.*?)\n```", re.DOTALL)
MAX_BLOCK_CHARS = 12_000  # same bound as the TIM_QWEN_TASK_V1 block
MAX_EVIDENCE = 20
# One first try plus two repairs (docs/MULTI_AGENTEN_SYSTEM.md, section 4). A slip cannot raise it.
MAX_ATTEMPTS = 3


class Role(StrEnum):
    PM = "PM"
    RESEARCHER = "RESEARCHER"
    DATA_STEWARD = "DATA_STEWARD"
    ENGINEER = "ENGINEER"
    TESTER = "TESTER"
    REVIEWER = "REVIEWER"
    DEVOPS = "DEVOPS"
    SECURITY = "SECURITY"
    DOCS = "DOCS"


class Gate(StrEnum):
    """Approval the receiver needs before acting. Only Uzi gives it."""

    NONE = "NONE"
    F1_GO = "F1_GO"
    F2_MERGE = "F2_MERGE"
    F3_RULE_UPDATE = "F3_RULE_UPDATE"
    F4_LIVE = "F4_LIVE"
    F5_HOLDOUT = "F5_HOLDOUT"


EVIDENCE_KINDS = ("test", "log", "number", "hash", "link", "file")
# What a role must show when it hands over (section 6). Other kinds may be added on top.
REQUIRED_EVIDENCE: Mapping[Role, str] = {
    Role.RESEARCHER: "file",    # preregistration or report
    Role.DATA_STEWARD: "hash",  # dataset hash
    Role.ENGINEER: "link",      # draft PR
    Role.TESTER: "test",        # check result on the commit
    Role.REVIEWER: "link",      # findings on the PR
    Role.DEVOPS: "log",         # deploy or health status
}
_KEYS = frozenset({"schema", "task_id", "issue_number", "from_role", "to_role", "input", "output",
                   "evidence", "attempt", "max_attempts", "gate"})


class HandoverError(ValueError):
    """The slip is missing, unreadable or breaks a rule. The handover does not count."""


@dataclass(frozen=True, slots=True)
class Evidence:
    kind: str
    ref: str


@dataclass(frozen=True, slots=True)
class Handover:
    task_id: str
    issue_number: int
    from_role: Role
    to_role: Role
    input: str
    output: str
    evidence: tuple[Evidence, ...]
    attempt: int
    max_attempts: int
    gate: Gate

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "task_id": self.task_id, "issue_number": self.issue_number,
                "from_role": self.from_role.value, "to_role": self.to_role.value,
                "input": self.input, "output": self.output,
                "evidence": [{"kind": e.kind, "ref": e.ref} for e in self.evidence],
                "attempt": self.attempt, "max_attempts": self.max_attempts, "gate": self.gate.value}

    def render(self) -> str:
        """The fenced block as it stands in an issue or PR body."""
        return ("```json " + SCHEMA + "\n"
                + json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n```")


def _positive_int(value: Any, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise HandoverError(f"{name} must be a positive integer")
    return value


def _member(kind: type[StrEnum], value: Any, name: str) -> Any:
    if isinstance(value, str) and value in kind._value2member_map_:
        return kind(value)
    raise HandoverError(f"{name} must be one of {[m.value for m in kind]}")


def _evidence(value: Any) -> tuple[Evidence, ...]:
    if not isinstance(value, list) or not 0 < len(value) <= MAX_EVIDENCE:
        raise HandoverError(f"evidence must be a list of 1 to {MAX_EVIDENCE} entries")
    items = []
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"kind", "ref"}:
            raise HandoverError("each evidence entry needs exactly 'kind' and 'ref'")
        if entry["kind"] not in EVIDENCE_KINDS:
            raise HandoverError(f"evidence kind must be one of {list(EVIDENCE_KINDS)}")
        items.append(Evidence(entry["kind"], _checked_text(entry["ref"], "evidence ref", 500)))
    return tuple(items)


def _checked_text(value: Any, name: str, limit: int = 2000) -> str:
    try:
        return _text(value, name, limit)
    except ValueError as exc:
        raise HandoverError(str(exc)) from exc


def validate(data: Any) -> Handover:
    """Turn a decoded slip into a ``Handover`` or raise ``HandoverError`` with the first broken rule."""
    if not isinstance(data, dict):
        raise HandoverError("slip must be a JSON object")
    if set(data) != _KEYS:
        missing, extra = sorted(_KEYS - set(data)), sorted(set(data) - _KEYS)
        raise HandoverError(f"wrong fields: missing {missing}, unknown {extra}")
    if data["schema"] != SCHEMA:
        raise HandoverError(f"schema must be {SCHEMA}")
    try:
        task_id = _ident(data["task_id"], "task_id")
    except ValueError as exc:
        raise HandoverError(str(exc)) from exc
    issue_number = _positive_int(data["issue_number"], "issue_number")
    from_role = _member(Role, data["from_role"], "from_role")
    to_role = _member(Role, data["to_role"], "to_role")
    if from_role is to_role:
        raise HandoverError("from_role and to_role must differ: nobody hands over to themselves")
    evidence = _evidence(data["evidence"])
    needed = REQUIRED_EVIDENCE.get(from_role)
    if needed is not None and all(e.kind != needed for e in evidence):
        raise HandoverError(f"{from_role.value} must attach evidence of kind '{needed}'")
    attempt = _positive_int(data["attempt"], "attempt")
    max_attempts = _positive_int(data["max_attempts"], "max_attempts")
    if max_attempts > MAX_ATTEMPTS:
        raise HandoverError(f"max_attempts must not exceed {MAX_ATTEMPTS}")
    if attempt > max_attempts:
        raise HandoverError(f"attempt {attempt} exceeds max_attempts {max_attempts}: stop and report")
    return Handover(task_id, issue_number, from_role, to_role,
                    _checked_text(data["input"], "input"), _checked_text(data["output"], "output"),
                    evidence, attempt, max_attempts, _member(Gate, data["gate"], "gate"))


def parse(body: Any, issue_number: int | None = None) -> Handover:
    """Read the one slip in an issue or PR body. Two slips, none, or a foreign issue number are errors."""
    blocks = BLOCK.findall(body) if isinstance(body, str) else []
    if len(blocks) != 1:
        raise HandoverError(f"expected exactly one {SCHEMA} block, found {len(blocks)}")
    if len(blocks[0]) > MAX_BLOCK_CHARS:
        raise HandoverError(f"{SCHEMA} block is too large")
    try:
        data = json.loads(blocks[0])
        canonical_json(data)  # rejects NaN and Infinity, which json.loads accepts
    except (json.JSONDecodeError, ValueError) as exc:
        raise HandoverError(f"invalid {SCHEMA} JSON") from exc
    slip = validate(data)
    if issue_number is not None and slip.issue_number != issue_number:
        raise HandoverError("slip belongs to another issue")
    return slip


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m src.agents.handover FILE", file=sys.stderr)
        return 2
    try:
        with open(args[0], encoding="utf-8") as handle:
            slip = parse(handle.read())
    except (OSError, HandoverError) as exc:
        print(f"INVALID: {exc}")
        return 1
    print(f"VALID: {slip.task_id} {slip.from_role.value} -> {slip.to_role.value}, "
          f"attempt {slip.attempt}/{slip.max_attempts}, gate {slip.gate.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
