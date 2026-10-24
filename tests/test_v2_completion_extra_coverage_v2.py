from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.tim_manager.contradictions import (
    _canonical_claim_value,
    _claim_value,
    _interval,
    _parse_time,
    _temporal_relation,
    detect_contradictions,
)
from src.tim_v2.research import (
    ExperimentPlan,
    ExperimentResult,
    Hypothesis,
    PeerReview,
    ResearchArtifact,
    ResearchJob,
    ResearchRegistry,
    ResearchSession,
)
from src.tim_v2.research.models import ResearchStatus
from src.v2_completion.independent_cases import (
    CanonicalIndependentUnit,
    build_completion_audit,
    parse_time,
    validate_review_workbook,
)
from src.v2_completion.qualification import (
    REQUIRED_START_GATES,
    StartGate,
    activate_campaign,
    build_daily_manifest,
    build_preregistration,
    validate_start_gates,
    write_immutable_json,
)

UTC = timezone.utc
NOW = datetime(2026, 7, 28, tzinfo=UTC)


# ---------------------------------------------------------------- qualification
def _gates(status: str = "PASS") -> list[StartGate]:
    return [StartGate(name, status, f"evidence/{name}.json") for name in REQUIRED_START_GATES]


def _prereg(status: str = "PASS") -> dict:
    return build_preregistration(
        gates=_gates(status),
        software_commit="a" * 40,
        configuration_hash="b" * 64,
        current_independent_cases=300,
        observed_minutes=14400,
        generated_at=NOW,
    )


def test_start_gate_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown qualification start gate"):
        StartGate("nope", "PASS", "x")


def test_start_gate_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="start-gate status"):
        StartGate(REQUIRED_START_GATES[0], "MAYBE", "x")


def test_start_gate_rejects_blank_evidence() -> None:
    with pytest.raises(ValueError, match="evidence must be explicit"):
        StartGate(REQUIRED_START_GATES[0], "PASS", "   ")


def test_validate_start_gates_rejects_duplicates() -> None:
    gates = [StartGate(REQUIRED_START_GATES[0], "PASS", "x")] * 2
    with pytest.raises(ValueError, match="duplicate"):
        validate_start_gates(gates)


def test_validate_start_gates_rejects_missing_gates() -> None:
    with pytest.raises(ValueError, match="missing qualification start gates"):
        validate_start_gates([StartGate(REQUIRED_START_GATES[0], "PASS", "x")])


def test_activate_campaign_rejects_blocking_gates() -> None:
    value = _prereg()
    value["campaign_status"] = "ELIGIBLE_TO_START_EXPLICIT_START_ACTION_REQUIRED"
    value["blocking_start_gates"] = ["watchdog"]
    with pytest.raises(RuntimeError, match="blocking start gates"):
        activate_campaign(value, start=NOW, actual_commit="a" * 40)


def test_activate_campaign_rejects_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        activate_campaign(_prereg(), start=datetime(2026, 8, 2), actual_commit="a" * 40)


def active() -> dict:
    return activate_campaign(_prereg(), start=NOW, actual_commit="a" * 40)


def test_daily_manifest_rejects_naive_day() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_daily_manifest(active(), day=datetime(2026, 8, 2), metrics=None)


def test_daily_manifest_builds_full_payload() -> None:
    manifest = build_daily_manifest(
        active(),
        day=NOW,
        metrics={
            "coverage": 0.95,
            "gap_count": 0,
            "case_count": 2000,
            "independent_case_count": 0,
            "runtime_status": {"mode": "OBSERVE", "trading_actions": 0},
            "security_status": "OK",
            "incident_ids": [],
        },
    )
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["utc_date"] == "2026-07-28"
    assert "manifest_hash" in manifest
    assert manifest["trading_actions"] == 0


