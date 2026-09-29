"""Agent contract V1: AgentSpec, TaskRecord, Message and deterministic replay.

Constitution Band 5 requires that agents communicate only through tasks and
messages, and Master Prompt 09 requires a contract per agent (mission, owner,
allowed/forbidden actions, tools, budget, timeout). This module is the single
code form of those rules for new agents.

Design limits, stated so nothing is hidden:
- Payloads (task input/output, message payload) are stored as canonical JSON
  text. Values that are not plain JSON are rejected, never stringified.
- ``timeout_seconds`` is declared, not enforced here: a synchronous handler
  cannot be stopped safely in-process. The caller (CLI, workflow job) enforces
  it. ``max_input_bytes`` is enforced before any handler runs.
- The bugfixer keeps its own task model (src/bugfixer/tasks.py); aligning the
  two is separate work.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Mapping

from src.agent_infra.profiles import COMMON_FORBIDDEN

SCHEMA_VERSION = "1.0.0"

_SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")
_PRIORITIES = ("P0", "P1", "P2", "P3")
MAX_TIMEOUT_SECONDS = 3600.0
MAX_INPUT_BYTES = 16 * 1024 * 1024


class PolicyViolation(RuntimeError):
    """An action or budget outside the agent's declared contract. Ends the task."""


class ReplayMismatch(RuntimeError):
    """A recorded run could not be reproduced exactly."""


