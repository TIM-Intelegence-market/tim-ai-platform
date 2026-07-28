import json

from src.analytics.research import ResearchAnalyticsEngine


def fixture():
    observations = [
        {"observation_id": "o1", "kind": "REJECTION", "rule_id": "rejection", "rule_version": "1.0.0", "timeframe": "5m", "observed_at": "2026-07-20T10:00:00Z", "confidence": 60},
        {"observation_id": "o2", "kind": "REJECTION", "rule_id": "rejection", "rule_version": "1.0.0", "timeframe": "15m", "observed_at": "2026-07-20T10:05:00Z", "confidence": 60},
    ]
    cases = [{"case_id": "c1", "opened_at": "2026-07-20T10:00:00Z", "updated_at": "2026-07-20T11:00:00Z", "status": "CONFIRMED", "outcome": "FOLLOW_THROUGH", "missing_evidence": ["volume"], "observation_ids": ["o1", "o2"]}]
    events = [{"timestamp": "2026-07-20T12:00:00Z", "event": "DATA_GAP"}, {"timestamp": "2026-07-20T12:01:00Z", "event": "VALIDATION_CYCLE"}, {"timestamp": "2026-07-20T12:02:00Z", "event": "RESTART"}]
    return observations, cases, events


def test_rule_statistics_are_exact_and_use_only_persisted_values():
    result = ResearchAnalyticsEngine().analyze(*fixture())
    rule = result["rules"][0]
    assert rule["count"] == 2
    assert rule["average_duration_seconds"] == 300.0
    assert rule["average_timeframes_per_case"] == 2.0
    assert rule["most_common_missing_evidence"] == ["volume"]
    assert rule["most_common_outcomes"] == ["FOLLOW_THROUGH"]
    assert rule["confirmed_rate_percent"] == 100.0
    assert rule["invalidation_rate_percent"] == rule["closed_rate_percent"] == 0.0
    assert rule["average_lifetime_seconds"] == 3600.0


def test_clusters_timeline_and_quality_are_deterministic():
    engine = ResearchAnalyticsEngine(); data = fixture()
    first = engine.analyze(*data); second = engine.analyze(*data)
    assert first == second
    assert len(first["case_clusters"]) == 2
    assert {item["stored_evidence_score"] for item in first["case_clusters"]} == {"60"}
    assert first["timeline"]["research_cases_per_hour"] == {"2026-07-20T10:00Z": 1}
    assert first["timeline"]["observation_frequency"] == {"REJECTION": 2}
    assert first["data_quality"] == {"gap_events": 1, "validator_events": 1, "governance_rejects": 0, "replay_runs": 0, "integrity_errors": 0}


def test_exports_are_repeatable_and_machine_readable():
    engine = ResearchAnalyticsEngine(); result = engine.analyze(*fixture())
    assert engine.to_json(result) == engine.to_json(result)
    assert json.loads(engine.to_json(result))["dataset_hash"] == result["dataset_hash"]
    assert "section,identifier,metric,value" in engine.to_csv(result)
    assert "# TIM Research Analytics" in engine.to_markdown(result)
