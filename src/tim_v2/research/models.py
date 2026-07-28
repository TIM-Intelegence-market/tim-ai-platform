from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
import hashlib
import json


class ResearchStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class Hypothesis:
    hypothesis_id: str
    proposition: str
    evidence_ids: tuple[str, ...]
    owner: str
    confidence: float
    status: ResearchStatus
    valid_from: datetime
    valid_until: datetime


@dataclass(frozen=True)
class ExperimentPlan:
    plan_id: str
    version: str
    hypothesis_id: str
    dataset_key: str
    metric: str
    split_manifest: str
    leakage_control: str
    code_version: str
    configuration_hash: str
    parameters: dict[str, str] = field(default_factory=dict)

    def manifest_sha256(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ResearchSession:
    session_id: str
    plan_id: str
    environment_id: str
    created_at: datetime


@dataclass(frozen=True)
class ResearchJob:
    job_id: str
    session_id: str
    plan_manifest_sha256: str
    status: str = "PLANNED"


@dataclass(frozen=True)
class ResearchArtifact:
    artifact_id: str
    job_id: str
    content_sha256: str
    kind: str


@dataclass(frozen=True)
class ExperimentResult:
    result_id: str
    plan_id: str
    status: ResearchStatus
    statistic_reference: str
    artifact_ids: tuple[str, ...]
    reproducibility_hash: str


@dataclass(frozen=True)
class PeerReview:
    review_id: str
    result_id: str
    reviewer: str
    outcome: str
    limitations: tuple[str, ...]
