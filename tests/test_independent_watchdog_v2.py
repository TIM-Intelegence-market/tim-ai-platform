from src.operational.watchdog import WatchdogThresholds, evaluate_watchdog, restartable_failures


def healthy_observation() -> dict:
    return {
        "runtime_running": True,
        "runtime_pid": 123,
        "collector_process_count": 1,
        "collector_pids": [123],
        "dashboard_healthy": True,
        "dashboard_status": 200,
        "collector_age_seconds": 5,
        "postgres_loopback_only": True,
        "postgres_listen_addresses": "localhost",
        "data_age_seconds": 5,
        "queue_oldest_age_seconds": None,
        "cursor_age_seconds": 5,
        "open_gap_count": 0,
        "oldest_gap_age_seconds": None,
        "disk_used_percent": 20,
        "largest_log_bytes": 100,
        "largest_log_path": "events.jsonl",
        "observe_only": True,
        "trading_action_count": 0,
    }


def test_watchdog_is_green_only_for_independently_healthy_observe_state() -> None:
    result = evaluate_watchdog(healthy_observation(), WatchdogThresholds())
    assert result["status"] == "GREEN"
    assert result["mode"] == "OBSERVE" and result["trading_actions"] == 0
    assert set(result["checks"]) == {
        "runtime_process", "single_collector", "dashboard", "collector_freshness", "postgres_listener", "data_age",
        "queue_age", "cursor_age", "gap_incidents", "disk_space", "log_growth", "observe_only",
        "trading_action_count",
    }


def test_watchdog_fails_closed_on_wildcard_listener_stale_cursor_or_action() -> None:
    observed = healthy_observation()
    observed.update(
        {
            "postgres_loopback_only": False,
            "postgres_listen_addresses": "*",
            "cursor_age_seconds": 1_000,
            "trading_action_count": 1,
        }
    )
    result = evaluate_watchdog(observed, WatchdogThresholds())
    assert result["status"] == "RED"
    assert result["checks"]["postgres_listener"]["status"] == "RED"
    assert result["checks"]["cursor_age"]["status"] == "RED"
    assert result["checks"]["trading_action_count"]["status"] == "RED"


def test_watchdog_rejects_multiple_collectors() -> None:
    observed = healthy_observation()
    observed.update({"collector_process_count": 2, "collector_pids": [123, 456]})
    result = evaluate_watchdog(observed, WatchdogThresholds())
    assert result["status"] == "RED"
    assert result["checks"]["single_collector"]["status"] == "RED"


def test_new_gap_warns_then_ages_to_critical() -> None:
    observed = healthy_observation()
    observed.update({"open_gap_count": 1, "oldest_gap_age_seconds": 10})
    assert evaluate_watchdog(observed, WatchdogThresholds())["status"] == "YELLOW"
    observed["oldest_gap_age_seconds"] = 1_000
    assert evaluate_watchdog(observed, WatchdogThresholds())["status"] == "RED"


def test_only_runtime_failures_are_restart_eligible() -> None:
    observed = healthy_observation()
    observed.update({"open_gap_count": 1, "oldest_gap_age_seconds": 1_000, "largest_log_bytes": 99_000_000})
    report = evaluate_watchdog(observed, WatchdogThresholds())
    assert report["status"] == "RED"
    assert restartable_failures(report) == ()
    observed["cursor_age_seconds"] = 1_000
    assert restartable_failures(evaluate_watchdog(observed, WatchdogThresholds())) == ("cursor_age",)
