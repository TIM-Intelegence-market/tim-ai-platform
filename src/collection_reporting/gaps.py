from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


GAP_CATEGORIES = {
    "TRUE_MISSING_DATA",
    "SOURCE_DOWNTIME",
    "RECOVERABLE_BACKFILL",
    "ALREADY_RECONSTRUCTED",
    "FALSE_POSITIVE",
    "STRUCTURAL_EXPECTED",
}


@dataclass(frozen=True, slots=True)
class MissingRange:
    missing_from_id: int
    missing_to_id: int
    missing_records: int
    category: str = "RECOVERABLE_BACKFILL"
    action: str = "DEFER_UNTIL_BOUNDED_BACKFILL_IS_APPROVED"
    data_quality_impact: str = "CONTINUOUS_COVERAGE_NOT_ESTABLISHED"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def missing_ranges(
    present_ids: Iterable[int], *, marker_from_id: int, marker_to_id: int
) -> list[MissingRange]:
    """Return the disjoint holes inside a marker union without changing data."""
    if marker_from_id < 0 or marker_to_id < marker_from_id:
        raise ValueError("invalid marker range")
    ordered = sorted({int(value) for value in present_ids if marker_from_id <= int(value) <= marker_to_id})
    if not ordered:
        return [MissingRange(marker_from_id, marker_to_id, marker_to_id - marker_from_id + 1)]
    result: list[MissingRange] = []
    expected = marker_from_id
    for current in ordered:
        if current > expected:
            result.append(MissingRange(expected, current - 1, current - expected))
        expected = current + 1
    if expected <= marker_to_id:
        result.append(MissingRange(expected, marker_to_id, marker_to_id - expected + 1))
    return result


def load_gap_classification(
    path: Path, *, symbol: str, raw_marker_count: int
) -> dict[str, object] | None:
    """Load complete, untampered, read-only gap-classification evidence."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("symbol") != symbol:
        return None
    if payload.get("mode") != "OBSERVE" or payload.get("read_only_database") is not True:
        return None
    if int(payload.get("database_rows_written", -1)) != 0:
        return None
    if int(payload.get("raw_markers", -1)) != raw_marker_count:
        return None
    ranges = payload.get("ranges")
    if not isinstance(ranges, list) or int(payload.get("canonical_ranges", -1)) != len(ranges):
        return None
    if int(payload.get("unknown_gaps", -1)) != 0:
        return None
    if any(not isinstance(item, dict) or item.get("category") not in GAP_CATEGORIES for item in ranges):
        return None
    supplied = payload.get("classification_hash")
    material = dict(payload)
    material.pop("generated_at", None)
    material.pop("classification_hash", None)
    actual = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return payload if supplied == actual else None
