from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from src.v2_completion.backfill_candidate import (
    GapWindow,
    add_fixed_window_coverage,
    gap_minutes,
    load_gap_windows,
    required_archive_days,
    timestamp_from_binance,
)


UTC = timezone.utc


def gap(start: str, end: str, name: str = "g1") -> GapWindow:
    return GapWindow(
        gap_id=name,
        start=datetime.fromisoformat(start.replace("Z", "+00:00")),
        end=datetime.fromisoformat(end.replace("Z", "+00:00")),
        severity="P1",
        root_cause="PROCESS_DOWNTIME",
    )


def test_gap_minutes_are_start_inclusive_end_exclusive() -> None:
    item = gap("2026-07-23T23:59:00Z", "2026-07-24T00:02:00Z")
    assert len(item.minutes) == 3
    assert required_archive_days([item]) == [
        datetime(2026, 7, 23, tzinfo=UTC).date(),
        datetime(2026, 7, 24, tzinfo=UTC).date(),
    ]


def test_gap_minute_union_deduplicates_overlaps() -> None:
    values = gap_minutes(
        [
            gap("2026-07-23T00:00:00Z", "2026-07-23T00:02:00Z", "a"),
            gap("2026-07-23T00:01:00Z", "2026-07-23T00:03:00Z", "b"),
        ]
    )
    assert len(values) == 3


def test_binance_millisecond_and_microsecond_timestamps_match() -> None:
    milliseconds = "1784764800000"
    microseconds = "1784764800000000"
    assert timestamp_from_binance(milliseconds) == timestamp_from_binance(microseconds)


def test_binance_timestamp_parser_rejects_non_numeric_value() -> None:
    with pytest.raises(ValueError):
        timestamp_from_binance("not-a-timestamp")


def test_gap_ledger_rejects_duplicate_ids(tmp_path: Path) -> None:
    row = {
        "gap_id": "same",
        "start_utc": "2026-07-23T00:00:00Z",
        "end_utc": "2026-07-23T00:01:00Z",
        "severity": "P1",
        "root_cause_class": "PROCESS_DOWNTIME",
    }
    path = tmp_path / "gaps.jsonl"
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="duplicate gap IDs"):
        load_gap_windows(path)


def test_candidate_coverage_is_separate_and_not_promoted() -> None:
    manifest = {
        "candidate_minutes": 80,
        "gap_minutes": 100,
        "candidate_gap_recovery_coverage": 0.8,
        "readiness_counted": False,
    }
    baseline = {
        "coverage": {
            "product_calculation": {
                "window_start_utc": "2026-01-01T00:00:00Z",
                "window_end_utc": "2026-01-01T01:40:00Z",
                "expected_observations": 100,
                "valid_observations": 20,
                "coverage": 0.2,
            }
        }
    }
    add_fixed_window_coverage(manifest, baseline)
    assert manifest["readiness_counted"] is False
    assert manifest["coverage_metrics"]["frozen_live_capture"]["coverage"] == 0.2
    assert manifest["coverage_metrics"]["backfill_eligible_if_governance_approved"]["coverage"] == 1.0
