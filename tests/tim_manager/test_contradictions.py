from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.tim_manager.adapters import structured_metadata
from src.tim_manager.contradictions import detect_contradictions
from src.tim_manager.query import answer
from src.tim_manager.reporting import generate_reports
from src.tim_manager.state import build_snapshot


def artifact(
    artifact_id: str,
    value: Any,
    *,
    claim_type: str = "validated_result",
    **claim_fields: Any,
) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "source_id": f"source-{artifact_id}",
        "normalized_path": f"{artifact_id}.json",
        "classification": "artifact",
        "content_hash": artifact_id * 64,
        "status": "active",
        "metadata": {
            "claims": [{
                "subject": "orderflow_pilot",
                "predicate": "status",
                "value": value,
                "claim_type": claim_type,
                "evidence_refs": [artifact_id],
                **claim_fields,
            }]
        },
    }


def scan(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "observed_at": "2026-07-28T00:00:00+00:00",
        "content_manifest_hash": "0" * 64,
        "config_hash": "1" * 64,
        "repository": {
            "repository_status": "unversioned",
            "repository_commit": None,
            "authoritative_git_repository": False,
            "repository_dirty": None,
            "parent_git_context": {},
        },
        "source_health": [],
        "artifacts": artifacts,
        "events": [],
        "stats": {"parser_errors": 0},
        "errors": [],
        "scan_id": "scan",
    }


def conflicting_artifacts() -> list[dict[str, Any]]:
    return [artifact("a", "complete"), artifact("b", "blocked")]


def test_namespaced_json_claims_are_passively_extracted(tmp_path: Path) -> None:
    payload = b"""{
      "tim_manager_claims": [{
        "subject": "orderflow_pilot",
        "predicate": "status",
        "value": "complete",
        "claim_type": "validated_result"
      }]
    }"""
    artifact_type, metadata, errors = structured_metadata(tmp_path / "claim.json", payload)
    assert artifact_type == "json"
    assert errors == []
    assert metadata["claims"][0]["subject"] == "orderflow_pilot"


def test_direct_status_contradiction_is_detected() -> None:
    contradictions = detect_contradictions(conflicting_artifacts())
    assert len(contradictions) == 1
    assert contradictions[0]["contradiction_type"] == "direct_fact_conflict"
    assert contradictions[0]["resolution_status"] == "unresolved"
    assert contradictions[0]["temporal_resolution"] == "unknown"


def test_both_evidence_references_are_preserved() -> None:
    contradiction = detect_contradictions(conflicting_artifacts())[0]
    assert {
        reference
        for claim in contradiction["claims"]
        for reference in claim["evidence_refs"]
    } == {"a", "b"}
    assert all(
        claim["contradiction_refs"] == [contradiction["contradiction_id"]]
        for claim in contradiction["claims"]
    )
    assert contradiction["contradicting_claims_preserved"] is True


def test_contradiction_appears_in_snapshot() -> None:
    snapshot = build_snapshot(scan(conflicting_artifacts()))
    assert snapshot["schema_version"] == "1.1"
    assert snapshot["provenance"]["schema_version"] == "1.1"
    assert len(snapshot["contradictions"]) == 1
    assert snapshot["contradictions"][0]["subject"] == "orderflow_pilot"


def test_contradiction_appears_in_query() -> None:
    snapshot = build_snapshot(scan(conflicting_artifacts()))
    result = answer("Show contradictions for the Orderflow Pilot status", snapshot)
    assert result["status"] == "unresolved"
    assert len(result["contradictions"]) == 1
    assert result["evidence"] == ["a", "b"]


def test_contradiction_appears_in_status_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    written: dict[str, str] = {}

    def capture(relative: str, content: str) -> Path:
        written[relative] = content
        return tmp_path / Path(relative).name

    monkeypatch.setattr("src.tim_manager.reporting._write", capture)
    generate_reports(build_snapshot(scan(conflicting_artifacts())))
    status = written["artifacts/tim_manager/reports/current_status.md"]
    assert "## Contradictions" in status
    assert "orderflow_pilot.status" in status
    assert "complete vs blocked" in status
    assert "a, b" in status


def test_non_overlapping_periods_do_not_conflict() -> None:
    artifacts = [
        artifact("a", "blocked", valid_at="2026-07-01T00:00:00+00:00"),
        artifact("b", "complete", valid_at="2026-07-20T00:00:00+00:00"),
    ]
    assert detect_contradictions(artifacts) == []


def test_different_measurement_methods_do_not_create_direct_conflict() -> None:
    artifacts = [
        artifact("a", "complete", measurement_method="integration_test"),
        artifact("b", "blocked", measurement_method="manual_review"),
    ]
    assert detect_contradictions(artifacts) == []


def test_superseded_claim_does_not_create_open_contradiction() -> None:
    artifacts = [
        artifact("a", "blocked", status="superseded", superseded_by="b"),
        artifact("b", "complete"),
    ]
    assert detect_contradictions(artifacts) == []


def test_model_interpretation_does_not_override_validated_result() -> None:
    contradiction = detect_contradictions([
        artifact("a", "complete", claim_type="validated_result"),
        artifact("b", "blocked", claim_type="model_inference"),
    ])[0]
    claims = {claim["claim_type"]: claim for claim in contradiction["claims"]}
    assert contradiction["contradiction_type"] == "interpretation_conflict"
    assert contradiction["preferred_claim_id"] == claims["validated_result"]["claim_id"]
    assert contradiction["resolution_status"] == "provisionally_resolved"
    assert {claim["value"] for claim in contradiction["claims"]} == {"complete", "blocked"}


def test_identical_claims_do_not_conflict() -> None:
    assert detect_contradictions([artifact("a", "complete"), artifact("b", "complete")]) == []


def test_second_unchanged_build_has_no_duplicate_contradiction() -> None:
    first = build_snapshot(scan(conflicting_artifacts()))
    second = build_snapshot(scan(conflicting_artifacts()))
    assert len(first["contradictions"]) == len(second["contradictions"]) == 1
    assert first["contradictions"] == second["contradictions"]
    assert first["snapshot_id"] == second["snapshot_id"]


def test_contradiction_id_is_stable_across_input_order() -> None:
    forward = detect_contradictions(conflicting_artifacts())[0]["contradiction_id"]
    reverse = detect_contradictions(list(reversed(conflicting_artifacts())))[0]["contradiction_id"]
    assert forward == reverse
