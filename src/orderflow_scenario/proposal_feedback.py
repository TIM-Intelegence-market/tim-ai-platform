"""Reflective, non-executing review of setup proposals.

The module turns the later observation of a scenario into structured research
feedback. It deliberately never alters scenario rules, scores, capital, or
orders; rule changes require a separate, reviewed research decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .domain import DataQualityReport, Scenario


class ProposalReviewStatus(StrEnum):
    VALIDATED = "VALIDATED"
    INVALIDATED = "INVALIDATED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ErrorCategory(StrEnum):
    DATA_QUALITY = "DATA_QUALITY"
    CONTEXT = "CONTEXT"
    LOCATION = "LOCATION"
    STRUCTURE = "STRUCTURE"
    ORDERFLOW = "ORDERFLOW"
    CONFIRMATION = "CONFIRMATION"
    OUTCOME_WINDOW = "OUTCOME_WINDOW"


@dataclass(frozen=True, slots=True)
class ProposalOutcome:
    """Observed outcome only; no counterfactual or causal claim is inferred."""

    proposal_id: str
    evaluated_at: datetime
    trigger_observed: bool
    target_observed: bool
    invalidation_observed: bool
    outcome_window_complete: bool
    evidence_refs: tuple[str, ...]
    error_categories: tuple[ErrorCategory, ...] = ()

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must be timezone-aware")
        if self.target_observed and self.invalidation_observed:
            raise ValueError("ambiguous outcome: target and invalidation cannot both be observed")
        if not self.evidence_refs:
            raise ValueError("at least one outcome evidence reference is required")


@dataclass(frozen=True, slots=True)
class ProposalReview:
    proposal_id: str
    status: ProposalReviewStatus
    evidence_refs: tuple[str, ...]
    error_categories: tuple[ErrorCategory, ...]
    improvement_question: str
    automatic_rule_change: bool = False


class ProposalFeedbackEngine:
    """Produces auditable feedback without self-tuning or execution authority."""

    def review(
        self,
        scenario: Scenario,
        data_quality: DataQualityReport,
        outcome: ProposalOutcome,
    ) -> ProposalReview:
        if outcome.proposal_id != scenario.scenario_id:
            raise ValueError("outcome proposal_id must match scenario_id")

        if not outcome.outcome_window_complete:
            return ProposalReview(
                proposal_id=scenario.scenario_id,
                status=ProposalReviewStatus.INCONCLUSIVE,
                evidence_refs=outcome.evidence_refs,
                error_categories=(ErrorCategory.OUTCOME_WINDOW,),
                improvement_question="Was the observation window complete before judging this proposal?",
            )
        if outcome.invalidation_observed:
            categories = outcome.error_categories or self._default_error_categories(data_quality, scenario)
            return ProposalReview(
                proposal_id=scenario.scenario_id,
                status=ProposalReviewStatus.INVALIDATED,
                evidence_refs=outcome.evidence_refs,
                error_categories=categories,
                improvement_question="Which evidence gate or assumption failed, and can it be tested out of sample?",
            )
        if outcome.target_observed:
            return ProposalReview(
                proposal_id=scenario.scenario_id,
                status=ProposalReviewStatus.VALIDATED,
                evidence_refs=outcome.evidence_refs,
                error_categories=(),
                improvement_question="Does this result replicate across a separate out-of-sample period?",
            )
        return ProposalReview(
            proposal_id=scenario.scenario_id,
            status=ProposalReviewStatus.INCONCLUSIVE,
            evidence_refs=outcome.evidence_refs,
            error_categories=(ErrorCategory.OUTCOME_WINDOW,),
            improvement_question="Did neither target nor invalidation occur within the declared window?",
        )

    @staticmethod
    def _default_error_categories(data_quality: DataQualityReport, scenario: Scenario) -> tuple[ErrorCategory, ...]:
        if not data_quality.passed():
            return (ErrorCategory.DATA_QUALITY,)
        if scenario.evidence_against:
            return (ErrorCategory.CONFIRMATION,)
        return (ErrorCategory.CONTEXT,)
