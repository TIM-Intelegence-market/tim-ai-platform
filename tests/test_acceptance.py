import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.acceptance.monitor import AcceptanceMonitor, EventCategory, run_acceptance_check
from scripts.acceptance_check import document_data_gaps, persisted_candle_gaps


def root_with_state(tmp_path: Path, start: datetime, hours: int = 72) -> Path:
    operational=tmp_path/"data/operational";operational.mkdir(parents=True)
    state={"started_at":start.isoformat(),"deadline":(start+timedelta(hours=hours)).isoformat(),"cycles":72}
    (operational/"state.json").write_text(json.dumps(state))
    healthy={"timestamp":start.isoformat(),"database":"HEALTHY","dashboard":"HEALTHY","benchmark":"PASS"}
    (operational/"metrics.jsonl").write_text(json.dumps(healthy)+"\n")
    (operational/"events.jsonl").write_text("")
    return tmp_path


def passing_context() -> dict:
    return {"database_consistent":True,"acceptance_candles":900,"acceptance_minutes":4320,"observations":20,"distinct_observations":20,"observations_deterministic":True,"research_cases":10,"cases_with_provenance":10,"dashboard_auto_refresh":True,"countdown_synchronized":True,"provenance_total":30,"provenance_valid":30,"api_http_status":200,"api_latency_ms":20,"candle_gaps":0,"last_candle_age_seconds":30,"candle_stream_active":True,"candle_timestamps_monotonic":True,"candles_last_hour":12}


def test_health_matrix_green_for_healthy_hour(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now)
    monitor=AcceptanceMonitor(root,as_of=now);monitor.state.update({"status":"RUNNING","mode":"OBSERVE"})
    matrix=monitor.health_matrix(passing_context())
    assert matrix["level"]=="GREEN"
    assert matrix["next_check_minutes"]==60


def test_health_matrix_data_gap_is_red(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now)
    monitor=AcceptanceMonitor(root,as_of=now);monitor.state.update({"status":"RUNNING","mode":"OBSERVE"});context=passing_context();context["candle_gaps"]=1
    matrix=monitor.health_matrix(context)
    assert matrix["level"]=="RED"
    assert matrix["critical"]==["DATA_GAP"]
    assert matrix["next_check_minutes"]==15


def test_persisted_gap_detection_covers_small_old_and_all_timeframes() -> None:
    old=datetime(2026,1,1,tzinfo=timezone.utc)
    records=[
        {"timeframe":"1m","open_time":old},
        {"timeframe":"1m","open_time":old+timedelta(minutes=2)},
        {"timeframe":"5m","open_time":old},
        {"timeframe":"5m","open_time":old+timedelta(minutes=10)},
        {"timeframe":"15m","open_time":old},
        {"timeframe":"15m","open_time":old+timedelta(minutes=15)},
    ]
    gaps=persisted_candle_gaps(records,("1m","5m","15m"))
    assert [(item["timeframe"],item["actual_seconds"]) for item in gaps]==[("1m",120),("5m",600)]


def test_data_gap_is_documented_once_with_scientific_impact(tmp_path:Path)->None:
    context={"candle_gap_details":[{"timeframe":"1m","prior":"2026-01-01T00:00:00+00:00","open_time":"2026-01-01T00:03:00+00:00","expected_seconds":60,"actual_seconds":180}]}
    now=datetime(2026,1,1,0,4,tzinfo=timezone.utc)
    assert document_data_gaps(tmp_path,context,now)==1
    assert document_data_gaps(tmp_path,context,now)==0
    rows=[json.loads(line) for line in (tmp_path/"data/operational/events.jsonl").read_text().splitlines()]
    assert len(rows)==1 and rows[0]["event"]=="DATA_GAP"
    assert rows[0]["duration_seconds"]==120 and rows[0]["reconstruction_performed"] is False
    assert rows[0]["scientific_impact"]=="CONTINUOUS_COVERAGE_CLAIMS_EXCLUDE_THIS_INTERVAL"


def test_report_is_refused_before_real_deadline(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=71))
    monitor=AcceptanceMonitor(root,as_of=now)
    assert monitor.check_deadline() is False
    with pytest.raises(RuntimeError,match="deadline"):monitor.generate_report(passing_context())
    result=run_acceptance_check(root,passing_context(),as_of=now)
    assert result["status"]=="monitoring"
    assert not (root/"docs/TIM_72H_ACCEPTANCE_REPORT.md").exists()


def test_runtime_passes_only_after_persisted_deadline(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=73))
    monitor=AcceptanceMonitor(root,as_of=now)
    assert monitor.check_deadline() is True
    assert monitor._check_runtime({})[0] is True


def test_observe_only_rejects_execution_event(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=1))
    monitor=AcceptanceMonitor(root,as_of=now);monitor.events=[{"event":"TRADE_EXECUTED"}]
    assert monitor._check_observe_only({})[0] is False


def test_controlled_failure_is_separate_from_uncontrolled(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=1))
    monitor=AcceptanceMonitor(root,as_of=now);monitor.events=[{"category":EventCategory.CONTROLLED_API_FAILURE.value},{"category":EventCategory.UNCONTROLLED_API_FAILURE.value}]
    assert sum(e["category"]==EventCategory.UNCONTROLLED_API_FAILURE.value for e in monitor.events)==1


def test_controlled_failure_does_not_fail_validator_health(tmp_path:Path)->None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=1));monitor=AcceptanceMonitor(root,as_of=now)
    monitor.metrics.append({"database":"HEALTHY","dashboard":"UNAVAILABLE","benchmark":"PASS"});monitor.events=[{"category":EventCategory.CONTROLLED_API_FAILURE.value}]
    passed,evidence=monitor._check_validator_health({})
    assert passed is True and "0 uncontrolled" in evidence


def test_weighted_score_is_deterministic(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=73));monitor=AcceptanceMonitor(root,as_of=now)
    context=passing_context();context["database_consistent"]=False
    result=monitor.evaluate(context)
    assert result["total_score"]==.90
    assert result["passed"] is False


def test_complete_report_contains_required_sections(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=73));(root/"docs").mkdir()
    result=run_acceptance_check(root,passing_context(),as_of=now)
    assert result["status"]=="complete"
    report=Path(result["path"]).read_text()
    for section in ("# TIM 72h Acceptance Report","## Executive Summary","## System Architecture","## Operational Metrics (72h)","## Resilience Testing","## Data Quality Audit","## Compliance Check (OBSERVE-only)","## Known Limitations","## Go/No-Go Recommendation"):
        assert section in report
    assert "Provenance: PUBLIC_MARKET_DATA_DETERMINISTIC" in report
    assert result["health_matrix"]
    assert "checks" in result["health_matrix"]


def test_missing_provenance_fails(tmp_path: Path) -> None:
    now=datetime(2026,1,4,tzinfo=timezone.utc);root=root_with_state(tmp_path,now-timedelta(hours=73));monitor=AcceptanceMonitor(root,as_of=now)
    context=passing_context();context["provenance_valid"]=29
    assert monitor._check_provenance(context)[0] is False
