from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import FilesystemAdapter, GitAdapter, structured_metadata
from .config import ARTIFACT_ROOT, PROJECT_ROOT, canonical_json, load_config
from .models import ArtifactRecord, ProjectEvent, SourceRecord
from .security import normalize_relative, safe_output_path
from .storage import ManagerStore


NAMESPACE = uuid.UUID("9fca0642-7893-5de9-8ba4-3cf49d52eeb5")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, "|".join((kind, *parts))))


def config_hash() -> str:
    names = ("sources.yaml", "protected_paths.yaml", "module_registry.yaml", "classification_rules.yaml", "routing.yaml", "reporting.yaml")
    payload = {name: load_config(name) for name in names}
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


def freshness_status(latest_modified_at: str | None, observed_at: str, expected_hours: int | float | None) -> str:
    """Classify source freshness from evidence, never from reachability alone."""
    if latest_modified_at is None or expected_hours is None:
        return "unknown"
    latest = datetime.fromisoformat(latest_modified_at)
    observed = datetime.fromisoformat(observed_at)
    age_hours = max(0.0, (observed - latest).total_seconds() / 3600)
    return "current" if age_hours <= float(expected_hours) else "stale"


def classify(path: str) -> tuple[str, str]:
    import fnmatch
    for rule in load_config("classification_rules.yaml")["rules"]:
        if fnmatch.fnmatch(path, rule["pattern"]):
            return rule["classification"], rule["source_tier"]
    return "unknown", "unknown"


def content_manifest_hash(artifacts: list[dict[str, Any]]) -> str:
    """Hash stable source identity without borrowing a parent Git commit."""
    manifest = [
        {
            "source_id": item["source_id"],
            "normalized_path": item["normalized_path"],
            "content_hash": item["content_hash"],
            "size_bytes": item["size_bytes"],
            "status": item["status"],
        }
        for item in sorted(
            artifacts,
            key=lambda item: (item["source_id"], item["normalized_path"]),
        )
    ]
    return hashlib.sha256(canonical_json(manifest).encode()).hexdigest()


def _event(event_type: str, entity_id: str, content_hash: str, observed_at: str, payload: dict[str, Any]) -> dict[str, Any]:
    event_id = stable_id("event", event_type, entity_id, content_hash)
    return ProjectEvent(
        event_id=event_id,
        event_type=event_type,
        entity_type="artifact",
        entity_id=entity_id,
        occurred_at=payload.get("modified_at") or observed_at,
        observed_at=observed_at,
        source_refs=(entity_id,),
        payload=payload,
    ).to_dict()


