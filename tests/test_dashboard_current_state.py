"""Control Center shows the current state after the V2 campaign was aborted (23.10.2026).

Pins five fixes: aborted campaign, stale readiness matrix, CI test of the
deployed commit, live runtime telemetry, and today's value next to archived gates.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dashboard.design_system import gate_rows
from src.dashboard.operations import (
    _apply_live_telemetry,
    _ci_test_of_deployment,
    _current_readiness,
    build_operations_snapshot,
    render_operations_page,
)

def _now() -> datetime:
    # Fresh per call: the CI suite reaches these tests ~30 min after import.
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _setup(root: Path, *, aborted: bool = True) -> tuple[Path, Path]:
    qualification = root / "data/qualification"
    _write(qualification / "qualification_campaign.json", {
        "campaign_status": "ACTIVE", "dataset_id": "V2_PROSPECTIVE_QUALIFICATION_V1",
        "start_utc": "2026-10-20T20:34:00Z", "case_target": 1000,
    })
    _write(qualification / "daily" / "2026-10-21.json", {
        "generated_at_utc": "2026-10-22T00:32:08Z",
        "metrics": {"cumulative_coverage": 1.0, "observed_minutes": 1440, "expected_minutes": 1440, "independent_case_count": 54},
    })
    if aborted:
        _write(qualification / "campaign_aborted.json", {
            "status": "ABORTED", "aborted_at_utc": "2026-10-22T22:08:14Z",
            "note": "Abgebrochen auf Uzis Wunsch.",
        })
    operational = root / "data/operational"
    _write(operational / "watchdog_status.json", {"status": "GREEN", "checked_at": _iso(_now()), "checks": {}})
    return qualification, operational


def _snapshot(root: Path, base: dict | None = None, completion: Path | None = None) -> dict:
    qualification, operational = _setup(root)
    return build_operations_snapshot(
        base or {"timestamp": _iso(_now()), "operational_health": {}},
        completion or root / "missing_completion", root / "missing_legacy",
        operational / "watchdog_status.json", operational / "rolling_liveness.json", qualification,
    )


def test_aborted_campaign_is_shown_as_aborted_and_not_counted(tmp_path: Path) -> None:
    data = _snapshot(tmp_path)
    assert data["qualification"]["status"] == "ABORTED"
    assert data["independent_cases"]["status"] == "ABORTED — NOT COUNTED"
    assert data["readiness"]["status"] == "NOT QUALIFIED — CAMPAIGN ABORTED"
    assert data["readiness"]["source"].endswith("campaign_aborted.json")
    page = render_operations_page("Qualification", data)
    assert "ABORTED" in page


def test_old_readiness_matrix_is_marked_stale_not_current() -> None:
    old = {"path": "artifacts/v2_completion/implementation_state.json", "captured_at": _iso(_now() - timedelta(days=80))}
    result = _current_readiness("FAIL — SAFETY OR DATA INTEGRITY", [], old, {})
    assert result["status"] == "STALE — FAIL — SAFETY OR DATA INTEGRITY"
    fresh = {"path": "x", "captured_at": _iso(_now() - timedelta(days=2))}
    assert _current_readiness("FAIL", [], fresh, {})["status"] == "FAIL"


def test_ci_run_of_deployed_commit_replaces_old_test_summary() -> None:
    deployment = {"commit": "cc6a880abc", "ci_test": {"conclusion": "success", "completed_at_utc": _iso(_now() - timedelta(hours=1)),
                                                      "passed": 6500, "failed": 0, "skipped": 40}}
    result = _ci_test_of_deployment(deployment, "2026-08-01T16:18:45Z")
    assert result and result["status"] == "PASS" and result["passed"] == 6500
    assert _ci_test_of_deployment(deployment, _iso(_now())) is None  # recorded summary is newer
    assert _ci_test_of_deployment({}, "2026-08-01T16:18:45Z") is None
    failed = {**deployment, "ci_test": {**deployment["ci_test"], "conclusion": "failure"}}
    assert _ci_test_of_deployment(failed, None)["status"] == "FAIL"


def test_deployment_record_feeds_the_audit_card(tmp_path: Path) -> None:
    _setup(tmp_path)
    _write(tmp_path / "data/operational/deployment.json", {
        "commit": "cc6a880abcdef", "deployed_at_utc": _iso(_now()),
        "ci_test": {"conclusion": "success", "completed_at_utc": _iso(_now() - timedelta(hours=1)), "passed": 6500, "failed": 0},
    })
    data = _snapshot(tmp_path)
    assert data["audit"]["test_status"] == "PASS"
    assert data["audit"]["passed"] == 6500 and data["audit"]["deployed_commit"] == "cc6a880abcdef"


def test_live_telemetry_fills_runtime_metrics_only_when_fresh() -> None:
    runtime = {key: {"value": "UNAVAILABLE", "status": "UNAVAILABLE"} for key in (
        "restarts", "queue_age", "cursor_age", "receive_rate", "persist_rate", "drop_count",
        "duplicate_count", "late_count", "source_to_store_latency", "event_loop_lag")}
    live = {"health_snapshot_observed_at": _iso(_now() - timedelta(seconds=5)), "receive_rate_per_second": 12.345,
            "persist_rate_per_second": 12.0, "duplicate_total": 1118832.0, "late_total": 3.0, "rejected_total": 0.0,
            "restart_total": 4.0, "event_loop_lag": 0.0021, "source_to_store_latency": 0.41, "cursor_age": 0.4}
    _apply_live_telemetry(runtime, live)
    assert runtime["receive_rate"]["value"] == 12.35 and runtime["receive_rate"]["unit"] == "events/s"
    assert runtime["duplicate_count"]["value"] == 1118832 and runtime["restarts"]["value"] == 4
    assert runtime["drop_count"]["value"] == 0
    assert "system_health" in runtime["late_count"]["source"]

    stale = {key: {"value": "UNAVAILABLE"} for key in runtime}
    _apply_live_telemetry(stale, {**live, "health_snapshot_observed_at": _iso(_now() - timedelta(minutes=10))})
    assert stale["receive_rate"]["value"] == "UNAVAILABLE"


def test_archived_gate_gets_todays_value_next_to_it(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write(completion / "implementation_state.json", {
        "generated_at_utc": _iso(_now() - timedelta(days=80)), "overall_status": "FAIL",
        "gates": [{"gate_id": "TECH-SECURITY", "status": "FAIL", "open_limitation": "PostgreSQL listens on LAN"},
                  {"gate_id": "V2-B04", "status": "FAIL", "open_limitation": "14 strict units"}],
    })
    base = {"timestamp": _iso(_now()), "operational_health": {},
            "system_health": {"postgres_listener": {"listen_addresses": "127.0.0.1,::1", "status": "PASS", "exposed_addresses": [],
                                                    "checked_at_utc": _iso(_now()), "source": "runtime: SHOW listen_addresses"}}}
    data = _snapshot(tmp_path, base, completion)
    gates = {gate["id"]: gate for gate in data["readiness"]["gates"]}
    assert gates["TECH-SECURITY"]["status"] == "FAIL"  # archived verdict unchanged
    assert gates["TECH-SECURITY"].get("current_status") == "PASS"
    assert "127.0.0.1" in gates["TECH-SECURITY"]["current_note"]
    assert gates["V2-B04"]["current_status"].startswith("ABORTED")
    assert "Heute:" in gate_rows(data["readiness"]["gates"])


def test_runtime_computes_rates_from_two_counter_samples() -> None:
    from types import SimpleNamespace

    from main import TIMApplication

    app = SimpleNamespace(_ingestion_health_snapshot=None, _ingestion_health_sample_started=0.0)
    throughput = TIMApplication._throughput
    assert throughput(app, {"received_total": 100.0}, 10.0) == {}  # first sample: no rate
    app._ingestion_health_snapshot = {"received_total": 100.0, "raw_persisted_total": 90.0}
    app._ingestion_health_sample_started = 10.0
    rates = throughput(app, {"received_total": 150.0, "raw_persisted_total": 140.0}, 15.0)
    assert rates == {"rate_window_seconds": 5.0, "receive_rate_per_second": 10.0, "persist_rate_per_second": 10.0}
    backwards = throughput(app, {"received_total": 50.0, "raw_persisted_total": 140.0}, 15.0)
    assert "receive_rate_per_second" not in backwards


def test_record_deployment_writes_commit_and_ci(tmp_path: Path) -> None:
    import argparse

    from scripts import record_deployment

    args = argparse.Namespace(commit="abc1234", ci_conclusion="success", ci_completed_at="2026-10-22T21:40:00Z",
                              ci_url="https://example.invalid/run", passed=10, failed=0, skipped=None)
    record = record_deployment.build(args)
    record_deployment.write(record, tmp_path / "deployment.json")
    stored = json.loads((tmp_path / "deployment.json").read_text())
    assert stored["commit"] == "abc1234" and stored["ci_test"]["completed_at_utc"] == "2026-10-22T21:40:00Z"
    assert "skipped" not in stored["ci_test"]
