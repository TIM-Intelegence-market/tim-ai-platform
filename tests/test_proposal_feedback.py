from datetime import datetime, timezone
from decimal import Decimal

from src.orderflow_scenario.domain import (
    ConfirmationState,
    DataQualityReport,
    Direction,
    ProbabilityType,
    Scenario,
    ScenarioType,
)
from src.orderflow_scenario.proposal_feedback import (
    ErrorCategory,
    ProposalFeedbackEngine,
    ProposalOutcome,
    ProposalReviewStatus,
)


def scenario() -> Scenario:
    return Scenario(
        scenario_id="proposal-1",
        scenario_type=ScenarioType.FAILED_AUCTION,
        direction=Direction.SHORT,
        hypothesis="Rejection remains conditional on confirmation.",
        trigger_level=Decimal("100"),
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        evidence_for=("rejection at value edge",),
        evidence_against=("CVD unavailable",),
        mandatory_confirmations=("close back inside value",),
        optional_confirmations=(),
        invalidation=("acceptance above value",),
        score=Decimal("0.5"),
        score_type=ProbabilityType.UNCALIBRATED_CONFIDENCE,
        state=ConfirmationState.PROPOSED,
    )


def quality() -> DataQualityReport:
    return DataQualityReport("PASS", Decimal("0.9"), (), (), ())


def test_invalidated_proposal_becomes_error_review_without_rule_change() -> None:
    outcome = ProposalOutcome(
        "proposal-1", datetime.now(timezone.utc), True, False, True, True,
        ("observation: acceptance above value",), (ErrorCategory.ORDERFLOW,),
    )
    review = ProposalFeedbackEngine().review(scenario(), quality(), outcome)
    assert review.status == ProposalReviewStatus.INVALIDATED
    assert review.error_categories == (ErrorCategory.ORDERFLOW,)
    assert review.automatic_rule_change is False


def test_incomplete_window_is_inconclusive_not_a_failed_setup() -> None:
    outcome = ProposalOutcome(
        "proposal-1", datetime.now(timezone.utc), True, False, False, False,
        ("observation window still open",),
    )
    review = ProposalFeedbackEngine().review(scenario(), quality(), outcome)
    assert review.status == ProposalReviewStatus.INCONCLUSIVE
    assert review.error_categories == (ErrorCategory.OUTCOME_WINDOW,)
