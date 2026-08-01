from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.v2_readiness.coverage import (
    CoverageDefinition,
    CoveragePolicyError,
    audit_calculate_coverage,
    build_gap_records,
    calculate_coverage,
    rolling_coverage,
)


UTC = timezone.utc
START = datetime(2026, 7, 22, 20, 14, tzinfo=UTC)


def definition(minutes: int = 1093) -> CoverageDefinition:
    return CoverageDefinition(
        metric_name="tim_closed_1m_continuous_coverage",
        metric_version="2.0.0",
        market="BINANCE_SPOT",
        instrument="BTCUSDT",
        data_type="CLOSED_1M_CANDLE_DERIVED_FROM_AGGTRADE",
        window_start_utc=START,
        window_end_utc=START + timedelta(minutes=minutes),
    )


def minutes(count: int) -> list[datetime]:
    return [START + timedelta(minutes=index) for index in range(count)]


def test_frozen_60659_baseline_is_reproducible() -> None:
    result = calculate_coverage(definition(), minutes(663))
    assert result.valid_observations == 663
    assert len(result.missing_minutes) == 430
    assert result.coverage == Decimal("0.606587")
    assert result.to_dict()["coverage_percent"] == "60.659"


def test_exact_95_percent_gate_keeps_original_denominator_start() -> None:
    result = calculate_coverage(definition(8600), minutes(8170))
    assert result.coverage == Decimal("0.950000")
    assert result.status == "PASS"
    assert result.definition.window_start_utc == START


def test_product_and_independent_audit_methods_agree() -> None:
    observed = minutes(100) + [START, START, START + timedelta(seconds=2)]
    product = calculate_coverage(definition(120), observed)
    audit = audit_calculate_coverage(definition(120), observed)
    assert product.coverage == audit.coverage
    assert product.missing_minutes == audit.missing_minutes
    assert product.valid_observations == audit.valid_observations == 100
    assert product.duplicates_excluded == audit.duplicates_excluded == 2
    assert product.invalid_observations == audit.invalid_observations == 1


def test_synthetic_minutes_are_visible_but_never_counted() -> None:
    observed = minutes(10)
    result = calculate_coverage(definition(10), observed, synthetic=[observed[-1]])
    assert result.valid_observations == 9
    assert result.synthetic_observations == 1
    assert result.coverage == Decimal("0.900000")
    assert result.status == "FAIL"


def test_duplicates_never_raise_coverage() -> None:
    result = calculate_coverage(definition(3), [START, START, START])
    assert result.valid_observations == 1
    assert result.duplicates_excluded == 2
    assert result.coverage == Decimal("0.333333")


def test_rolling_coverage_uses_same_fixed_rules() -> None:
    observed = minutes(120)
    result = rolling_coverage(definition(120), observed, [timedelta(hours=1)])
    assert result["PT60M"]["expected_observations"] == 60
    assert result["PT60M"]["coverage"] == 1.0
    assert result["PT60M"]["invalid_observations"] == 0


def test_gap_ids_are_deterministic_and_ranges_are_collapsed() -> None:
    missing = [START, START + timedelta(minutes=1), START + timedelta(minutes=4)]
    first = build_gap_records(definition(5), missing)
    second = build_gap_records(definition(5), reversed(missing))
    assert first == second
    assert [item["missing_observations"] for item in first] == [2, 1]
    assert len({item["gap_id"] for item in first}) == 2
    assert {item["severity"] for item in first} == {"P1"}


def test_gap_root_cause_requires_evidence() -> None:
    gap = build_gap_records(definition(2), [START])[0]
    assert gap["root_cause_class"] == "UNKNOWN"
    assert gap["root_cause_status"] == "UNKNOWN"
    raw_gap = build_gap_records(definition(2), [START], raw_minutes=[START])[0]
    assert raw_gap["root_cause_class"] == "PARTIAL_WRITE"
    assert raw_gap["root_cause_status"] == "PROBABLE"
    sleep_gap = build_gap_records(
        definition(2),
        [START],
        confirmed_downtime=[(START - timedelta(seconds=1), START + timedelta(minutes=1))],
    )[0]
    assert sleep_gap["root_cause_class"] == "PROCESS_DOWNTIME"
    assert sleep_gap["root_cause_status"] == "CONFIRMED"
    probable_gap = build_gap_records(
        definition(2),
        [START],
        probable_downtime=[(START, START + timedelta(minutes=2))],
    )[0]
    assert probable_gap["root_cause_class"] == "PROCESS_DOWNTIME"
    assert probable_gap["root_cause_status"] == "PROBABLE"


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"target": Decimal("0.90")}, "target"),
        ({"market": "BINANCE_FUTURES"}, "market"),
        ({"instrument": "ETHUSDT"}, "instrument"),
        ({"window_start_utc": START.replace(second=1)}, "aligned"),
        ({"window_start_utc": START.replace(tzinfo=None)}, "timezone-aware"),
    ],
)
def test_metric_policy_rejects_denominator_or_scope_manipulation(changes, match) -> None:
    values = {
        "metric_name": "tim_closed_1m_continuous_coverage",
        "metric_version": "2.0.0",
        "market": "BINANCE_SPOT",
        "instrument": "BTCUSDT",
        "data_type": "CLOSED_1M_CANDLE_DERIVED_FROM_AGGTRADE",
        "window_start_utc": START,
        "window_end_utc": START + timedelta(minutes=10),
    }
    values.update(changes)
    with pytest.raises(CoveragePolicyError, match=match):
        CoverageDefinition(**values)
