"""Read-only provenance inventory for V2-B05 (Historical Provenance).

Counts which provenance fields the research records carry and puts every
record of data/research/module_a_cache.jsonl into one class of the
remediation program (TIM_V2_REMEDIATION_PROGRAM.md, Workstream 5):

- COMPLETE_PROSPECTIVE: created at or after the V2 boundary, all required
  fields present, artifact_hash verifies.
- PARTIAL_LEGACY: created before the boundary, source fields present
  (provenance, input_hash, created_at) but the V2 fields missing.
  Retained and documented, never backfilled.
- NON_RECONSTRUCTABLE: source fields themselves missing or unreadable.
- CONFLICTING: a declared artifact_hash that does not verify, or a record
  after the boundary that still lacks a V2 field. Excluded from the
  qualifying scope until a human disposition.

The inventory never writes into data/research. It hashes every file before
and after the scan and reports whether the bytes stayed unchanged.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.research_ops.audit import digest, parse_time

SCHEMA = "tim_v2_provenance_inventory/1"
CACHE_RELATIVE = "data/research/module_a_cache.jsonl"
V2_FIELDS = ("artifact_hash", "generator_version", "schema_version")
SOURCE_FIELDS = ("provenance", "input_hash", "created_at")
# Checklist fields of Workstream 5 and the keys that satisfy them.
CHECKLIST = {
    "provenance": ("provenance", "source", "read_only_sources"),
    "input_hash": ("input_hash", "dataset_hash"),
    "artifact_hash": ("artifact_hash", "report_hash", "output_hash", "snapshot_hash", "audit_hash"),
    "schema_version": ("schema_version",),
    "generator_version": ("generator_version",),
    "generation_timestamp": ("generation_timestamp", "generated_at", "created_at", "timestamp"),
    "validation_status": ("validation_status", "status"),
}
CLASSES = ("COMPLETE_PROSPECTIVE", "PARTIAL_LEGACY", "NON_RECONSTRUCTABLE", "CONFLICTING")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _classify(row: dict[str, Any], boundary: datetime | None) -> str:
    created = parse_time(row.get("created_at"))
    if "artifact_hash" in row:
        copy = {k: v for k, v in row.items() if k != "artifact_hash"}
        if digest(copy) != row["artifact_hash"]:
            return "CONFLICTING"
    has_v2 = all(key in row for key in V2_FIELDS)
    has_source = all(row.get(key) for key in SOURCE_FIELDS) and created is not None
    if boundary is not None and created is not None and created >= boundary:
        return "COMPLETE_PROSPECTIVE" if has_v2 and has_source else "CONFLICTING"
    if not has_source:
        return "NON_RECONSTRUCTABLE"
    return "PARTIAL_LEGACY"


def first_complete_record(rows: list[dict[str, Any]]) -> datetime | None:
    """Earliest created_at of a record that carries all V2 fields."""
    times = [t for row in rows if all(k in row for k in V2_FIELDS) and (t := parse_time(row.get("created_at")))]
    return min(times) if times else None


def _read_cache(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    unreadable = 0
    if not path.is_file():
        return rows, unreadable
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            unreadable += 1
            continue
        if isinstance(value, dict):
            rows.append(value)
        else:
            unreadable += 1
    return rows, unreadable


def _artifact_fields(research_root: Path, root: Path) -> list[dict[str, Any]]:
    """Checklist field presence for every JSON artifact under data/research (audit dir excluded)."""
    result = []
    for path in sorted(research_root.rglob("*.json")):
        if "audit" in path.relative_to(research_root).parts:
            continue
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            result.append({"path": path.relative_to(root).as_posix(), "readable": False})
            continue
        if not isinstance(value, dict):
            result.append({"path": path.relative_to(root).as_posix(), "readable": False})
            continue
        present = {name: any(key in value for key in keys) for name, keys in CHECKLIST.items()}
        result.append({
            "path": path.relative_to(root).as_posix(),
            "readable": True,
            "present": sorted(k for k, v in present.items() if v),
            "missing": sorted(k for k, v in present.items() if not v),
        })
    return result


def build_inventory(root: Path, *, cutoff: datetime, boundary: datetime | None = None) -> dict[str, Any]:
    """Inventory as of cutoff. boundary=None derives it from the first complete record."""
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    root = root.resolve()
    research_root = root / "data/research"
    files = sorted(p for p in research_root.rglob("*") if p.is_file()) if research_root.is_dir() else []
    before = {p.relative_to(root).as_posix(): _sha256(p) for p in files}

    rows, unreadable = _read_cache(root / CACHE_RELATIVE)
    in_cutoff = [r for r in rows if (t := parse_time(r.get("created_at"))) is None or t <= cutoff]
    derived = boundary is None
    if boundary is None:
        boundary = first_complete_record(in_cutoff)
    classes = {name: 0 for name in CLASSES}
    for row in in_cutoff:
        classes[_classify(row, boundary)] += 1
    classes["NON_RECONSTRUCTABLE"] += unreadable
    field_counts = {key: sum(key in r for r in in_cutoff) for key in V2_FIELDS + SOURCE_FIELDS}
    prospective = sum(
        1 for r in in_cutoff
        if boundary is not None and (t := parse_time(r.get("created_at"))) is not None and t >= boundary
    )
    complete_pct = round(100 * classes["COMPLETE_PROSPECTIVE"] / prospective, 3) if prospective else None

    after = {p.relative_to(root).as_posix(): _sha256(p) for p in files if p.is_file()}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "schema_version": "1.0.0",
        "generator_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "OBSERVE",
        "read_only": True,
        "cutoff": cutoff.astimezone(timezone.utc).isoformat(),
        "v2_boundary": boundary.isoformat() if boundary else None,
        "v2_boundary_source": ("first record with all V2 fields" if boundary else "no record with all V2 fields yet") if derived else "given",
        "module_a_cache": {
            "path": CACHE_RELATIVE,
            "records": len(in_cutoff) + unreadable,
            "unreadable_lines": unreadable,
            "field_counts": field_counts,
            "classes": classes,
            "prospective_records": prospective,
            "prospective_complete_percent": complete_pct,
        },
        "artifacts": _artifact_fields(research_root, root) if research_root.is_dir() else [],
        "files_hashed": len(before),
        "bytes_unchanged": before == after,
        "rules": [
            "No historical record is rewritten or backfilled.",
            "PARTIAL_LEGACY stays a documented limitation.",
            "CONFLICTING records are excluded from the qualifying scope until a human disposition.",
            "The V2 boundary needs human approval (Research Lead / Governance Lead).",
        ],
    }
    payload["artifact_hash"] = digest(payload)
    return payload