def test_write_immutable_json_creates_then_unchanged(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "manifest.json"
    payload = {"a": 1, "b": "two"}
    assert write_immutable_json(target, payload) == "CREATED"
    assert target.exists()
    assert write_immutable_json(target, payload) == "UNCHANGED"


def test_write_immutable_json_rejects_different_content(tmp_path: Path) -> None:
    target = tmp_path / "manifest.json"
    write_immutable_json(target, {"a": 1})
    with pytest.raises(FileExistsError, match="immutable manifest"):
        write_immutable_json(target, {"a": 2})


# ------------------------------------------------------- independent_cases
def icunit(index: int, *, start_minute: int = 0, sample_class: str = "POSITIVE") -> CanonicalIndependentUnit:
    start = datetime(2026, 8, 1, tzinfo=UTC) + timedelta(minutes=start_minute)
    return CanonicalIndependentUnit(
        unit_id=f"unit-{index}",
        start_utc=start,
        end_utc=start + timedelta(minutes=30),
        source_window="BTCUSDT:win",
        data_complete=True,
        gap_exposure=False,
        observation_id="obs" if sample_class == "POSITIVE" else None,
        label=sample_class,
        sample_class=sample_class,
        volatility_regime="MEDIUM",
        liquidity_regime="MEDIUM",
        session="EUROPE",
        weekday="SATURDAY",
        trend_regime="RANGE",
        reviewer_id=None,
        provenance="PUBLIC_BINANCE_SPOT",
        input_hash=f"{index:064x}",
    )


def test_unit_to_dict_and_iso() -> None:
    data = icunit(1).to_dict()
    assert data["start_utc"].endswith("Z")
    assert data["unit_id"] == "unit-1"


def test_parse_time_accepts_z_and_rejects_naive() -> None:
    assert parse_time("2026-08-01T00:00:00Z").tzinfo is UTC
    with pytest.raises(ValueError, match="timezone-aware"):
        parse_time("2026-08-01T00:00:00")


def test_unit_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        CanonicalIndependentUnit(
            "u", datetime(2026, 8, 1), datetime(2026, 8, 1), "w", True, False,
            None, "x", "POSITIVE", "M", "M", "S", "W", "R", None, "p", "a" * 64,
        )


def test_unit_rejects_wrong_duration() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="exactly 30 minutes"):
        CanonicalIndependentUnit(
            "u", start, start + timedelta(minutes=15), "w", True, False, None,
            "x", "POSITIVE", "M", "M", "S", "W", "R", None, "p", "a" * 64,
        )


def test_unit_rejects_invalid_sample_class() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="sample class"):
        CanonicalIndependentUnit(
            "u", start, start + timedelta(minutes=30), "w", True, False, None,
            "x", "BOGUS", "M", "M", "S", "W", "R", None, "p", "a" * 64,
        )


def test_unit_rejects_non_sha256_input_hash() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="SHA-256"):
        CanonicalIndependentUnit(
            "u", start, start + timedelta(minutes=30), "w", True, False, None,
            "x", "POSITIVE", "M", "M", "S", "W", "R", None, "p", "short",
        )


def test_build_completion_audit() -> None:
    audit = {
        "raw_complete_validation_rows": 1200,
        "quality_eligible_labels": 1100,
        "quality_eligible_underlying_windows": 1050,
        "strict_independent_30m_windows": 0,
        "required_independent_cases": 1000,
        "audit_hash": "x" * 64,
        "gate_status": "FAIL",
        "negative_or_control_sampling": {"NEGATIVE": 1, "NEUTRAL_CONTROL": 1},
    }
    baseline = {
        "scientific_case_audit": {
            "frozen_cutoff_audit": audit,
            "current_cutoff_audit": audit,
            "current_cutoff_utc": "2026-08-01T00:00:00Z",
        }
    }
    prereg = {"dataset_id": "V2", "campaign_status": "NOT_STARTED", "case_target": 1000}
    value = build_completion_audit(baseline=baseline, preregistration=prereg)
    assert value["schema_version"] == "1.0.0"
    assert value["scientific_gate"] == "FAIL"
    assert "audit_hash" in value
    assert value["qualification"]["required_units"] == 1000


def test_validate_review_workbook_complete_and_partial() -> None:
    workbook = {
        "selected_cases": [
            {
                "observation_id": "ok",
                "review": {
                    "reviewer_id": "r", "reviewed_at_utc": "now",
                    "data_quality": "good", "observation_correct": True,
                    "label_correct": True, "future_information_absent": True,
                    "narrative_adjustment_absent": True, "confidence_0_to_1": 0.9,
                    "decision": "MATCH", "rationale": "because",
                    "inter_rater_conflict": False,
                },
            },
            {"observation_id": "partial", "review": {"reviewer_id": "r"}},
        ],
        "approval": True,
    }
    check = validate_review_workbook(workbook)
    assert check["complete_human_decisions"] == 1
    assert check["invalid_partial_reviews"] == ["partial"]


