"""Shared pieces of the Mac -> server archive sync (plan #285, package S1).

Nothing in this package is scheduled or started automatically. The importer writes only into
its own schema (default ``archive_mac``) and refuses ``public``; the exporter only reads.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

FORMAT = "tim-archive-batch/1"
DEFAULT_SCHEMA = "archive_mac"
SOURCE_VALUE = "BINANCE_SPOT_AGGTRADE"
KINDS = ("new", "backfill", "prefix")
# Column order is part of the content hash: the same rows always give the same bytes.
COLUMNS = (
    "symbol",
    "aggregate_trade_id",
    "trade_time",
    "price",
    "quantity",
    "buyer_is_maker",
    "source",
    "ingest_timestamp",
)
# Output settings that fix the canonical text form, set locally in every hashing transaction.
CANONICAL_SETTINGS = (
    "SET LOCAL TIME ZONE 'UTC'",
    "SET LOCAL datestyle = 'ISO, YMD'",
    "SET LOCAL extra_float_digits = 1",
)
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
MIN_FREE_RATIO = 0.15


class ArchiveSyncError(RuntimeError):
    """A sync step refused to continue; nothing was written by the failing step."""


def checked_schema(name: str, *, allow_public: bool = False) -> str:
    if not _SCHEMA_NAME.match(name or ""):
        raise ArchiveSyncError(f"invalid schema name: {name!r}")
    if name in {"public", "pg_catalog", "information_schema"} and not allow_public:
        raise ArchiveSyncError(f"refusing schema {name!r}: the archive never writes there")
    return name


def canonical_select(table: str, where: str) -> str:
    """The one query whose CSV output defines a batch's content hash, on both sides.

    The caller must run it after ``CANONICAL_SETTINGS``: UTC, ISO dates and the shortest
    exact float form (PostgreSQL 12+), so the bytes are identical on 16 and 18.
    """
    return f"SELECT {', '.join(COLUMNS)} FROM {table} WHERE {where} ORDER BY aggregate_trade_id"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def batch_id_for(kind: str, symbol: str, lo: int, hi: int, content_sha256: str, holes: Iterable[Iterable[int]]) -> str:
    payload = {
        "format": FORMAT,
        "kind": kind,
        "symbol": symbol,
        "lo": int(lo),
        "hi": int(hi),
        "content_sha256": content_sha256,
        "holes": [[int(a), int(b)] for a, b in holes],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def normalise_holes(holes: Iterable[Iterable[int]], lo: int, hi: int) -> list[list[int]]:
    """Validate a hole list: sorted, disjoint, non-adjacent and inside [lo, hi]."""
    result: list[list[int]] = []
    previous_hi: int | None = None
    for raw in holes:
        a, b = (int(value) for value in raw)
        if a > b or a < lo or b > hi:
            raise ArchiveSyncError(f"hole {a}-{b} outside batch {lo}-{hi}")
        if previous_hi is not None and a <= previous_hi + 1:
            raise ArchiveSyncError("holes must be sorted, disjoint and not adjacent")
        result.append([a, b])
        previous_hi = b
    return result


def hole_size(holes: Iterable[Iterable[int]]) -> int:
    return sum(int(b) - int(a) + 1 for a, b in holes)


@dataclass(frozen=True)
class DiskGate:
    path: str
    total_bytes: int
    free_bytes: int
    needed_bytes: int
    min_free_ratio: float

    @property
    def free_after_ratio(self) -> float:
        return (self.free_bytes - self.needed_bytes) / self.total_bytes if self.total_bytes else 0.0

    @property
    def passed(self) -> bool:
        return self.total_bytes > 0 and self.free_after_ratio >= self.min_free_ratio

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "total_bytes": self.total_bytes,
            "free_bytes": self.free_bytes,
            "needed_bytes": self.needed_bytes,
            "free_after_ratio": round(self.free_after_ratio, 4),
            "min_free_ratio": self.min_free_ratio,
            "passed": self.passed,
        }


def disk_gate(
    path: str | Path,
    needed_bytes: int,
    *,
    min_free_ratio: float = MIN_FREE_RATIO,
    usage: Callable[[str], Any] = shutil.disk_usage,
) -> DiskGate:
    stats = usage(str(path))
    return DiskGate(str(path), int(stats.total), int(stats.free), max(0, int(needed_bytes)), min_free_ratio)


def require_disk(gate: DiskGate) -> None:
    if not gate.passed:
        raise ArchiveSyncError(
            f"disk gate failed at {gate.path}: {gate.free_after_ratio:.1%} free after write, "
            f"need {gate.min_free_ratio:.0%}"
        )


def write_json_atomic(path: Path, payload: Any) -> None:
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
