"""Pure knowledge objects. No retrieval index, I/O, model or TIM-IM write path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import re


SHA256 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")


class ClaimStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime

    def contains(self, at: datetime) -> bool:
        return self.start <= at <= self.end

    def valid(self) -> bool:
        return self.start.tzinfo is not None and self.end.tzinfo is not None and self.start <= self.end


@dataclass(frozen=True)
class Source:
    source_id: str
    locator: str
    content_sha256: str
    license_name: str
    trust_level: str
    created_at: datetime

    def issues(self) -> tuple[str, ...]:
        return tuple(code for valid, code in ((bool(IDENTIFIER.fullmatch(self.source_id)), "SOURCE_ID_INVALID"), (bool(self.locator.strip()), "SOURCE_LOCATOR_REQUIRED"), (bool(SHA256.fullmatch(self.content_sha256)), "SOURCE_HASH_INVALID"), (bool(self.license_name.strip()), "SOURCE_LICENSE_REQUIRED"), (bool(self.trust_level.strip()), "SOURCE_TRUST_REQUIRED"), (self.created_at.tzinfo is not None, "SOURCE_TIMEZONE_REQUIRED")) if not valid)


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    content_sha256: str
    observed_at: datetime
    valid_time: TimeRange
    excerpt_reference: str
    provenance: str

    def issues(self) -> tuple[str, ...]:
        return tuple(code for valid, code in ((bool(IDENTIFIER.fullmatch(self.evidence_id)), "EVIDENCE_ID_INVALID"), (bool(IDENTIFIER.fullmatch(self.source_id)), "EVIDENCE_SOURCE_ID_INVALID"), (bool(SHA256.fullmatch(self.content_sha256)), "EVIDENCE_HASH_INVALID"), (self.observed_at.tzinfo is not None, "EVIDENCE_TIMEZONE_REQUIRED"), (self.valid_time.valid(), "EVIDENCE_VALID_TIME_INVALID"), (bool(self.excerpt_reference.strip()), "EVIDENCE_REFERENCE_REQUIRED"), (bool(self.provenance.strip()), "EVIDENCE_PROVENANCE_REQUIRED")) if not valid)


@dataclass(frozen=True)
class Claim:
    claim_id: str
    proposition: str
    evidence_ids: tuple[str, ...]
    confidence: float
    status: ClaimStatus
    valid_time: TimeRange
    created_at: datetime

    def issues(self) -> tuple[str, ...]:
        return tuple(code for valid, code in ((bool(IDENTIFIER.fullmatch(self.claim_id)), "CLAIM_ID_INVALID"), (bool(self.proposition.strip()), "CLAIM_PROPOSITION_REQUIRED"), (bool(self.evidence_ids), "CLAIM_EVIDENCE_REQUIRED"), (len(set(self.evidence_ids)) == len(self.evidence_ids), "CLAIM_EVIDENCE_DUPLICATE"), (0 <= self.confidence <= 1, "CLAIM_CONFIDENCE_INVALID"), (self.valid_time.valid(), "CLAIM_VALID_TIME_INVALID"), (self.created_at.tzinfo is not None, "CLAIM_TIMEZONE_REQUIRED")) if not valid)


@dataclass(frozen=True)
class Fact:
    fact_id: str
    claim_id: str
    validation_policy: str
    validated_at: datetime


@dataclass(frozen=True)
class Observation:
    observation_id: str
    dataset_key: str
    observed_at: datetime
    value_reference: str
    provenance: str


@dataclass(frozen=True)
class Contradiction:
    contradiction_id: str
    left_claim_id: str
    right_claim_id: str
    method: str
    status: str


@dataclass(frozen=True)
class DecisionHistory:
    decision_id: str
    claim_ids: tuple[str, ...]
    rationale: str
    approver: str
    decided_at: datetime


@dataclass(frozen=True)
class ResearchLink:
    link_id: str
    claim_id: str
    research_reference: str
    relationship: str
