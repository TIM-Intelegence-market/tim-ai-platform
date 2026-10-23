"""Append-only, hash-chained JSON-lines event log for the paper journals.

One line per event. Every event carries `seq`, `previous` (hash of the event
before it, GENESIS for the first) and `hash` over its own body, like the
hypothesis register in src.research_lab.stats.register. The file is the only
truth; views are folded from it. Rules:

- `append` is idempotent on `event_id`: an event that is already in the log is
  not written again and the call returns False.
- A broken chain (edited, reordered or deleted lines) raises LogError; callers
  must fail closed and never continue with an empty log.
- A truncated last line (crash while writing) is the one tolerated defect: it
  is dropped, reported in `read().dropped_tail`, and overwritten by the next
  append. Everything before it is still verified.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

GENESIS = "0" * 64
LOG_VERSION = "journal_log/1"


class LogError(ValueError):
    pass


def event_id(*parts: Any) -> str:
    """Deterministic identity of an event from its semantic parts."""
    return hashlib.sha256(json.dumps(list(parts), sort_keys=True, default=str).encode()).hexdigest()


def content_hash(value: Any) -> str:
    """Hash of any JSON-serialisable content (candles, payloads)."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _digest(previous: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class LogState:
    events: list[dict[str, Any]]
    head: str
    valid_bytes: int
    total_bytes: int = 0
    dropped_tail: str | None = None
    ids: set[str] = field(default_factory=set)


def read(path: Path) -> LogState:
    """All events with chain verification. Raises LogError on a broken chain."""
    if not path.exists():
        return LogState([], GENESIS, 0, 0)
    raw = path.read_bytes()
    events: list[dict[str, Any]] = []
    ids: set[str] = set()
    previous = GENESIS
    offset = 0
    dropped = None
    lines = raw.split(b"\n")
    for index, line in enumerate(lines):
        if not line.strip():
            offset += len(line) + 1
            continue
        try:
            event = json.loads(line)
        except ValueError:
            if index == len(lines) - 1 or (index == len(lines) - 2 and lines[-1] == b""):
                dropped = line[:120].decode("utf-8", "replace")
                break
            raise LogError(f"line {index + 1} is not JSON; the log was edited")
        if not isinstance(event, dict) or "hash" not in event:
            raise LogError(f"line {index + 1} is not an event")
        body = {k: v for k, v in event.items() if k != "hash"}
        if body.get("previous") != previous or body.get("seq") != len(events) or event["hash"] != _digest(previous, body):
            raise LogError(f"hash chain broken at seq {body.get('seq')}; the log was edited or reordered")
        if event["event_id"] in ids:
            raise LogError(f"duplicate event_id {event['event_id']} at seq {body.get('seq')}")
        events.append(event)
        ids.add(event["event_id"])
        previous = event["hash"]
        offset += len(line) + 1
    return LogState(events, previous, min(offset, len(raw)), len(raw), dropped, ids)


def append(path: Path, events: Iterable[dict[str, Any]], state: LogState | None = None) -> list[dict[str, Any]]:
    """Append events that are not yet in the log. Returns the written events.

    Each input needs `event_id` and `kind`; `seq`, `previous`, `hash` and
    `log_version` are added here. The file must still be exactly as `state`
    saw it: if another writer appended in the meantime, LogError is raised and
    nothing is written (the caller re-reads and re-derives its events). A
    dropped tail is overwritten; nothing else is ever truncated."""
    state = state or read(path)
    written: list[dict[str, Any]] = []
    previous, seq, ids = state.head, len(state.events), set(state.ids)
    lines: list[str] = []
    for event in events:
        if "event_id" not in event or "kind" not in event:
            raise LogError("events need event_id and kind")
        if event["event_id"] in ids:
            continue
        body = {**event, "seq": seq, "previous": previous, "log_version": LOG_VERSION}
        full = {**body, "hash": _digest(previous, body)}
        lines.append(json.dumps(full, sort_keys=True, default=str))
        written.append(full)
        ids.add(event["event_id"])
        previous, seq = full["hash"], seq + 1
    if not lines:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() != state.total_bytes:
            raise LogError("the log changed since it was read; re-read before appending")
        if state.dropped_tail is not None:
            handle.truncate(state.valid_bytes)
            handle.seek(state.valid_bytes)
        handle.write(("\n".join(lines) + "\n").encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    return written
