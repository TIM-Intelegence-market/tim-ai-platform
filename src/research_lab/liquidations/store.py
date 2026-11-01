"""Append-only raw store for S12 (pre-registration section 3.3).

Layout under the data root (default ``~/Library/Application Support/TIM/research-lab/liquidations``)::

    raw/<venue>/<YYYY-MM-DD>.jsonl          one JSON record per line, appended with one write each
    raw/<venue>/<YYYY-MM-DD>.manifest.json  written for closed days by ``write_manifest``
    snapshots/<YYYY-MM-DD>/<HHMM>.json.gz   frozen heatmap inputs (``snapshots``)

Record kinds: ``connect``, ``message`` (raw text unchanged plus its SHA-256), ``alive`` (written
once a minute after a websocket ping got its pong), ``disconnect`` (with the reason),
``connect_failed`` (a connection attempt that never opened). The day of a record is
the UTC day of its local receive time. Files are only ever appended to; nothing is rewritten. Plain text, so a line cut off by a crash
only loses that line (``read_records`` skips and counts it); later lines stay readable.

A feed without messages is not zero: a stretch only counts as covered between two proofs of life
of the same session (any record) at most 90 s apart (``connected_intervals``).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

DEFAULT_ROOT = Path.home() / "Library" / "Application Support" / "TIM" / "research-lab" / "liquidations"
KINDS = frozenset({"connect", "message", "alive", "disconnect", "connect_failed"})
NS_PER_S = 1_000_000_000
ALIVE_SECONDS = 60
MAX_PROOF_GAP_NS = 75 * NS_PER_S  # alive every 60 s plus up to 10 s pong wait and slack


def data_root(value: str | os.PathLike[str] | None = None) -> Path:
    if value:
        return Path(value).expanduser()
    env = os.environ.get("TIM_S12_DATA_DIR")
    return Path(env).expanduser() if env else DEFAULT_ROOT


def utc_day(receive_ns: int) -> date:
    return datetime.fromtimestamp(receive_ns / NS_PER_S, tz=timezone.utc).date()


def raw_path(root: Path, venue: str, day: date) -> Path:
    return root / "raw" / venue / f"{day.isoformat()}.jsonl"


def make_record(kind: str, venue: str, session_id: str, receive_ns: int, mono_ns: int,
                payload: str | None = None, note: str | None = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"unknown record kind {kind!r}")
    record: dict[str, Any] = {"kind": kind, "venue": venue, "session_id": session_id,
                              "receive_ns": receive_ns, "mono_ns": mono_ns}
    if payload is not None:
        record["payload"] = payload
        record["payload_sha256"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if note is not None:
        record["note"] = note
    return record


def append(root: Path, record: dict[str, Any]) -> Path:
    """Append one record as one line with a single ``O_APPEND`` write (a crash loses at most it).

    A line that does not end with a newline (cut off earlier) is closed first, so the new record
    always starts on its own line.
    """
    path = raw_path(root, record["venue"], utc_day(int(record["receive_ns"])))
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, separators=(",", ":"), sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        size = os.fstat(fd).st_size
        if size:
            with open(path, "rb") as handle:
                handle.seek(size - 1)
                if handle.read(1) != b"\n":
                    line = b"\n" + line
        os.write(fd, line)
    finally:
        os.close(fd)
    return path


def read_records(path: Path, bad: list[int] | None = None) -> Iterator[dict[str, Any]]:
    """Records of one day file. Lines that are not a complete record are skipped; their line
    numbers go to ``bad`` when given (the manifest reports them)."""
    with open(path, "rb") as handle:
        for number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                record = json.loads(raw.decode("ascii"))
            except (UnicodeDecodeError, ValueError):
                record = None
            if not isinstance(record, dict) or record.get("kind") not in KINDS or "receive_ns" not in record:
                if bad is not None:
                    bad.append(number)
                continue
            yield record


def check_payload(record: dict[str, Any]) -> bool:
    payload = record.get("payload")
    if payload is None:
        return "payload_sha256" not in record
    return hashlib.sha256(payload.encode("utf-8")).hexdigest() == record.get("payload_sha256")


def records_between(root: Path, venue: str, start_ns: int, end_ns: int) -> list[dict[str, Any]]:
    """All records of ``venue`` with ``start_ns <= receive_ns < end_ns``, sorted by receive time."""
    first, last = utc_day(start_ns), utc_day(max(start_ns, end_ns - 1))
    days = [date.fromordinal(n) for n in range(first.toordinal() - 1, last.toordinal() + 2)]
    result = []
    for day in days:
        path = raw_path(root, venue, day)
        if path.exists():
            result.extend(r for r in read_records(path) if start_ns <= int(r["receive_ns"]) < end_ns)
    result.sort(key=lambda r: (int(r["receive_ns"]), int(r.get("mono_ns", 0))))
    return result


@dataclass(frozen=True)
class Interval:
    start_ns: int
    end_ns: int


def connected_intervals(records: Iterable[dict[str, Any]], max_gap_ns: int = MAX_PROOF_GAP_NS) -> list[Interval]:
    """Covered stretches between consecutive proofs of life of one session.

    Every record of a session (``connect``, ``message``, ``alive``, ``disconnect``) proves the
    socket was open at its receive time. Two consecutive proofs of the same session no more than
    ``max_gap_ns`` apart cover the time between them. A ``disconnect`` ends the session; a crash
    without one simply stops the proofs. No connect record before a window is needed.
    """
    intervals: list[Interval] = []
    previous: dict[str, int] = {}
    closed: set[str] = set()
    for record in sorted(records, key=lambda r: (int(r["receive_ns"]), int(r.get("mono_ns", 0)))):
        sid, ts = record.get("session_id"), int(record["receive_ns"])
        if not isinstance(sid, str) or sid in closed or record["kind"] == "connect_failed":
            continue
        before = previous.get(sid)
        if before is not None and 0 < ts - before <= max_gap_ns:
            intervals.append(Interval(before, ts))
        previous[sid] = ts
        if record["kind"] == "disconnect":
            closed.add(sid)
    return intervals


def coverage(intervals: Iterable[Interval], start_ns: int, end_ns: int) -> float:
    """Share of ``[start_ns, end_ns)`` covered by the (possibly overlapping) intervals."""
    if end_ns <= start_ns:
        raise ValueError("coverage: empty window")
    clipped = sorted((max(i.start_ns, start_ns), min(i.end_ns, end_ns)) for i in intervals)
    covered, cursor = 0, start_ns
    for lo, hi in clipped:
        if hi <= cursor:
            continue
        lo = max(lo, cursor)
        if hi > lo:
            covered += hi - lo
            cursor = hi
    return covered / (end_ns - start_ns)


def gaps(intervals: Iterable[Interval], start_ns: int, end_ns: int) -> list[tuple[int, int]]:
    """Uncovered stretches of ``[start_ns, end_ns)``, in time order."""
    result, cursor = [], start_ns
    for lo, hi in sorted((max(i.start_ns, start_ns), min(i.end_ns, end_ns)) for i in intervals):
        if hi <= cursor:
            continue
        if lo > cursor:
            result.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < end_ns:
        result.append((cursor, end_ns))
    return result


def manifest(root: Path, venue: str, day: date) -> dict[str, Any]:
    path = raw_path(root, venue, day)
    if not path.exists():
        return {"venue": venue, "day": day.isoformat(), "exists": False}
    data = path.read_bytes()
    bad_lines: list[int] = []
    records = list(read_records(path, bad_lines))
    kinds: dict[str, int] = {}
    for record in records:
        kinds[record["kind"]] = kinds.get(record["kind"], 0) + 1
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()) * NS_PER_S
    end = start + 86_400 * NS_PER_S
    context = records_between(root, venue, start - MAX_PROOF_GAP_NS, end + MAX_PROOF_GAP_NS)
    return {
        "venue": venue,
        "day": day.isoformat(),
        "exists": True,
        "file": path.name,
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "records": len(records),
        "kinds": dict(sorted(kinds.items())),
        "sessions": sorted({r["session_id"] for r in records if r["kind"] == "connect"}),
        "disconnects": [{"receive_ns": r["receive_ns"], "note": r.get("note")} for r in records if r["kind"] == "disconnect"],
        "bad_payload_hashes": sum(1 for r in records if not check_payload(r)),
        "bad_lines": bad_lines,
        "connect_failed": kinds.get("connect_failed", 0),
        "coverage": round(coverage(connected_intervals(context), start, end), 6),
        "gaps": [{"start_ns": lo, "end_ns": hi, "seconds": round((hi - lo) / NS_PER_S, 1)}
                 for lo, hi in gaps(connected_intervals(context), start, end)],
    }


def write_manifest(root: Path, venue: str, day: date) -> Path:
    """Write the manifest of a closed day once; an existing manifest is never replaced."""
    target = raw_path(root, venue, day).with_name(f"{day.isoformat()}.manifest.json")
    if target.exists():
        return target
    target.write_text(json.dumps(manifest(root, venue, day), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