def scan_project(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    observed_at = utc_now()
    scan_id = stable_id("scan", config_hash(), observed_at)
    store_path = safe_output_path("artifacts/tim_manager/indexes/tim_manager.sqlite3")
    store = ManagerStore(store_path)
    previous = store.artifacts()
    current: dict[str, dict[str, Any]] = {}
    source_health: list[dict[str, Any]] = []
    emitted: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    stats = {"new": 0, "changed": 0, "deleted": 0, "moved": 0, "unchanged": 0, "parser_errors": 0}
    git = GitAdapter(root).metadata()
    cfg_hash = config_hash()
    try:
        for source in load_config("sources.yaml")["sources"]:
            if not source.get("enabled"):
                source_health.append(SourceRecord(
                    source_id=source["source_id"], source_type=source["adapter"], required=source.get("required", False),
                    status="disabled", trust_class=source["trust_class"], last_scan_at=observed_at,
                    freshness_status="not_applicable",
                ).to_dict())
                continue
            if source["adapter"] == "git":
                health = GitAdapter(root).health_check()
                source_health.append(SourceRecord(
                    source_id=source["source_id"], source_type="git", required=source.get("required", False),
                    status=health["status"], trust_class=source["trust_class"], last_scan_at=observed_at,
                    last_success_at=observed_at if health["status"] == "reachable" else None,
                    freshness_status="current" if health["status"] == "reachable" else "unknown",
                ).to_dict())
                continue
            if source["adapter"] != "filesystem":
                source_health.append(SourceRecord(
                    source_id=source["source_id"], source_type=source["adapter"], required=source.get("required", False),
                    status="unsupported", trust_class=source["trust_class"], last_scan_at=observed_at,
                    freshness_status="not_applicable",
                ).to_dict())
                continue
            adapter = FilesystemAdapter(source, root)
            health = adapter.health_check()
            source_errors: list[str] = []
            count = 0
            latest_modified_at: str | None = None
            for path in adapter.list_artifacts():
                count += 1
                relative = normalize_relative(path, root)
                metadata = adapter.read_metadata(path)
                digest = adapter.compute_fingerprint(path)
                artifact_id = stable_id("artifact", source["source_id"], relative)
                classification, source_tier = classify(relative)
                max_bytes = int(source.get("max_file_size_mb", 20) * 1024 * 1024)
                content = b""
                parse_metadata: dict[str, Any] = {"source_tier": source_tier}
                parse_errors: list[str] = []
                if metadata["size_bytes"] <= max_bytes:
                    content = adapter.read_content(path, max_bytes)
                    artifact_type, parsed, parse_errors = structured_metadata(path, content)
                    parse_metadata.update(parsed)
                else:
                    artifact_type = path.suffix.lstrip(".") or "binary"
                    parse_metadata["metadata_only"] = True
                if parse_errors:
                    stats["parser_errors"] += len(parse_errors)
                    source_errors.extend(f"{relative}:{item}" for item in parse_errors)
                    errors.extend({"path": relative, "error": item} for item in parse_errors)
                modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                if latest_modified_at is None or modified_at > latest_modified_at:
                    latest_modified_at = modified_at
                record = ArtifactRecord(
                    artifact_id=artifact_id,
                    source_id=source["source_id"],
                    normalized_path=relative,
                    artifact_type=artifact_type,
                    classification=classification,
                    content_hash=digest,
                    size_bytes=metadata["size_bytes"],
                    created_at=None,
                    modified_at=modified_at,
                    observed_at=observed_at,
                    sensitivity="internal",
                    status="invalid" if parse_errors else "active",
                    metadata={**parse_metadata, "parser_errors": parse_errors},
                    provenance={
                        "scan_id": scan_id, "source_id": source["source_id"], "source_hashes": [digest],
                        "repository_status": git["repository_status"],
                        "repository_commit": git["repository_commit"],
                        "authoritative_git_repository": git["authoritative_git_repository"],
                        "repository_dirty": git["repository_dirty"],
                        "parent_git_context": git["parent_git_context"],
                        "manager_version": __version__, "schema_version": "1.0", "config_hash": cfg_hash,
                        "generated_at_utc": observed_at, "generation_method": "deterministic_filesystem_scan",
                        "model_used": None,
                    },
                ).to_dict()
                old = previous.get(relative)
                if old is None:
                    same_hash_old = next((item for old_path, item in previous.items() if old_path not in current and item["content_hash"] == digest), None)
                    event_type = "artifact_moved" if same_hash_old else "artifact_added"
                    stats["moved" if same_hash_old else "new"] += 1
                elif old["content_hash"] != digest:
                    event_type = "artifact_changed"
                    stats["changed"] += 1
                else:
                    event_type = ""
                    stats["unchanged"] += 1
                current[relative] = record
                searchable = content.decode("utf-8", errors="replace") if content and b"\x00" not in content[:4096] else ""
                store.upsert_artifact(record, searchable)
                if event_type:
                    event = _event(event_type, artifact_id, digest, observed_at, {"path": relative, "modified_at": modified_at, "content_hash": digest})
                    if store.add_event(event):
                        emitted.append(event)
            status = health["status"]
            if source.get("required") and count == 0:
                status = "missing"
                source_errors.append("NO_ARTIFACTS_DISCOVERED")
            source_health.append(SourceRecord(
                source_id=source["source_id"], source_type="filesystem", required=source.get("required", False),
                status=status, trust_class=source["trust_class"], last_scan_at=observed_at,
                last_success_at=observed_at if status == "reachable" else None,
                freshness_status=freshness_status(
                    latest_modified_at,
                    observed_at,
                    source.get("freshness_policy", {}).get("expected_update_interval_hours"),
                ) if status == "reachable" else "unknown",
                errors=tuple(source_errors),
            ).to_dict())
        for relative, record in previous.items():
            if relative in current:
                continue
            event = _event("artifact_deleted", record["artifact_id"], record["content_hash"], observed_at, {"path": relative, "content_hash": record["content_hash"], "tombstone": True})
            if store.add_event(event):
                emitted.append(event)
            store.delete_artifact(relative)
            stats["deleted"] += 1
        store.commit()
    finally:
        store.close()
    artifacts = sorted(current.values(), key=lambda item: item["normalized_path"])
    return {
        "scan_id": scan_id,
        "observed_at": observed_at,
        "config_hash": cfg_hash,
        "content_manifest_hash": content_manifest_hash(artifacts),
        "repository": git,
        "source_health": source_health,
        "artifacts": artifacts,
        "events": emitted,
        "stats": stats,
        "errors": errors,
    }
