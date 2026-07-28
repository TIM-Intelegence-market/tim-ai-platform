from datetime import datetime, timedelta, timezone

import pytest

from src.models.market_data import Observation, ObservationKind
from src.research.case_engine import ResearchCaseEngine


def observation(kind: ObservationKind, minute: int) -> Observation:
    return Observation(kind, "BTCUSDT", "1m", datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute), kind.value, 60, {"observed": True}, rule_id="test", rule_version="2.0.0", input_hash=str(minute))


def test_case_collects_evidence_versions_and_missing_items() -> None:
    engine = ResearchCaseEngine()
    case = engine.ingest(observation(ObservationKind.REJECTION, 1))
    assert case.rule_versions == {"test": "2.0.0"}
    assert "structure_confirmation" in case.missing_evidence
    assert "level_reaction_context" not in case.missing_evidence
    same = engine.ingest(observation(ObservationKind.BOS_BULLISH, 2))
    assert same.case_id == case.case_id
    assert "structure_confirmation" not in same.missing_evidence


def test_case_closure_rejects_retroactive_outcome() -> None:
    engine = ResearchCaseEngine()
    case = engine.ingest(observation(ObservationKind.REJECTION, 2))
    with pytest.raises(ValueError):
        engine.close(case.case_id, "documented", datetime(2026, 1, 1, tzinfo=timezone.utc))
