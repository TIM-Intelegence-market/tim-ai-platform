"""Start gates pass only on explicit, fresh evidence and never start the campaign."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.v2_completion import start_gate_checks as gates
from src.v2_completion.qualification import REQUIRED_START_GATES

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
SS_LOOPBACK = "LISTEN 0 200 127.0.0.1:5432 0.0.0.0:*\nLISTEN 0 200 [::1]:5432 [::]:*\nLISTEN 0 5 0.0.0.0:22 0.0.0.0:*\n"
STOP = {"status": "PASS", "trading_actions": 0, "cursor": "HASH_AND_VERSION_VALIDATED",
        "completed_at": "2026-10-20T11:02:18+00:00",
        "durable_ingestion_checkpoint": {"checkpoint_safe": True, "processing": 0}}
START = {"status": "PASS", "trading_actions": 0, "completed_at": "2026-10-20T11:02:25+00:00"}
LIVENESS = {"status": "PASS", "computed_at_utc": "2026-10-20T11:59:00Z", "expected_observations": 1440,
            "valid_observations": 1440, "trading_actions": 0, "coverage_percent": "100.000"}


def test_postgresql_security() -> None:
    assert gates.listener_addresses(SS_LOOPBACK) == ["127.0.0.1", "::1"]
    assert gates.check_postgresql_security(SS_LOOPBACK, "localhost").status == "PASS"
    exposed = gates.check_postgresql_security(SS_LOOPBACK + "LISTEN 0 200 192.168.1.5:5432 0.0.0.0:*\n", "localhost")
    assert exposed.status == "FAIL" and "192.168.1.5" in exposed.reasons[0]
    assert gates.check_postgresql_security(SS_LOOPBACK, "*").status == "FAIL"
    assert gates.check_postgresql_security(None, None).status == "PENDING"
    assert gates.check_postgresql_security("", "localhost").status == "FAIL"


def test_safe_stop() -> None:
    assert gates.check_safe_stop(STOP, START, NOW).status == "PASS"
    assert gates.check_safe_stop(None, START, NOW).status == "PENDING"
    assert gates.check_safe_stop({**STOP, "trading_actions": 1}, START, NOW).status == "FAIL"
    assert gates.check_safe_stop(STOP, {**START, "completed_at": "2026-10-20T11:00:00+00:00"}, NOW).status == "FAIL"
    assert gates.check_safe_stop(STOP, START, NOW + timedelta(days=15)).status == "FAIL"


def test_cursor_outbox_ingestion() -> None:
    cursor = {"cursor_version": 1, "cursor_hash": "a" * 64, "recovery_state": "NORMAL",
              "last_persisted_at": NOW - timedelta(seconds=5)}
    assert gates.check_durable_cursor(cursor, NOW).status == "PASS"
    assert gates.check_durable_cursor({**cursor, "recovery_state": "DEGRADED"}, NOW).status == "FAIL"
    assert gates.check_durable_cursor({**cursor, "last_persisted_at": NOW - timedelta(minutes=6)}, NOW).status == "FAIL"
    assert gates.check_durable_outbox({"COMPLETED": 10, "DEFERRED": 5}).status == "PASS"
    assert gates.check_durable_outbox({"COMPLETED": 10, "QUARANTINED": 1}).status == "FAIL"
    assert gates.check_durable_outbox({"PENDING": 60_000}).status == "FAIL"
    assert gates.check_durable_ingestion(0, LIVENESS, NOW).status == "PASS"
    assert gates.check_durable_ingestion(2, LIVENESS, NOW).status == "FAIL"
    assert gates.check_durable_ingestion(0, {**LIVENESS, "valid_observations": 1439}, NOW).status == "FAIL"
    assert gates.check_durable_ingestion(0, {**LIVENESS, "computed_at_utc": "2026-10-20T11:00:00Z"}, NOW).status == "FAIL"


def test_watchdog_logs_observe() -> None:
    status = {"status": "GREEN", "checked_at": "2026-10-20T11:59:30+00:00"}
    assert gates.check_watchdog(status, "active", NOW).status == "PASS"
    assert gates.check_watchdog(status, "inactive", NOW).status == "FAIL"
    assert gates.check_watchdog({**status, "status": "RED"}, "active", NOW).status == "FAIL"
    assert gates.check_watchdog(None, "active", NOW).status == "PENDING"
    assert gates.check_log_rotation("active", NOW - timedelta(hours=11), ["queue.jsonl.1.gz"], NOW).status == "PASS"
    assert gates.check_log_rotation("active", NOW - timedelta(hours=30), ["x.gz"], NOW).status == "FAIL"
    assert gates.check_log_rotation("active", NOW, [], NOW).status == "FAIL"
    health = {"mode": "OBSERVE", "trading_actions": 0}
    assert gates.check_observe_only(health, LIVENESS).status == "PASS"
    assert gates.check_observe_only({**health, "mode": "PAPER"}, LIVENESS).status == "FAIL"


def test_suite_and_freeze_bind_to_head() -> None:
    head = "b" * 40
    assert gates.check_full_suite(head, head, "https://example/run/1").status == "PASS"
    assert gates.check_full_suite(head, "c" * 40, "https://example/run/1").status == "FAIL"
    assert gates.check_full_suite(head, None, None).status == "PENDING"
    assert gates.check_frozen(head, [], head, []).status == "PASS"
    assert gates.check_frozen(head, [" M config/x"], head, []).status == "FAIL"
    assert gates.check_frozen(head, [], head, ["tim-runtime.service"]).status == "FAIL"
    assert gates.check_frozen(head, [], None, []).status == "PENDING"


def test_summary_requires_all_gates_and_never_starts() -> None:
    passing = [gates.GateResult(name, "PASS") for name in REQUIRED_START_GATES]
    report = gates.summarize(passing, now=NOW, context={})
    assert report["all_start_gates_pass"] and report["campaign_started"] is False and report["trading_actions"] == 0
    mixed = passing[:-1] + [gates.GateResult(REQUIRED_START_GATES[-1], "PENDING")]
    assert gates.summarize(mixed, now=NOW, context={})["blocking_start_gates"] == [REQUIRED_START_GATES[-1]]
    with pytest.raises(ValueError):
        gates.summarize(passing[:-1], now=NOW, context={})
