import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.operational.health import HealthChecker
from src.operational.logging import StructuredLog
from src.operational.metrics import MetricsCollector
from src.operational.runner import OperationalValidator
from src.operational.research_health import ResearchHealthChecker


class BrokenResearchChecker:
    validator_cycle = None

    def run_full_check(self):
        raise RuntimeError("TEST_ONLY research failure")


def test_structured_log_is_valid_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    StructuredLog(path).write("TEST_EVENT", mode="OBSERVE")
    row = json.loads(path.read_text().strip())
    assert row["event"] == "TEST_EVENT"
    assert row["mode"] == "OBSERVE"


def test_metrics_collector_returns_bounded_values(tmp_path: Path) -> None:
    metrics = MetricsCollector(tmp_path).collect()
    assert metrics.rss_mb >= 0
    assert metrics.cpu_percent >= 0
    assert 0 <= metrics.disk_used_percent <= 100


def test_required_file_health_reports_missing_path(tmp_path: Path) -> None:
    report = HealthChecker("postgresql://unused").files([tmp_path / "missing"])
    assert report["status"] == "DEGRADED"
    assert report["missing"] == [str(tmp_path / "missing")]


def test_validator_state_survives_restart(tmp_path: Path) -> None:
    first = OperationalValidator(tmp_path, duration_seconds=60, interval_seconds=5)
    first.state["cycles"] = 7
    first._write(first.state_path, first.state)
    second = OperationalValidator(tmp_path, duration_seconds=60, interval_seconds=5)
    assert second.state["cycles"] == 7
    assert second.state["restart_count"] == 1
    assert second.state["status"] == "RUNNING"
    assert second.report()["constraints"]["live_trading"] is False


def test_completed_validator_is_idempotent_on_restart(tmp_path: Path) -> None:
    first=OperationalValidator(tmp_path,duration_seconds=60,interval_seconds=5)
    first.state.update({"status":"COMPLETED","restart_count":4,"completed_at":"2026-01-01T00:00:00+00:00"})
    first._write(first.state_path,first.state)
    restarted=OperationalValidator(tmp_path,duration_seconds=60,interval_seconds=5)
    assert restarted.state["status"]=="COMPLETED"
    assert restarted.state["restart_count"]==4
    assert restarted.state["completed_at"]=="2026-01-01T00:00:00+00:00"


def test_acceptance_check_is_hourly_and_final_is_forced(tmp_path: Path) -> None:
    validator=OperationalValidator(tmp_path,duration_seconds=60,interval_seconds=5)
    now=datetime(2026,1,1,12,tzinfo=timezone.utc)
    assert validator._acceptance_due(now) is True
    validator.state["last_acceptance_check_at"]=(now-timedelta(minutes=59)).isoformat()
    assert validator._acceptance_due(now) is False
    validator.state["last_acceptance_check_at"]=(now-timedelta(minutes=60)).isoformat()
    assert validator._acceptance_due(now) is True
    assert validator._acceptance_due(now,final=True) is True


def test_degraded_health_uses_fifteen_minute_interval(tmp_path: Path) -> None:
    validator=OperationalValidator(tmp_path,duration_seconds=60,interval_seconds=5);now=datetime.now(timezone.utc)
    validator.state["health_monitor"]={"level":"YELLOW"}
    validator.state["last_acceptance_check_at"]=(now-timedelta(minutes=14)).isoformat()
    assert validator._acceptance_due(now) is False
    validator.state["last_acceptance_check_at"]=(now-timedelta(minutes=15)).isoformat()
    assert validator._acceptance_due(now) is True


def test_research_health_is_observe_only_and_reports_missing_runtime(tmp_path:Path)->None:
    result=ResearchHealthChecker(tmp_path,"http://127.0.0.1:1").check()
    assert result["status"]=="DEGRADED"
    assert result["external_search"] is False and result["multi_agent"] is False
    assert result["checks"]["report_integrity"] is False
    assert result["checks"]["metadata_complete"] is False


@pytest.mark.local_env
def test_live_research_monitor_matrix_is_green()->None:
    root=Path(__file__).resolve().parents[1];result=ResearchHealthChecker(root).check()
    assert result["level"]=="GREEN"
    assert result["trigger_duplicates"]==0
    assert result["reports"]["metadata"]==result["reports"]["metadata_valid"]==result["reports"]["provenance_valid"]


def test_research_check_failure_is_isolated_without_crashing_cycle(tmp_path:Path)->None:
    validator=OperationalValidator(tmp_path,duration_seconds=60,interval_seconds=5)
    result=validator._run_research_check(BrokenResearchChecker(),48)
    assert result["level"]=="RED"
    assert result["isolated"] is True
    assert validator.state["research_health"]=="CRITICAL"
    assert validator.state["research_last_check"]
    event=json.loads((tmp_path/"data/operational/events.jsonl").read_text())
    assert event["event"]=="RESEARCH_CYCLE_CHECK_FAILED"
    assert event["cycle"]==48
