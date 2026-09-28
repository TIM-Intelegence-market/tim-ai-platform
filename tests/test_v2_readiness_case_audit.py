from datetime import datetime, timedelta, timezone

from src.v2_readiness.case_audit import ValidatedCaseRecord, audit_validated_cases


UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def record(
    index: int,
    *,
    minute: int | None = None,
    horizons: tuple[int, ...] = (5, 15, 30),
    source_gap: bool = False,
) -> ValidatedCaseRecord:
    observed = BASE + timedelta(minutes=index if minute is None else minute)
    return ValidatedCaseRecord(
        observation_id=f"obs-{index}",
        observed_at=observed,
        validated_through=observed + timedelta(minutes=30),
        kind="RISING_CVD_ACTIVITY",
        outcome="PRICE_INCREASED",
        input_hash=f"{index:064x}",
        horizon_minutes=horizons,
        source_gap_overlap=source_gap,
        case_present=True,
        case_closed=True,
        case_outcome_matches=True,
        provenance_complete=True,
    )


def test_case_gate_counts_strict_non_overlapping_quality_windows() -> None:
    result = audit_validated_cases(
        [record(0), record(1), record(2), record(30), record(60)],
        required_independent_cases=3,
    )
    assert result["raw_complete_validation_rows"] == 5
    assert result["strict_independent_30m_windows"] == 3
    assert result["gate_status"] == "PASS"


def test_same_timestamp_labels_are_not_independent_cases() -> None:
    result = audit_validated_cases(
        [record(1, minute=0), record(2, minute=0), record(3, minute=30)],
        required_independent_cases=3,
    )
    assert result["unique_observation_ids"] == 3
    assert result["unique_underlying_observation_times"] == 2
    assert result["strict_independent_30m_windows"] == 2
    assert result["gate_status"] == "FAIL"


def test_missing_horizon_or_source_gap_fails_quality_screen() -> None:
    result = audit_validated_cases(
        [record(1, horizons=(5, 30)), record(2, minute=30, source_gap=True)],
        required_independent_cases=1,
    )
    assert result["horizon_incomplete"] == 1
    assert result["source_gap_overlap"] == 1
    assert result["quality_eligible_labels"] == 0
    assert result["gate_status"] == "FAIL"


def test_duplicate_observation_id_is_detected() -> None:
    item = record(1)
    result = audit_validated_cases([item, item], required_independent_cases=1)
    assert result["duplicate_observation_id_count"] == 1
    assert result["gate_status"] == "FAIL"
