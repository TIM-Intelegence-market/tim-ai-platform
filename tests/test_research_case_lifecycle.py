from datetime import datetime, timedelta, timezone

import pytest

from src.models.market_data import Observation, ObservationKind
from src.research.case_engine import MISSING_REASONS, ResearchCaseEngine


def observation(kind: ObservationKind, minute: int) -> Observation:
    return Observation(kind, "BTCUSDT", "1m", datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute), kind.value, 60, {"observed": True}, rule_id="test", rule_version="2.0.0", input_hash=str(minute))


def test_missing_reasons_vocabulary_complete() -> None:
    assert len(MISSING_REASONS) == 8
    assert "Manual Review pending" in MISSING_REASONS


def test_forward_lifecycle_open_to_review() -> None:
    engine = ResearchCaseEngine()
    case = engine.ingest(observation(ObservationKind.REJECTION, 1))
    at = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    engine.transition(case.case_id, "COLLECTING_EVIDENCE", at, "evidence growing")
    engine.transition(case.case_id, "READY_FOR_REVIEW", at + timedelta(minutes=5), "evidence complete")
    assert engine.cases[case.case_id].status == "READY_FOR_REVIEW"
    assert len(engine.cases[case.case_id].review_history) == 2


def test_backward_transition_rejected() -> None:
    engine = ResearchCaseEngine()
    case = engine.ingest(observation(ObservationKind.REJECTION, 1))
    at = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    engine.transition(case.case_id, "COLLECTING_EVIDENCE", at, "x")
    with pytest.raises(ValueError):
        engine.transition(case.case_id, "OPEN", at + timedelta(minutes=1), "retrograde")
    with pytest.raises(ValueError):
        engine.transition(case.case_id, "READY_FOR_REVIEW", at - timedelta(minutes=1), "time travel")


def test_confirm_requires_full_criteria() -> None:
    engine = ResearchCaseEngine()
    case = engine.ingest(observation(ObservationKind.REJECTION, 1))
    at = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        engine.confirm(case.case_id, at, "reviewer")
    engine.transition(case.case_id, "COLLECTING_EVIDENCE", at, "x")
    engine.transition(case.case_id, "READY_FOR_REVIEW", at + timedelta(minutes=1), "x")
    with pytest.raises(ValueError):
        engine.confirm(case.case_id, at + timedelta(minutes=2), "reviewer")


def test_quarantine_never_deletes() -> None:
    engine = ResearchCaseEngine()
    case = engine.ingest(observation(ObservationKind.REJECTION, 1))
    at = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    engine.quarantine(case.case_id, at, "defective input hash")
    assert engine.cases[case.case_id].status == "QUARANTINED"
    with pytest.raises(ValueError):
        engine.transition(case.case_id, "OPEN", at + timedelta(minutes=1), "reopen")


def test_review_history_persists_in_dict() -> None:
    engine = ResearchCaseEngine()
    case = engine.ingest(observation(ObservationKind.REJECTION, 1))
    at = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    engine.transition(case.case_id, "COLLECTING_EVIDENCE", at, "r")
    assert engine.cases[case.case_id].to_dict()["review_history"][0]["to"] == "COLLECTING_EVIDENCE"
