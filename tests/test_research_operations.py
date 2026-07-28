from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.research_ops import MonthlyResearchSnapshot, ResearchAuditEngine, ResearchQualityEngine
from src.research_ops.audit import digest
from scripts.research_infrastructure_review import append_maturity_history, build_readiness


NOW = datetime(2026, 7, 31, 23, 0, tzinfo=timezone.utc)


def manifest() -> dict:
    return {"core_version":"1.0.0","status":"FROZEN","operating_mode":"OBSERVE","components":{"orderflow_metrics":"1.0.0","orderflow_observations":"1.0.0","orderflow_validation":"1.0.0","dashboard":"2.1.0"}}


def root(tmp_path: Path) -> Path:
    (tmp_path/"config").mkdir();(tmp_path/"data/research/module_b_reports").mkdir(parents=True);(tmp_path/"data/operational").mkdir(parents=True)
    (tmp_path/"config/core_manifest.json").write_text(json.dumps(manifest()))
    content="# Research\n\nDeterministic report.\n"
    report=tmp_path/"data/research/module_b_reports/tim-b-abcdef0123456789_research_report.md";report.write_text(content)
    metadata={"report_id":"tim-b-abcdef0123456789","file":str(report.relative_to(tmp_path)),"input_hash":"abcdef0123456789"+"0"*48,"artifact_hash":hashlib.sha256(content.encode()).hexdigest(),"schema_version":"1.0.0","generator_version":"1.0.0","provenance":"TIM_LOCAL_EVIDENCE_DETERMINISTIC","mode":"OBSERVE","timestamp":"2026-07-01T00:00:00+00:00","word_count":len(content.split())}
    report.with_name(report.name+".json").write_text(json.dumps(metadata))
    return tmp_path


