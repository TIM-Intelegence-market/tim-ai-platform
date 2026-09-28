from src.v2_readiness.monitor import evaluate_observe_alerts


def safe_snapshot() -> dict:
    return {
        "coverage": 0.96,
        "open_p0_gaps": 0,
        "open_p1_gaps": 0,
        "data_age_seconds": 5,
        "stale_after_seconds": 180,
        "collector_status": "GREEN",
        "persistence_invalid_rows": 0,
        "clock_skew_rows": 0,
        "dashboard_bind": "LOOPBACK_ONLY",
        "execution_active": False,
    }


def test_observe_alerts_are_empty_for_a_proven_safe_snapshot() -> None:
    assert evaluate_observe_alerts(safe_snapshot()) == []


def test_observe_alerts_fail_closed_without_causing_trading_actions() -> None:
    snapshot = safe_snapshot()
    snapshot.update(
        coverage=0.67,
        open_p1_gaps=283,
        data_age_seconds=500,
        collector_status="DOWN",
        clock_skew_rows=2,
        dashboard_bind="PUBLIC",
        execution_active=None,
    )
    alerts = evaluate_observe_alerts(snapshot)
    assert {item["code"] for item in alerts} == {
        "CLOCK_SKEW",
        "COLLECTOR_DOWN",
        "COVERAGE_BELOW_TARGET",
        "EXECUTION_COMPONENT_ACTIVE_OR_UNKNOWN",
        "OPEN_P1_GAP",
        "PUBLIC_DASHBOARD_BIND",
        "STALE_DATA",
    }
    assert {item["action"] for item in alerts} == {"OBSERVE_ONLY_NO_TRADING_ACTION"}
