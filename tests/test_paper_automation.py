from datetime import datetime, timedelta, timezone

import pytest

from src.paper.automation import PaperAutomation, PaperPolicy
from src.research.case_engine import ResearchCase


def closed_case(at: datetime) -> ResearchCase:
    return ResearchCase("case_test", "BTCUSDT", "1m", at, at, status="CLOSED", outcome="documented")


def test_paper_is_disabled_by_default() -> None:
    engine = PaperAutomation(PaperPolicy("test"))
    with pytest.raises(PermissionError):
        engine.evaluate_case(closed_case(datetime.now(timezone.utc)), datetime.now(timezone.utc) + timedelta(hours=1), 100, 101)


def test_test_only_journal_costs_and_deduplication() -> None:
    at = datetime.now(timezone.utc)
    engine = PaperAutomation(PaperPolicy("test", enabled=True, test_only=True, evaluation_delay=timedelta(minutes=1), fee_bps=6, slippage_bps=2))
    evaluated = at + timedelta(minutes=2)
    first = engine.evaluate_case(closed_case(at), evaluated, 100, 101)
    second = engine.evaluate_case(closed_case(at), evaluated, 100, 101)
    assert first is second
    assert first.fee_fraction == 0.0012
    assert first.slippage_fraction == 0.0004
    assert first.provenance == "TEST_ONLY_PAPER_RESEARCH"


def test_non_test_policy_is_impossible() -> None:
    with pytest.raises(ValueError, match="TEST_ONLY"):
        PaperPolicy("unsafe", test_only=False)
