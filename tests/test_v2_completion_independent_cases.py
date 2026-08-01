from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.v2_completion.independent_cases import (
    CanonicalIndependentUnit,
    build_review_workbook,
    validate_independent_units,
    validate_review_workbook,
)


UTC = timezone.utc


def unit(index: int, *, start_minute: int, sample_class: str = "POSITIVE") -> CanonicalIndependentUnit:
    start = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(minutes=start_minute)
    return CanonicalIndependentUnit(
        unit_id=f"unit-{index}",
        start_utc=start,
        end_utc=start + timedelta(minutes=30),
        source_window=f"BTCUSDT:{start.isoformat()}",
        data_complete=True,
        gap_exposure=False,
        observation_id=f"obs-{index}" if sample_class == "POSITIVE" else None,
        label="RISING_CVD_ACTIVITY" if sample_class == "POSITIVE" else sample_class,
        sample_class=sample_class,
        volatility_regime="MEDIUM",
        liquidity_regime="MEDIUM",
        session="EUROPE",
        weekday="SATURDAY",
        trend_regime="RANGE",
        reviewer_id=None,
        provenance="PUBLIC_BINANCE_SPOT",
        input_hash=f"{index:064x}",
    )


def test_canonical_units_reject_overlap_and_duplicate_input() -> None:
    left = unit(1, start_minute=0)
    right = unit(2, start_minute=15)
    value = validate_independent_units([left, right])
    assert value["gate_status"] == "FAIL"
    assert value["overlaps"]


def test_canonical_units_accept_balanced_non_overlapping_classes() -> None:
    value = validate_independent_units(
        [
            unit(1, start_minute=0, sample_class="POSITIVE"),
            unit(2, start_minute=30, sample_class="NEGATIVE"),
            unit(3, start_minute=60, sample_class="NEUTRAL_CONTROL"),
        ]
    )
    assert value["gate_status"] == "PASS"
    assert value["sample_class_counts"] == {
        "NEGATIVE": 1,
        "NEUTRAL_CONTROL": 1,
        "POSITIVE": 1,
    }


def test_manual_workbook_contains_no_simulated_human_decision() -> None:
    sample = {
        "sample_hash": "a" * 64,
        "manifest_hash": "b" * 64,
        "selected_cases": [
            {
                "selection_rank": 1,
                "observation_id": "obs-1",
                "case_id": "case-1",
                "source_window_signature": "window-1",
                "observed_at_utc": "2026-08-01T00:00:00Z",
                "validated_through_utc": "2026-08-01T00:30:00Z",
                "observation_kind": "RISING_CVD_ACTIVITY",
                "outcome": "PRICE_INCREASED",
                "input_hash": "a" * 64,
                "validation_hash": "b" * 64,
            }
        ],
    }
    workbook = build_review_workbook(sample)
    check = validate_review_workbook(workbook)
    assert check["complete_human_decisions"] == 0
    assert check["approval"] is False
    assert check["status"] == "PENDING_OR_FAIL"
