import pytest

from src.repair_observe.enablement import DEFAULT_THRESHOLDS, a1_go_no_go


@pytest.fixture
def good_metrics():
    return {
        "events_ingested": 1000,
        "unknown_rate": 0.20,
        "critical_rate": 0.05,
        "ingestion_lag_seconds": 300,
        "checkpoint_age_seconds": 600,
        "pending_tracebacks": 0,
        "future_timestamp_observed": False,
    }


def test_go_with_defaults(good_metrics):
    assert a1_go_no_go(good_metrics) == {
        "decision": "GO",
        "reasons": [],
        "auto_repair_enabled": False,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("events_ingested", 999),
        ("unknown_rate", 0.21),
        ("critical_rate", 0.06),
        ("ingestion_lag_seconds", 301),
        ("checkpoint_age_seconds", 601),
        ("pending_tracebacks", 1),
        ("future_timestamp_observed", True),
    ],
)
def test_each_failing_check_returns_no_go(good_metrics, field, value):
    good_metrics[field] = value
    result = a1_go_no_go(good_metrics)
    assert result["decision"] == "NO_GO"
    assert field in result["reasons"]


def test_missing_key_returns_no_go(good_metrics):
    del good_metrics["critical_rate"]
    result = a1_go_no_go(good_metrics)
    assert result["decision"] == "NO_GO"
    assert "critical_rate" in result["reasons"]


def test_none_value_returns_no_go(good_metrics):
    good_metrics["unknown_rate"] = None
    result = a1_go_no_go(good_metrics)
    assert result["decision"] == "NO_GO"
    assert "unknown_rate" in result["reasons"]


def test_non_dict_metrics_returns_no_go():
    result = a1_go_no_go([])
    assert result["decision"] == "NO_GO"
    assert "metrics" in result["reasons"]


def test_unknown_threshold_key_returns_no_go(good_metrics):
    result = a1_go_no_go(good_metrics, {"unexpected": 1})
    assert result["decision"] == "NO_GO"
    assert "unknown threshold key: unexpected" in result["reasons"]


def test_mixed_unknown_threshold_keys_fail_closed(good_metrics):
    result = a1_go_no_go(good_metrics, {1: 1, "unexpected": 1})
    assert result["decision"] == "NO_GO"
    assert result["reasons"] == ["threshold keys must be strings"]


def test_unrepresentable_numeric_metric_fails_closed(good_metrics):
    good_metrics["events_ingested"] = 10 ** 10000
    result = a1_go_no_go(good_metrics)
    assert result["decision"] == "NO_GO"
    assert "events_ingested" in result["reasons"]


def test_threshold_override_is_applied(good_metrics):
    good_metrics["events_ingested"] = 10
    result = a1_go_no_go(good_metrics, {"min_events": 10})
    assert result["decision"] == "GO"


def test_auto_repair_is_false_for_go(good_metrics):
    assert a1_go_no_go(good_metrics)["auto_repair_enabled"] is False


def test_default_thresholds_have_expected_values():
    assert DEFAULT_THRESHOLDS == {
        "min_events": 1000,
        "max_unknown_rate": 0.20,
        "max_critical_rate": 0.05,
        "max_ingestion_lag_seconds": 300,
        "max_checkpoint_age_seconds": 600,
        "max_pending_tracebacks": 0,
    }