def canonical_json(value: Any) -> str:
    """Canonical JSON text; raises TypeError/ValueError for non-JSON values."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    return value


def _ident(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _IDENT.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _text(value: Any, name: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be non-empty text up to {limit} characters")
    return value


def _names(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise ValueError(f"{name} must be a tuple")
    for item in value:
        _ident(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicates")
    return value


def _mapping_json(value: Any, name: str) -> str:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    return canonical_json(dict(value))


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """Least-privilege contract of one agent. Routing never changes it."""

    name: str
    version: str
    mission: str
    owner: str
    allowed_actions: tuple[str, ...]
    tools: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = COMMON_FORBIDDEN
    max_input_bytes: int = 1_000_000
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        _ident(self.name, "agent name")
        if not isinstance(self.version, str) or not _SEMVER.fullmatch(self.version):
            raise ValueError("agent version must be semantic (MAJOR.MINOR.PATCH)")
        _text(self.mission, "mission")
        _ident(self.owner, "owner")
        _names(self.allowed_actions, "allowed_actions")
        _names(self.tools, "tools")
        _names(self.forbidden_actions, "forbidden_actions")
        if not self.allowed_actions:
            raise ValueError("an agent must declare at least one allowed action")
        missing = set(COMMON_FORBIDDEN) - set(self.forbidden_actions)
        if missing:
            raise ValueError(f"common forbidden actions cannot be removed: {sorted(missing)}")
        overlap = set(self.allowed_actions) & set(self.forbidden_actions)
        if overlap:
            raise ValueError(f"actions both allowed and forbidden: {sorted(overlap)}")
        if type(self.max_input_bytes) is not int or not 0 < self.max_input_bytes <= MAX_INPUT_BYTES:
            raise ValueError("max_input_bytes out of range")
        if (isinstance(self.timeout_seconds, bool)
                or not isinstance(self.timeout_seconds, (int, float))
                or not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS):
            raise ValueError("timeout_seconds out of range")

    def authorize(self, action: str) -> None:
        if action in self.forbidden_actions:
            raise PolicyViolation(f"{self.name}: action '{action}' is forbidden")
        if action not in self.allowed_actions:
            raise PolicyViolation(f"{self.name}: action '{action}' is not granted")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "version": self.version, "mission": self.mission,
            "owner": self.owner, "allowed_actions": list(self.allowed_actions),
            "tools": list(self.tools), "forbidden_actions": list(self.forbidden_actions),
            "max_input_bytes": self.max_input_bytes, "timeout_seconds": self.timeout_seconds,
        }

    @property
    def spec_hash(self) -> str:
        return content_hash(self.to_dict())


class TaskStatus(StrEnum):
    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


_NEXT: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.NEW: frozenset({TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset({TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.BLOCKED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.FAILED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}
_NOTE_REQUIRED = frozenset({TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.CANCELLED})


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    status: TaskStatus
    at: str
    note: str

    def __post_init__(self) -> None:
        TaskStatus(self.status)
        _timestamp(self.at, "history timestamp")
        if not isinstance(self.note, str) or len(self.note) > 2000:
            raise ValueError("history note must be text up to 2000 characters")


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """Versioned canonical task record. Every change yields a new revision."""

    task_id: str
    owner: str
    priority: str
    deadline: str | None
    dependencies: tuple[str, ...]
    input_json: str
    output_json: str | None
    status: TaskStatus
    history: tuple[HistoryEntry, ...]
    revision: int
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _ident(self.task_id, "task_id")
        _ident(self.owner, "owner")
        if self.priority not in _PRIORITIES:
            raise ValueError("priority must be one of P0..P3")
        if self.deadline is not None:
            _timestamp(self.deadline, "deadline")
        _names(self.dependencies, "dependencies")
        if self.task_id in self.dependencies:
            raise ValueError("a task cannot depend on itself")
        if self.input_json != _mapping_json(json.loads(self.input_json), "input"):
            raise ValueError("input must be canonical JSON")
        if self.output_json is not None and self.output_json != _mapping_json(
                json.loads(self.output_json), "output"):
            raise ValueError("output must be canonical JSON")
        TaskStatus(self.status)
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported task schema version")
        if not self.history or self.history[0].status != TaskStatus.NEW:
            raise ValueError("history must start with NEW")
        for previous, current in zip(self.history, self.history[1:]):
            if current.status not in _NEXT[previous.status]:
                raise ValueError("history contains an invalid transition")
        if type(self.revision) is not int or self.history[-1].status != self.status \
                or self.revision != len(self.history):
            raise ValueError("status/revision do not match history")
        if (self.status == TaskStatus.DONE) != (self.output_json is not None):
            raise ValueError("output is required exactly when the task is DONE")

    @classmethod
    def new(cls, task_id: str, owner: str, task_input: Mapping[str, Any], *,
            priority: str = "P2", deadline: str | None = None,
            dependencies: tuple[str, ...] = (), at: str | None = None) -> TaskRecord:
        created = HistoryEntry(TaskStatus.NEW, _utc_now() if at is None else at, "created")
        return cls(task_id, owner, priority, deadline, dependencies,
                   _mapping_json(task_input, "input"), None, TaskStatus.NEW,
                   (created,), 1)

    @property
    def input(self) -> dict[str, Any]:
        return json.loads(self.input_json)

    @property
    def output(self) -> dict[str, Any] | None:
        return None if self.output_json is None else json.loads(self.output_json)

    def transition(self, target: TaskStatus | str, *, note: str = "",
                   output: Mapping[str, Any] | None = None,
                   at: str | None = None) -> TaskRecord:
        target = TaskStatus(target)
        if target not in _NEXT[self.status]:
            raise ValueError(f"invalid transition {self.status} -> {target}")
        if target in _NOTE_REQUIRED and not note.strip():
            raise ValueError(f"a note is required for {target}")
        if (target == TaskStatus.DONE) != (output is not None):
            raise ValueError("output is required exactly when the task is DONE")
        entry = HistoryEntry(target, _utc_now() if at is None else at, note)
        return TaskRecord(
            self.task_id, self.owner, self.priority, self.deadline, self.dependencies,
            self.input_json, None if output is None else _mapping_json(output, "output"),
            target, (*self.history, entry), self.revision + 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "task_id": self.task_id,
            "owner": self.owner, "priority": self.priority, "deadline": self.deadline,
            "dependencies": list(self.dependencies), "input": self.input,
            "output": self.output, "status": self.status.value,
            "history": [{"status": h.status.value, "at": h.at, "note": h.note}
                        for h in self.history],
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> TaskRecord:
        output = value["output"]
        return cls(
            value["task_id"], value["owner"], value["priority"], value["deadline"],
            tuple(value["dependencies"]), _mapping_json(value["input"], "input"),
            None if output is None else _mapping_json(output, "output"),
            TaskStatus(value["status"]),
            tuple(HistoryEntry(TaskStatus(h["status"]), h["at"], h["note"])
                  for h in value["history"]),
            value["revision"], value["schema_version"])

    @property
    def record_hash(self) -> str:
        return content_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class Message:
    """Immutable, hashed message. Construction fails if the hash does not match."""

    sender: str
    recipient: str
    timestamp: str
    schema: str
    payload_json: str
    correlation_id: str
    hash: str
    version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _ident(self.sender, "sender")
        _ident(self.recipient, "recipient")
        _timestamp(self.timestamp, "timestamp")
        _ident(self.schema, "schema")
        _ident(self.correlation_id, "correlation_id")
        if self.version != SCHEMA_VERSION:
            raise ValueError("unsupported message version")
        if len(self.payload_json.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError("payload exceeds the message size limit")
        if self.payload_json != _mapping_json(json.loads(self.payload_json), "payload"):
            raise ValueError("payload must be canonical JSON")
        if self.hash != self._compute_hash():
            raise ValueError("message hash does not match its content")

    def _body(self) -> dict[str, Any]:
        return {
            "sender": self.sender, "recipient": self.recipient,
            "timestamp": self.timestamp, "schema": self.schema,
            "payload": json.loads(self.payload_json),
            "correlation_id": self.correlation_id, "version": self.version,
        }

    def _compute_hash(self) -> str:
        return content_hash(self._body())

    @classmethod
    def create(cls, sender: str, recipient: str, schema: str,
               payload: Mapping[str, Any], correlation_id: str, *,
               timestamp: str | None = None) -> Message:
        payload_json = _mapping_json(payload, "payload")
        timestamp = _utc_now() if timestamp is None else timestamp
        body = {"sender": sender, "recipient": recipient, "timestamp": timestamp,
                "schema": schema, "payload": json.loads(payload_json),
                "correlation_id": correlation_id, "version": SCHEMA_VERSION}
        return cls(sender, recipient, timestamp, schema, payload_json,
                   correlation_id, content_hash(body))

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json)

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "hash": self.hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Message:
        return cls(value["sender"], value["recipient"], value["timestamp"],
                   value["schema"], _mapping_json(value["payload"], "payload"),
                   value["correlation_id"], value["hash"], value["version"])


@dataclass(frozen=True, slots=True)
class RunRecord:
    """What an agent was given and what it returned. No wall-clock fields."""

    agent: str
    agent_version: str
    spec_hash: str
    action: str
    input_json: str
    input_hash: str
    output_json: str
    output_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent, "agent_version": self.agent_version,
            "spec_hash": self.spec_hash, "action": self.action,
            "input": json.loads(self.input_json), "input_hash": self.input_hash,
            "output": json.loads(self.output_json), "output_hash": self.output_hash,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> RunRecord:
        input_json = _mapping_json(value["input"], "input")
        output_json = _mapping_json(value["output"], "output")
        record = cls(value["agent"], value["agent_version"], value["spec_hash"],
                     value["action"], input_json, value["input_hash"],
                     output_json, value["output_hash"])
        if content_hash(json.loads(input_json)) != record.input_hash:
            raise ReplayMismatch("recorded input does not match its hash")
        if content_hash(json.loads(output_json)) != record.output_hash:
            raise ReplayMismatch("recorded output does not match its hash")
        return record


Handler = Callable[[dict[str, Any]], Mapping[str, Any]]


def run_task(spec: AgentSpec, handler: Handler, task_input: Mapping[str, Any], *,
             action: str) -> RunRecord:
    """Authorize, enforce the input budget, run the handler, record the result."""
    spec.authorize(action)
    input_json = _mapping_json(task_input, "input")
    if len(input_json.encode("utf-8")) > spec.max_input_bytes:
        raise PolicyViolation(f"{spec.name}: input exceeds max_input_bytes")
    output = handler(json.loads(input_json))
    output_json = _mapping_json(output, "output")
    return RunRecord(spec.name, spec.version, spec.spec_hash, action,
                     input_json, content_hash(json.loads(input_json)),
                     output_json, content_hash(json.loads(output_json)))


def replay(spec: AgentSpec, handler: Handler, record: RunRecord) -> RunRecord:
    """Re-run a recorded input and require a byte-identical output."""
    if (record.agent, record.agent_version, record.spec_hash) != (
            spec.name, spec.version, spec.spec_hash):
        raise ReplayMismatch("record was produced by a different agent or spec version")
    fresh = run_task(spec, handler, json.loads(record.input_json), action=record.action)
    if fresh.input_hash != record.input_hash:
        raise ReplayMismatch("replayed input differs from the record")
    if fresh.output_hash != record.output_hash:
        raise ReplayMismatch("replayed output differs from the record")
    return fresh
