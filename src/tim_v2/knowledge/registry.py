"""In-memory immutable knowledge registry with explicit abstention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import Claim, ClaimStatus, Contradiction, DecisionHistory, Evidence, Fact, ResearchLink, Source


@dataclass(frozen=True)
class QueryResult:
    state: str
    claims: tuple[Claim, ...]
    reason: str | None = None


class KnowledgeRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._evidence: dict[str, Evidence] = {}
        self._claims: dict[str, Claim] = {}
        self._facts: dict[str, Fact] = {}
        self._contradictions: dict[str, Contradiction] = {}
        self._decisions: dict[str, DecisionHistory] = {}
        self._research_links: dict[str, ResearchLink] = {}

    def add_source(self, source: Source) -> Source:
        self._insert(self._sources, source.source_id, source, source.issues())
        return source

    def add_evidence(self, evidence: Evidence) -> Evidence:
        issues = list(evidence.issues())
        if evidence.source_id not in self._sources:
            issues.append("EVIDENCE_SOURCE_NOT_FOUND")
        self._insert(self._evidence, evidence.evidence_id, evidence, tuple(issues))
        return evidence

    def add_claim(self, claim: Claim) -> Claim:
        issues = list(claim.issues())
        issues.extend(f"CLAIM_EVIDENCE_NOT_FOUND:{ref}" for ref in claim.evidence_ids if ref not in self._evidence)
        self._insert(self._claims, claim.claim_id, claim, tuple(issues))
        return claim

    def add_fact(self, fact: Fact) -> Fact:
        if fact.claim_id not in self._claims or self._claims[fact.claim_id].status is not ClaimStatus.SUPPORTED:
            raise ValueError("FACT_REQUIRES_SUPPORTED_CLAIM")
        if not fact.validation_policy.strip() or fact.validated_at.tzinfo is None:
            raise ValueError("FACT_VALIDATION_INVALID")
        self._insert(self._facts, fact.fact_id, fact, ())
        return fact

    def add_contradiction(self, contradiction: Contradiction) -> Contradiction:
        if contradiction.left_claim_id == contradiction.right_claim_id:
            raise ValueError("CONTRADICTION_SELF_REFERENCE")
        if contradiction.left_claim_id not in self._claims or contradiction.right_claim_id not in self._claims:
            raise ValueError("CONTRADICTION_CLAIM_NOT_FOUND")
        if not contradiction.method.strip() or not contradiction.status.strip():
            raise ValueError("CONTRADICTION_METADATA_REQUIRED")
        self._insert(self._contradictions, contradiction.contradiction_id, contradiction, ())
        return contradiction

    def add_decision_history(self, decision: DecisionHistory) -> DecisionHistory:
        if not decision.rationale.strip() or not decision.approver.strip() or decision.decided_at.tzinfo is None:
            raise ValueError("DECISION_HISTORY_METADATA_REQUIRED")
        if any(claim_id not in self._claims for claim_id in decision.claim_ids):
            raise ValueError("DECISION_HISTORY_CLAIM_NOT_FOUND")
        self._insert(self._decisions, decision.decision_id, decision, ())
        return decision

    def add_research_link(self, link: ResearchLink) -> ResearchLink:
        if link.claim_id not in self._claims or not link.research_reference.strip() or not link.relationship.strip():
            raise ValueError("RESEARCH_LINK_INVALID")
        self._insert(self._research_links, link.link_id, link, ())
        return link

    def trace(self, claim_id: str) -> tuple[Evidence, ...]:
        claim = self._claims.get(claim_id)
        if claim is None:
            return ()
        return tuple(self._evidence[key] for key in claim.evidence_ids)

    def query_at(self, at: datetime) -> QueryResult:
        matches = tuple(claim for claim in self._claims.values() if claim.valid_time.contains(at))
        if not matches:
            return QueryResult("ABSTAIN", (), "NO_SUPPORTED_CLAIM_AT_TIME")
        unsupported = tuple(claim for claim in matches if claim.status is not ClaimStatus.SUPPORTED)
        if unsupported:
            return QueryResult("ABSTAIN", (), "CLAIM_NOT_SUPPORTED")
        matched_ids = {claim.claim_id for claim in matches}
        if any(contradiction.status != "RESOLVED" and {contradiction.left_claim_id, contradiction.right_claim_id} <= matched_ids for contradiction in self._contradictions.values()):
            return QueryResult("ABSTAIN", (), "UNRESOLVED_CONTRADICTION")
        return QueryResult("SUPPORTED", tuple(sorted(matches, key=lambda claim: claim.claim_id)))

    @staticmethod
    def _insert(store: dict[str, object], key: str, value: object, issues: tuple[str, ...]) -> None:
        if issues:
            raise ValueError(";".join(issues))
        current = store.get(key)
        if current is None:
            store[key] = value
        elif current != value:
            raise ValueError(f"IMMUTABLE_RECORD_CONFLICT:{key}")
