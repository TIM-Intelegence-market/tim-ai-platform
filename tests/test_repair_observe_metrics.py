import pytest

from src.repair_observe.metrics import quality_metrics


@pytest.fixture
def status():
    return {
        "incidents_created": 10,
        "events_ingested": 20,
        "occurrences_deduplicated": 5,
        "unknown_incidents": 2,
        "active_incidents": 4,
        "critical_incidents": 3,
        "ingestion_lag_seconds": 1.5,
        "checkpoint_age_seconds": 8,
        "future_timestamp_observed": False,
        "pending_tracebacks": 1,
    }


def test_returns_quality_metrics(status):
    assert quality_metrics(status) == {
        "unknown_rate": 0.2,
        "dedup_ratio": 0.25,
        "critical_rate": 0.3,
        "ingestion_lag_seconds": 1.5,
        "checkpoint_age_seconds": 8,
        "future_timestamp_observed": False,
        "pending_tracebacks": 1,
        "events_ingested": 20,
    }


def test_zero_incidents_produce_none_incident_rates(status):
    status["incidents_created"] = 0

    result = quality_metrics(status)

    assert result["unknown_rate"] is None
    assert result["critical_rate"] is None


def test_zero_events_produce_none_dedup_ratio(status):
    status["events_ingested"] = 0

    assert quality_metrics(status)["dedup_ratio"] is None


def test_none_lag_values_are_preserved(status):
    status["ingestion_lag_seconds"] = None
    status["checkpoint_age_seconds"] = None

    result = quality_metrics(status)

    assert result["ingestion_lag_seconds"] is None
    assert result["checkpoint_age_seconds"] is None


def test_missing_key_raises_value_error_naming_key(status):
    del status["pending_tracebacks"]

    with pytest.raises(ValueError, match="pending_tracebacks"):
        quality_metrics(status)


def test_wrong_numeric_type_raises_value_error_naming_key(status):
    status["events_ingested"] = True

    with pytest.raises(ValueError, match="events_ingested"):
        quality_metrics(status)


def test_wrong_boolean_type_raises_value_error_naming_key(status):
    status["future_timestamp_observed"] = 0

    with pytest.raises(ValueError, match="future_timestamp_observed"):
        quality_metrics(status)