def test_audit_is_deterministic_and_read_only(tmp_path: Path):
    project=root(tmp_path);before={p.relative_to(project):p.read_bytes() for p in project.rglob("*") if p.is_file()}
    first=ResearchAuditEngine(project).audit(as_of=NOW);second=ResearchAuditEngine(project).audit(as_of=NOW)
    after={p.relative_to(project):p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert first==second and before==after and first["status"]=="PASS" and first["read_only"] is True


def test_audit_detects_tampered_report_and_missing_documentation(tmp_path: Path):
    project=root(tmp_path);report=next((project/"data/research/module_b_reports").glob("*.md"));report.write_text("tampered")
    cache=project/"data/research/module_a_cache.jsonl";cache.write_text(json.dumps({"mode":"OBSERVE","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC","created_at":"2026-07-01T00:00:00Z"})+"\n")
    result=ResearchAuditEngine(project).audit(as_of=NOW);codes={item["code"] for item in result["issues"]}
    assert result["status"]=="FAIL" and {"ARTIFACT_HASH_MISMATCH","WORD_COUNT_MISMATCH","MISSING_DOCUMENTATION"}<=codes
    documentation=next(item for item in result["issues"] if item["code"]=="MISSING_DOCUMENTATION")
    assert "1 record(s)" in documentation["detail"]


def test_quality_documents_gaps_schema_timestamps_and_forward_only(tmp_path: Path):
    project=root(tmp_path)
    (project/"data/operational/events.jsonl").write_text("\n".join([json.dumps({"timestamp":"2026-07-02T00:00:00Z","event":"DATA_GAP","mode":"OBSERVE"}),json.dumps({"timestamp":"2026-07-01T00:00:00Z","event":"VALIDATION_CYCLE","mode":"OBSERVE"})])+"\n")
    (project/"data/operational/metrics.jsonl").write_text("not-json\n")
    (project/"data/research/trigger_events.jsonl").write_text(json.dumps({"triggered_at":"2026-08-01T00:00:00Z"})+"\n")
    (project/"data/operational/state.json").write_text(json.dumps({"health_monitor":{"checks":{"candle_sequence_gap_free":False,"provenance_deterministic":False}}}))
    audit=ResearchAuditEngine(project).audit(as_of=NOW);result=ResearchQualityEngine().assess(project,audit,as_of=NOW);codes={item["code"] for item in result["issues"]}
    assert result["status"]=="FAIL" and result["known_data_gaps"]
    assert {"TIMESTAMP_ORDER_VIOLATION","INVALID_SCHEMA","FUTURE_TIMESTAMP","PROVENANCE_INCOMPLETE"}<=codes
    assert result["checks"]["data_gaps_documented"] is True


def test_quality_replay_is_deterministic(tmp_path: Path):
    project=root(tmp_path)
    for path in (project/"data/operational/events.jsonl",project/"data/operational/metrics.jsonl",project/"data/research/trigger_events.jsonl"):path.write_text("")
    (project/"data/operational/state.json").write_text(json.dumps({"health_monitor":{"checks":{"candle_sequence_gap_free":True,"provenance_deterministic":True}}}))
    audit=ResearchAuditEngine(project).audit(as_of=NOW);engine=ResearchQualityEngine()
    assert engine.assess(project,audit,as_of=NOW)==engine.assess(project,audit,as_of=NOW)


def test_monthly_snapshot_is_deterministic_hashed_and_non_predictive():
    builder=MonthlyResearchSnapshot();kwargs={"month":"2026-07","as_of":NOW,"manifest":manifest(),"counts":{"agg_trades":10,"candles":2,"observations":1,"orderflow_observations":1,"research_cases":1,"validated_cases":1},"coverage":{"basis":"BTCUSDT closed 1m candles","expected_intervals":2,"observed_intervals":2,"missing_intervals":0,"coverage_percent":"100.000"},"replay":{"status":"PASS","hash":"a"*64},"quality":{"status":"PASS","report_hash":"b"*64,"known_data_gaps":[],"issues":[]},"insights":{"eligibility_status":"NOT_YET_ELIGIBLE","result_status":"EXPLORATORY_ONLY","eligibility":{"fully_validated_cases":1},"outcome_distribution":[],"input_hash":"c"*64,"warnings":["INSUFFICIENT_FULLY_VALIDATED_CASES"]}}
    first=builder.build(**kwargs);second=builder.build(**kwargs);copy=dict(first);declared=copy.pop("snapshot_hash")
    assert first==second and declared==digest(copy) and first["snapshot_status"]=="IN_PROGRESS"
    assert all(first[key] for key in ("artifact_hash","generator_version","schema_version","dataset_hash","generation_timestamp","validation_status"))
    assert first["research_results"]["open_cases"]==0
    assert first["research_results"]["validation_coverage_percent"]=="100.000"
    assert first["scientific_health"]["checks"]["replay"]=="PASS"
    assert first["scientific_health"]["checks"]["new_artifact_provenance"]=="FAIL"
    text=json.dumps(first).lower()+MonthlyResearchSnapshot.to_markdown(first).lower()
    assert "confidence" not in first
    for forbidden in ("buy signal","sell signal","expected move","probability"):
        assert forbidden not in text


def test_completed_month_is_final():
    result=MonthlyResearchSnapshot().build(month="2026-06",as_of=NOW,manifest=manifest(),counts={"validated_cases":0},coverage={},replay={},quality={},insights={})
    assert result["snapshot_status"]=="FINAL"


def test_maturity_history_is_hash_chained_and_deduplicated(tmp_path:Path):
    builder=MonthlyResearchSnapshot();base={"month":"2026-07","as_of":NOW,"manifest":manifest(),"counts":{"orderflow_observations":1,"validated_cases":1},"coverage":{"coverage_percent":"100.000"},"replay":{"status":"PASS"},"quality":{"status":"PASS","checks":{"forward_only":True,"observe_only":True},"known_data_gaps":[],"artifact_hash":"a"*64,"generator_version":"1.0.0","schema_version":"1.0.0","dataset_hash":"b"*64,"generation_timestamp":NOW.isoformat(),"validation_status":"PASS"},"insights":{"mode":"OBSERVE","input_hash":"c"*64,"output_hash":"d"*64,"eligibility":{}}}
    first=builder.build(**base);path=tmp_path/"history.jsonl"
    assert append_maturity_history(path,first) is True
    assert append_maturity_history(path,first) is False
    row=json.loads(path.read_text());copy=dict(row);declared=copy.pop("record_hash")
    assert declared==hashlib.sha256(json.dumps(copy,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def test_readiness_reports_waiting_and_never_approves_v2():
    snapshot={"generation_timestamp":NOW.isoformat(),"snapshot_hash":"a"*64,"dataset_hash":"b"*64,"artifact_hash":"c"*64,"validation_status":"PASS","versions":{"core":"1.0.0"},"research_results":{"observations":900,"fully_validated_cases":900,"open_cases":20},"coverage":{"continuous_coverage_percent":"96.000","continuous_interval_start":"2026-07-01T00:00:00+00:00","continuous_interval_end":NOW.isoformat(),"continuous_expected_intervals":10,"continuous_observed_intervals":10,"continuous_missing_intervals":0},"data_quality":{"known_data_gaps":[]},"scientific_health":{"status":"PASS","output_hash":"d"*64,"checks":{"new_artifact_provenance":"PASS","replay":"PASS","dataset_hash":"PASS","output_hash":"PASS","forward_only":"PASS","observe_only":"PASS"}}}
    history=[{"generation_timestamp":"2026-07-31T22:00:00+00:00","fully_validated_cases":890},{"generation_timestamp":NOW.isoformat(),"fully_validated_cases":900}]
    value=build_readiness(snapshot,history,{"status":"PASS"})
    assert value["readiness_status"]=="NOT_READY_FOR_V2" and value["v2_approved"] is False
    assert value["criteria"]["validated_cases"]=="WAITING" and value["criteria"]["manual_scientific_review"]=="WAITING"
    assert value["criteria"]["continuous_coverage"]=="PASS" and value["artifact_hash"]


def test_readiness_is_reproducible():
    snapshot={"generation_timestamp":NOW.isoformat(),"snapshot_hash":"a"*64,"dataset_hash":"b"*64,"artifact_hash":"c"*64,"validation_status":"PASS","versions":{"core":"1.0.0"},"research_results":{"observations":1000,"fully_validated_cases":1000,"open_cases":0},"coverage":{"continuous_coverage_percent":"100.000"},"data_quality":{"known_data_gaps":[]},"scientific_health":{"status":"PASS","output_hash":"d"*64,"checks":{"new_artifact_provenance":"PASS","replay":"PASS","dataset_hash":"PASS","output_hash":"PASS","forward_only":"PASS","observe_only":"PASS"}}}
    history=[{"generation_timestamp":NOW.isoformat(),"fully_validated_cases":1000}]
    assert build_readiness(snapshot,history,{"status":"PASS"})==build_readiness(snapshot,history,{"status":"PASS"})
