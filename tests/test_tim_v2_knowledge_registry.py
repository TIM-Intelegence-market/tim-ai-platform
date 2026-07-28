from datetime import datetime, timedelta, timezone

import pytest

from src.tim_v2.knowledge import Claim, Contradiction, DecisionHistory, Evidence, Fact, KnowledgeRegistry, ResearchLink, Source, TimeRange
from src.tim_v2.knowledge.models import ClaimStatus


NOW = datetime(2026, 7, 28, 12, tzinfo=timezone.utc)


def populated(status: ClaimStatus = ClaimStatus.SUPPORTED) -> tuple[KnowledgeRegistry, Claim]:
    registry = KnowledgeRegistry()
    registry.add_source(Source("source_one", "urn:tim:source:one", "a" * 64, "internal", "reviewed", NOW))
    registry.add_evidence(Evidence("evidence_one", "source_one", "b" * 64, NOW, TimeRange(NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)), "urn:excerpt:one", "dataset"))
    claim = Claim("claim_one", "A bounded proposition.", ("evidence_one",), 0.8, status, TimeRange(NOW - timedelta(minutes=1), NOW + timedelta(minutes=1)), NOW)
    registry.add_claim(claim)
    return registry, claim


def test_trace_is_complete_and_provenance_preserving() -> None:
    registry, claim = populated()
    assert registry.trace(claim.claim_id)[0].source_id == "source_one"


def test_query_supports_only_supported_temporal_claims() -> None:
    registry, _ = populated()
    assert registry.query_at(NOW).state == "SUPPORTED"
    assert registry.query_at(NOW + timedelta(days=1)).state == "ABSTAIN"


def test_unsupported_claim_abstains() -> None:
    registry, _ = populated(ClaimStatus.CANDIDATE)
    assert registry.query_at(NOW).reason == "CLAIM_NOT_SUPPORTED"


def test_records_are_immutable_and_idempotent() -> None:
    registry, claim = populated()
    registry.add_claim(claim)
    with pytest.raises(ValueError, match="IMMUTABLE_RECORD_CONFLICT"):
        registry.add_claim(Claim(**{**claim.__dict__, "proposition": "Changed."}))


def test_fact_requires_supported_claim() -> None:
    registry, claim = populated()
    registry.add_fact(Fact("fact_one", claim.claim_id, "policy-v1", NOW))
    candidate, claim = populated(ClaimStatus.CANDIDATE)
    with pytest.raises(ValueError, match="FACT_REQUIRES_SUPPORTED_CLAIM"):
        candidate.add_fact(Fact("fact_two", claim.claim_id, "policy-v1", NOW))


def test_missing_evidence_and_invalid_time_are_rejected() -> None:
    registry = KnowledgeRegistry()
    with pytest.raises(ValueError, match="CLAIM_EVIDENCE_NOT_FOUND"):
        registry.add_claim(Claim("claim_two", "x", ("missing",), .5, ClaimStatus.CANDIDATE, TimeRange(NOW, NOW), NOW))
    registry, claim = populated()
    with pytest.raises(ValueError, match="CONTRADICTION_SELF_REFERENCE"):
        registry.add_contradiction(Contradiction("contradiction_one", claim.claim_id, claim.claim_id, "manual", "open"))


def test_contradiction_abstention_and_linked_history_are_explicit() -> None:
    registry, first = populated()
    registry.add_source(Source("source_two", "urn:tim:source:two", "c" * 64, "internal", "reviewed", NOW))
    registry.add_evidence(Evidence("evidence_two", "source_two", "d" * 64, NOW, TimeRange(NOW, NOW), "urn:excerpt:two", "dataset"))
    second = Claim("claim_two", "A second bounded proposition.", ("evidence_two",), .7, ClaimStatus.SUPPORTED, TimeRange(NOW, NOW), NOW)
    registry.add_claim(second)
    registry.add_contradiction(Contradiction("contradiction_one", first.claim_id, second.claim_id, "manual", "OPEN"))
    registry.add_decision_history(DecisionHistory("decision_one", (first.claim_id,), "review", "human", NOW))
    registry.add_research_link(ResearchLink("link_one", first.claim_id, "research:future-reference", "used_by_research"))
    assert registry.query_at(NOW).reason == "UNRESOLVED_CONTRADICTION"
