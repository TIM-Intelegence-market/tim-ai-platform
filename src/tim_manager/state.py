from __future__ import annotations

import glob
import hashlib
import json
from pathlib import Path
from typing import Any

from .config import ARTIFACT_ROOT, PROJECT_ROOT, canonical_json, load_config
from .contradictions import detect_contradictions
from .scanner import stable_id


def build_module_states(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    paths = {item["normalized_path"]: item["artifact_id"] for item in artifacts}
    states: list[dict[str, Any]] = []
    for module in load_config("module_registry.yaml")["modules"]:
        evidence: list[str] = []
        for pattern in module["evidence_globs"]:
            for path in sorted(glob.glob(str(PROJECT_ROOT / pattern), recursive=True)):
                relative = Path(path).relative_to(PROJECT_ROOT).as_posix()
                if relative in paths:
                    evidence.append(paths[relative])
        implementation = any((PROJECT_ROOT / "src" / module["module_id"]).glob("*.py")) if (PROJECT_ROOT / "src" / module["module_id"]).exists() else bool(evidence)
        test_present = any("test" in next((path for path, identifier in paths.items() if identifier == evidence_id), "") for evidence_id in evidence)
        verified = [name for name, ok in (("implementation_present", implementation), ("test_present", test_present)) if ok]
        failed = [name for name, ok in (("implementation_present", implementation), ("test_present", test_present)) if not ok]
        status = "verified" if not failed else "implemented" if implementation else "unknown"
        states.append({
            "module_id": module["module_id"], "name": module["name"], "status": status,
            "phase": "evidence_scan", "acceptance_criteria": module["acceptance_criteria"],
            "verified_criteria": verified, "failed_criteria": failed, "blocked_criteria": [],
            "evidence_refs": sorted(set(evidence)), "risks": [],
            "last_changed_at": None,
            "calculation_method": "all configured required criteria require repository evidence; tests are detected, not executed by scanner",
        })
    return states


def build_snapshot(scan: dict[str, Any]) -> dict[str, Any]:
    missing_required = [item for item in scan["source_health"] if item["required"] and item["status"] != "reachable"]
    risks = [{
        "risk_id": stable_id("risk", "missing_source", item["source_id"]),
        "title": f"Required source unavailable: {item['source_id']}",
        "category": "source_coverage", "severity": "P1", "likelihood": "observed",
        "impact": "Project state cannot be fully verified", "status": "open",
        "evidence_refs": [item["source_id"]], "affected_modules": [], "mitigations": ["Restore or configure source"],
        "owner": None, "first_observed_at": scan["observed_at"], "last_observed_at": scan["observed_at"],
    } for item in missing_required]
    known_unknowns = [f"Required source unavailable: {item['source_id']}" for item in missing_required]
    contradictions = detect_contradictions(scan["artifacts"])
    artifact_projection = [
        {key: item[key] for key in ("artifact_id", "source_id", "normalized_path", "classification", "content_hash", "status", "metadata")}
        for item in scan["artifacts"]
    ]
    content = {
        "schema_version": "1.1",
        "repository_status": scan["repository"]["repository_status"],
        "repository_commit": scan["repository"]["repository_commit"],
        "authoritative_git_repository": scan["repository"]["authoritative_git_repository"],
        "repository_dirty": scan["repository"]["repository_dirty"],
        "parent_git_context": scan["repository"]["parent_git_context"],
        "content_manifest_hash": scan["content_manifest_hash"],
        "config_hash": scan["config_hash"],
        "source_health": scan["source_health"],
        "module_states": build_module_states(scan["artifacts"]),
        "risks": risks,
        "contradictions": contradictions,
        "data_gaps": [
            {
                "source_id": item["source_id"],
                "reason": "required_source_unavailable",
                "evidence": list(item["errors"]),
            }
            for item in missing_required
        ],
        "decisions": [],
        "open_decisions": [],
        "experiments": [],
        "evaluations": [],
        "recent_changes": scan["events"],
        "data_quality_summary": {"parser_errors": scan["stats"]["parser_errors"], "scan_errors": len(scan["errors"])},
        "coverage": {
            "configured_sources": len(scan["source_health"]),
            "reachable_sources": sum(item["status"] == "reachable" for item in scan["source_health"]),
            "missing_required_sources": len(missing_required),
            "global_progress": None,
            "global_progress_reason": "No explicit module weighting is configured.",
        },
        "known_unknowns": known_unknowns,
        "artifacts": artifact_projection,
    }
    # Runtime timestamps and the per-run recent-change view are deliberately
    # excluded. Identical project evidence therefore retains one snapshot ID.
    deterministic_projection = {
        "schema_version": content["schema_version"],
        "repository_status": content["repository_status"],
        "repository_commit": content["repository_commit"],
        "authoritative_git_repository": content["authoritative_git_repository"],
        "repository_dirty": content["repository_dirty"],
        "parent_git_context": content["parent_git_context"],
        "content_manifest_hash": content["content_manifest_hash"],
        "config_hash": content["config_hash"],
        "source_health": [
            {
                "source_id": item["source_id"], "source_type": item["source_type"],
                "required": item["required"], "status": item["status"],
                "trust_class": item["trust_class"], "read_only": item["read_only"],
                "freshness_status": item["freshness_status"], "errors": item["errors"],
            }
            for item in content["source_health"]
        ],
        "module_states": content["module_states"],
        "risks": [
            {key: value for key, value in item.items() if key not in {"first_observed_at", "last_observed_at"}}
            for item in content["risks"]
        ],
        "contradictions": content["contradictions"],
        "data_gaps": content["data_gaps"],
        "decisions": content["decisions"],
        "open_decisions": content["open_decisions"],
        "experiments": content["experiments"],
        "evaluations": content["evaluations"],
        "data_quality_summary": content["data_quality_summary"],
        "coverage": content["coverage"],
        "known_unknowns": content["known_unknowns"],
        "artifacts": content["artifacts"],
    }
    snapshot_hash = hashlib.sha256(canonical_json(deterministic_projection).encode()).hexdigest()
    return {
        "snapshot_id": stable_id("snapshot", snapshot_hash),
        "generated_at_utc": scan["observed_at"],
        **content,
        "provenance": {
            "scan_id": scan["scan_id"], "source_artifact_ids": [item["artifact_id"] for item in scan["artifacts"]],
            "source_hashes": [item["content_hash"] for item in scan["artifacts"]],
            "repository_status": scan["repository"]["repository_status"],
            "repository_commit": scan["repository"]["repository_commit"],
            "authoritative_git_repository": scan["repository"]["authoritative_git_repository"],
            "repository_dirty": scan["repository"]["repository_dirty"],
            "parent_git_context": scan["repository"]["parent_git_context"],
            "content_manifest_hash": scan["content_manifest_hash"],
            "manager_version": "1.0.0", "schema_version": "1.1", "config_hash": scan["config_hash"],
            "generated_at_utc": scan["observed_at"], "generation_method": "deterministic_state_builder",
            "model_used": None, "snapshot_hash": snapshot_hash,
        },
    }