# ---------------------------------------------------------------- research registry
def hyp(registry: ResearchRegistry) -> Hypothesis:
    return registry.add_hypothesis(
        Hypothesis("h1", "Bounded", ("e",), "owner", 0.7, ResearchStatus.DRAFT, NOW, NOW)
    )


def plan(registry: ResearchRegistry) -> ExperimentPlan:
    return registry.add_plan(
        ExperimentPlan("plan1", "1.0", hyp(registry).hypothesis_id, "key", "metric",
                       "split", "embargo", "code", "a" * 64)
    )


def session(registry: ResearchRegistry) -> ResearchSession:
    return registry.add_session(ResearchSession("s1", plan(registry).plan_id, "env", NOW))


def job(registry: ResearchRegistry) -> ResearchJob:
    return registry.add_job(ResearchJob("j1", session(registry).session_id, "h" * 64, "PLANNED"))


def test_registry_rejects_invalid_hypothesis() -> None:
    with pytest.raises(ValueError, match="HYPOTHESIS_INVALID"):
        ResearchRegistry().add_hypothesis(
            Hypothesis("h", "  ", (), "o", 0.9, ResearchStatus.DRAFT, NOW, NOW)
        )


def test_add_session_rejects_plan_tz_env() -> None:
    registry = ResearchRegistry()
    with pytest.raises(ValueError, match="RESEARCH_SESSION_INVALID"):
        registry.add_session(ResearchSession("s", "missing", "e", NOW))
    p = plan(registry)
    with pytest.raises(ValueError, match="RESEARCH_SESSION_INVALID"):
        registry.add_session(ResearchSession("s", p.plan_id, "", NOW))
    with pytest.raises(ValueError, match="RESEARCH_SESSION_INVALID"):
        registry.add_session(ResearchSession("s", p.plan_id, "e", datetime(2026, 7, 28)))


def test_add_job_rejects_session_and_status() -> None:
    registry = ResearchRegistry()
    with pytest.raises(ValueError, match="RESEARCH_JOB_INVALID"):
        registry.add_job(ResearchJob("j", "missing", "h" * 64, "PLANNED"))
    job(registry)
    with pytest.raises(ValueError, match="RESEARCH_JOB_INVALID"):
        registry.add_job(ResearchJob("j2", "s1", "h" * 64, "RUNNING"))


def test_add_artifact_rejects_job_hash_kind() -> None:
    registry = ResearchRegistry()
    with pytest.raises(ValueError, match="RESEARCH_ARTIFACT_INVALID"):
        registry.add_artifact(ResearchArtifact("a", "missing", "h" * 64, "kind"))
    job(registry)
    with pytest.raises(ValueError, match="RESEARCH_ARTIFACT_INVALID"):
        registry.add_artifact(ResearchArtifact("a", "j1", "short", "kind"))
    with pytest.raises(ValueError, match="RESEARCH_ARTIFACT_INVALID"):
        registry.add_artifact(ResearchArtifact("a", "j1", "h" * 64, ""))


def _valid_result(registry: ResearchRegistry) -> object:
    job(registry)
    registry.add_artifact(ResearchArtifact("a1", "j1", "h" * 64, "csv"))
    return registry.add_result(
        ExperimentResult("r1", "plan1", ResearchStatus.SUPPORTED, "ref", ("a1",), "h" * 64)
    )


def test_add_result_rejects_plan_artifact_hash() -> None:
    registry = ResearchRegistry()
    with pytest.raises(ValueError, match="EXPERIMENT_RESULT_INVALID"):
        registry.add_result(
            ExperimentResult("r", "missing", ResearchStatus.SUPPORTED, "ref", ("a1",), "h" * 64)
        )
    plan(registry)
    with pytest.raises(ValueError, match="EXPERIMENT_RESULT_INVALID"):
        registry.add_result(
            ExperimentResult("r", "plan1", ResearchStatus.SUPPORTED, "ref", ("missing-artifact",), "h" * 64)
        )
    job(registry)
    registry.add_artifact(ResearchArtifact("a1", "j1", "h" * 64, "csv"))
    with pytest.raises(ValueError, match="EXPERIMENT_RESULT_INVALID"):
        registry.add_result(
            ExperimentResult("r", "plan1", ResearchStatus.SUPPORTED, "ref", ("a1",), "short")
        )


