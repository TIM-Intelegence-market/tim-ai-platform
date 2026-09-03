from src.operational.watchdog import WatchdogThresholds, evaluate_watchdog


def healthy_observation() -> dict:
    return {
        "runtime_running": True,
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
        "runtime_process", "dashboard", "collector_freshness", "postgres_listener", "data_age",
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


def test_new_gap_warns_then_ages_to_critical() -> None:
    observed = healthy_observation()
    observed.update({"open_gap_count": 1, "oldest_gap_age_seconds": 10})
    assert evaluate_watchdog(observed, WatchdogThresholds())["status"] == "YELLOW"
    observed["oldest_gap_age_seconds"] = 1_000
    assert evaluate_watchdog(observed, WatchdogThresholds())["status"] == "RED"
