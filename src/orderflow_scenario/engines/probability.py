"""Probability Engine.

Scores scenarios without fabricating statistical precision. Unless empirical
calibration exists, every score is labelled HEURISTIC_SCORE or
UNCALIBRATED_CONFIDENCE. A higher score never triggers a trade by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from ..domain import ProbabilityType, Scenario, ScenarioType
from ..domain import MarketState as MarketStateModel
from ..domain import AuctionState as AuctionStateModel
from ..domain import OrderflowInterpretation

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ProbabilityEngineInput:
    scenario: Scenario
    market_state: MarketStateModel
    auction_state: AuctionStateModel
    orderflow: OrderflowInterpretation
    data_quality_confidence: Decimal | None = None
    empirical_hit_rate: Decimal | None = None
    historical_similarity: Decimal | None = None
    regime: str | None = None


class ProbabilityEngine:
    """Rule-based weighting that never overclaims statistical validity."""

    def evaluate(self, inputs: Sequence[ProbabilityEngineInput]) -> tuple[Scenario, ...]:
        scored: list[Scenario] = []
        for item in inputs:
            raw = self._score(item)
            scored.append(_replace(item.scenario, raw, item))
        return tuple(scored)

    def _score(self, item: ProbabilityEngineInput) -> Decimal:
        if item.empirical_hit_rate is not None and item.historical_similarity is not None:
            # Empirical calibration present for this exact scenario type.
            score = item.empirical_hit_rate * Decimal("0.6") + item.historical_similarity * Decimal("0.4")
            return _bounded(score)

        # Heuristic weighting.
        score = Decimal("0.30")
        scenario = item.scenario
        ms = item.market_state
        of = item.orderflow

        if scenario.direction.value == "LONG":
            if ms.primary.value in {"TREND_UP", "BREAKOUT_ATTEMPT", "ACCEPTANCE_ABOVE_VALUE", "LIQUIDITY_SWEEP_LOW"}:
                score += Decimal("0.12")
            if of.aggressive_side == "BUYERS":
                score += Decimal("0.08")
            if of.aggressive_side == "SELLERS":
                score -= Decimal("0.06")
        elif scenario.direction.value == "SHORT":
            if ms.primary.value in {"TREND_DOWN", "BREAKDOWN_ATTEMPT", "ACCEPTANCE_BELOW_VALUE", "REJECTION_ABOVE_VALUE"}:
                score += Decimal("0.12")
            if of.aggressive_side == "SELLERS":
                score += Decimal("0.08")
            if of.aggressive_side == "BUYERS":
                score -= Decimal("0.06")

        if scenario.evidence_for:
            score += Decimal("0.04") * min(len(scenario.evidence_for), 3)
        if scenario.evidence_against:
            score -= Decimal("0.05") * min(len(scenario.evidence_against), 2)
        if of.absorption_confirmed:
            score += Decimal("0.06")
        if of.open_interest_interpretation and "accumulation" in of.open_interest_interpretation:
            score += Decimal("0.03")

        if item.data_quality_confidence is not None:
            score *= item.data_quality_confidence * Decimal("0.5") + Decimal("0.5")

        return _bounded(score)


def _bounded(value: Decimal) -> Decimal:
    return max(ZERO, min(Decimal("1"), value))


def _replace(scenario: Scenario, score: Decimal, item: ProbabilityEngineInput) -> Scenario:
    probability_type = ProbabilityType.UNCALIBRATED_CONFIDENCE
    if item.empirical_hit_rate is not None and item.historical_similarity is not None:
        probability_type = ProbabilityType.EMPIRICALLY_CALIBRATED
    elif item.historical_similarity is not None:
        probability_type = ProbabilityType.MODEL_BASED
    return Scenario(
        scenario_id=scenario.scenario_id,
        scenario_type=scenario.scenario_type,
        direction=scenario.direction,
        hypothesis=scenario.hypothesis,
        trigger_level=scenario.trigger_level,
        entry_zone_low=scenario.entry_zone_low,
        entry_zone_high=scenario.entry_zone_high,
        evidence_for=scenario.evidence_for,
        evidence_against=scenario.evidence_against,
        mandatory_confirmations=scenario.mandatory_confirmations,
        optional_confirmations=scenario.optional_confirmations,
        invalidation=scenario.invalidation,
        score=score,
        score_type=probability_type,
        state=scenario.state,
        confirmation=scenario.confirmation,
        trade_template=scenario.trade_template,
    )