def test_add_review_rejects_result_reviewer_outcome() -> None:
    registry = ResearchRegistry()
    with pytest.raises(ValueError, match="PEER_REVIEW_INVALID"):
        registry.add_review(PeerReview("rv", "missing", "someone", "approve", ()))
    _valid_result(registry)
    with pytest.raises(ValueError, match="PEER_REVIEW_INVALID"):
        registry.add_review(PeerReview("rv", "r1", "", "approve", ()))
    with pytest.raises(ValueError, match="PEER_REVIEW_INVALID"):
        registry.add_review(PeerReview("rv", "r1", "someone", "", ()))
    review = registry.add_review(PeerReview("rv", "r1", "someone", "approve", ()))
    assert review.review_id == "rv"


# ---------------------------------------------------------------- contradictions
def test_claim_value_keeps_non_string() -> None:
    assert _claim_value(42) == 42
    assert _claim_value("  active  ") == "active"


def test_canonical_claim_value_branches() -> None:
    assert _canonical_claim_value("status", "BLOCKED") == "blocked"
    assert _canonical_claim_value("x", True) is True
    assert _canonical_claim_value("x", "true") is True
    assert _canonical_claim_value("x", "FALSE") is False
    assert _canonical_claim_value("x", "banana") is None


def test_parse_time_invalid() -> None:
    assert _parse_time("not-a-date") is None
    assert _parse_time("") is None
    assert _parse_time("2026-08-01T00:00:00Z").tzinfo is not None


def test_interval_returns_start_end() -> None:
    claim = {"valid_from": "2026-08-01T00:00:00Z", "valid_to": "2026-08-01T01:00:00Z"}
    start, end = _interval(claim)
    assert end > start


def test_temporal_relation_non_overlapping_reverse() -> None:
    left = {"valid_from": "2026-08-01T10:00:00Z", "valid_to": "2026-08-01T11:00:00Z"}
    right = {"valid_from": "2026-08-01T08:00:00Z", "valid_to": "2026-08-01T09:00:00Z"}
    assert _temporal_relation(left, right) == (False, "non_overlapping")


def test_temporal_relation_overlapping() -> None:
    left = {"valid_from": "2026-08-01T10:00:00Z", "valid_to": "2026-08-01T11:00:00Z"}
    right = {"valid_from": "2026-08-01T10:30:00Z", "valid_to": "2026-08-01T11:30:00Z"}
    assert _temporal_relation(left, right) == (True, "overlapping")


def _artifact(case_id: str, value: object, *, claim_type: str = "observed_fact", **extra) -> dict:
    claim = {"subject": "s-1", "predicate": "status", "value": value, "claim_type": claim_type}
    claim.update(extra)
    return {"artifact_id": case_id, "classification": "artifact", "metadata": {"claims": [claim]}}


def test_evidence_refs_fall_back_to_artifact() -> None:
    out = detect_contradictions([
        _artifact("a", "complete", evidence_refs=None),
        _artifact("b", "blocked"),
    ])
    assert out and out[0]["claims"]


def test_missing_subject_claim_is_skipped() -> None:
    bad = {"classification": "artifact", "artifact_id": "x",
           "metadata": {"claims": [{"value": "v"}]}}
    assert detect_contradictions([bad]) == []


def test_unknown_claim_type_normalizes() -> None:
    out = detect_contradictions([
        _artifact("a", "complete", claim_type="weird_type"),
        _artifact("b", "blocked"),
    ])
    assert out and out[0]["claims"][0]["claim_type"] == "unknown"


def test_single_claim_dict_metadata() -> None:
    out = detect_contradictions([
        {"artifact_id": "a", "classification": "artifact",
         "metadata": {"claim": {"subject": "s", "predicate": "status", "value": "complete"}}}
    ])
    assert out == []


def test_non_dict_claim_entries_are_skipped() -> None:
    out = detect_contradictions([
        {"artifact_id": "a", "classification": "artifact", "metadata": {"claims": ["junk"]}},
        {"artifact_id": "b", "classification": "artifact", "metadata": {"claims": ["junk"]}},
    ])
    assert out == []