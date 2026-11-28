"""Persistent receipt and revision ledger (E2, Mission 06/07, #372): isolated draft, no recorder change.

``pit_contract.RevisionLog`` lives in memory: after a restart everything before is UNKNOWN. This ledger writes every
*new* revision of a bucket, with the moment TIM first held it, to an append-only JSON-lines file, so a restarted
consumer (or a later study) can still answer "which value of this bucket was known at t?" with real receipt times.

Record (one line, ``schema`` ``pit-ledger/1``)::

    {"schema": "pit-ledger/1", "source": "...", "symbol": "...", "day": "2026-11-24", "start": 1795000000.0,
     "level": 75000.0, "values": [1.0, 2.0], "seen_at": 1795000310.0, "seq": 17, "prev": "<sha256 of previous line>"}

Rules:

* Append only; a line is written and ``fsync``-ed before the in-memory view counts it. A half-written last line (crash)
  is cut off by a newline before the next append and skipped when read; it never counts.
* ``seq`` and ``prev`` (hash chain) make edits, deletions and reordering visible: :func:`verify` reports the first
  break. Nothing in the file is ever rewritten.
* ``seen_at`` never goes back per key: a revision observed with an older time than the last one of its key is refused.
* Receipt times are an upper bound of availability (the consumer held the store then), as in the contract.

Not wired into any runtime: the recorder and the live consumers are untouched (Uzi, Mission 06: "keine Änderung am
laufenden Recorder und keine Produktionsmigration"). Paths are given by the caller; there is no default under data/.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from src.orderflow.pit_contract import RevisionLog

SCHEMA = "pit-ledger/1"
GENESIS = "0" * 64


def _digest(line: bytes) -> str:
    return hashlib.sha256(line).hexdigest()


def read(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Records of the ledger and a check: ``{"ok", "records", "skipped_partial", "break"}``. Never raises on content."""
    records: list[dict[str, Any]] = []
    check = {"ok": True, "records": 0, "skipped_partial": 0, "break": None}
    target = Path(path)
    if not target.is_file():
        return records, check
    raw = target.read_bytes()
    lines = raw.split(b"\n")
    tail_partial = not raw.endswith(b"\n") and raw != b""
    prev = GENESIS
    for index, line in enumerate(lines):
        if not line:
            continue
        if index == len(lines) - 1 and tail_partial:
            check["skipped_partial"] += 1
            break
        try:
            record = json.loads(line)
        except ValueError:
            check["skipped_partial"] += 1      # a cut line in the middle: only after a crash and a later append
            continue
        if not isinstance(record, dict) or record.get("schema") != SCHEMA:
            check["ok"], check["break"] = False, check["break"] or {"line": index + 1, "why": "schema"}
            continue
        if record.get("prev") != prev or record.get("seq") != len(records):
            check["ok"], check["break"] = False, check["break"] or {"line": index + 1, "why": "chain"}
        prev = _digest(line)
        records.append(record)
    check["records"] = len(records)
    return records, check


def verify(path: Path) -> dict[str, Any]:
    """Only the check of :func:`read`."""
    return read(path)[1]


class PersistentRevisionLog:
    """``RevisionLog`` backed by an append-only ledger file for one source and symbol."""

    def __init__(self, path: Path, source: str, symbol: str, keep_seconds: float = 12 * 3600) -> None:
        self.path = Path(path)
        self.source, self.symbol = source, symbol.upper()
        self.memory = RevisionLog(keep_seconds=keep_seconds)
        self._last: dict[tuple[str, float, float], tuple[float, tuple[float, ...]]] = {}
        self._lock = Lock()
        self._prev, self._seq = GENESIS, 0
        records, self.check = read(self.path)
        for record in records:
            if record.get("source") != self.source or str(record.get("symbol", "")).upper() != self.symbol:
                continue
            self._remember(record)
        if records:
            last_line = [l for l in self.path.read_bytes().split(b"\n") if l]
            # the chain continues from the last complete record, never from a cut tail
            complete = [l for l in last_line if _is_record(l)]
            self._prev, self._seq = _digest(complete[-1]), len(records)

    def _remember(self, record: Mapping[str, Any]) -> None:
        key = (str(record["day"]), float(record["start"]), float(record["level"]))
        values = tuple(float(v) for v in record["values"])
        seen = float(record["seen_at"])
        self._last[key] = (seen, values)
        self.memory.observe({key[0]: [[key[1], key[2], *values]]}, datetime.fromtimestamp(seen, timezone.utc))

    def observe(self, days: Mapping[str, Iterable[Any]] | None, seen_at: datetime) -> int:
        """Append every bucket value that is new or changed since the last record of its key; returns how many."""
        if not days or seen_at.tzinfo is None:
            return 0
        seen = seen_at.timestamp()
        new: list[dict[str, Any]] = []
        with self._lock:
            for day, rows in days.items():
                for row in rows or ():
                    try:
                        key = (str(day), float(row[0]), float(row[1]))
                        values = tuple(float(v) for v in row[2:])
                    except (TypeError, ValueError, IndexError):
                        continue
                    if not all(math.isfinite(v) for v in (key[1], key[2], *values)):
                        continue
                    last = self._last.get(key)
                    if last is not None and (last[1] == values or seen < last[0]):
                        continue           # unchanged, or would go back in time
                    new.append({"schema": SCHEMA, "source": self.source, "symbol": self.symbol, "day": key[0],
                                "start": key[1], "level": key[2], "values": list(values), "seen_at": seen})
            if not new:
                return 0
            self._append(new)
            for record in new:
                self._remember(record)
        return len(new)

    def _append(self, records: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("ab") as fh:
            if fh.tell() and self.path.read_bytes()[-1:] != b"\n":
                fh.write(b"\n")                    # cut off a half-written line of a crash
            for record in records:
                record["seq"], record["prev"] = self._seq, self._prev
                line = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
                fh.write(line + b"\n")
                self._prev, self._seq = _digest(line), self._seq + 1
            fh.flush()
            os.fsync(fh.fileno())

    def rows_at(self, target: Any, bucket_seconds: float):
        """As :meth:`RevisionLog.rows_at`, with the knowledge of every earlier run of the ledger."""
        return self.memory.rows_at(target, bucket_seconds)


def _is_record(line: bytes) -> bool:
    try:
        return isinstance(json.loads(line), dict)
    except ValueError:
        return False
