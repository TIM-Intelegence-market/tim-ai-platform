from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    source_type: str
    required: bool
    status: str
    trust_class: str
    read_only: bool = True
    configured_at: str | None = None
    last_scan_at: str | None = None
    last_success_at: str | None = None
    freshness_status: str = "unknown"
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["errors"] = list(self.errors)
        return result


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    source_id: str
    normalized_path: str
    artifact_type: str
    classification: str
    content_hash: str
    size_bytes: int
    created_at: str | None
    modified_at: str | None
    observed_at: str
    schema_version: str = "1.0"
    parser_version: str = "1.0"
    sensitivity: str = "internal"
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectEvent:
    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    occurred_at: str
    observed_at: str
    source_refs: tuple[str, ...]
    payload: dict[str, Any]
    event_version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source_refs"] = list(self.source_refs)
        return result


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    subject: str
    predicate: str
    object: Any
    claim_type: str
    status: str
    evidence_refs: tuple[str, ...]
    contradiction_refs: tuple[str, ...] = ()
    freshness: str = "unknown"
    created_by: str = "deterministic_extractor"
    model_metadata: dict[str, Any] | None = None
    valid_at: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    superseded_by: str | None = None
    source_classification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence_refs"] = list(self.evidence_refs)
        result["contradiction_refs"] = list(self.contradiction_refs)
        return result


@dataclass(frozen=True)
class ContradictionRecord:
    contradiction_id: str
    subject: str
    predicate: str
    claims: tuple[dict[str, Any], ...]
    severity: str
    resolution_status: str
    contradiction_type: str
    temporal_resolution: str
    preferred_claim_id: str | None = None
    preference_reason: str | None = None
    contradicting_claims_preserved: bool = True

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["claims"] = list(self.claims)
        return result
