"""The heuristic setup grade: versioned, graded on the real scenario state, never A+."""
from __future__ import annotations

import itertools
from dataclasses import replace
from decimal import Decimal

import pytest

from src.orderflow_scenario.domain import ConfirmationState, Direction, Grade, ProbabilityType, Scenario, ScenarioType
from src.orderflow_scenario.engines.trade_plan import GRADE_RULESET_VERSION, TradePlanBuilder, grade_scenario
from tests.test_orderflow_trade_plan_builder import build


def _scenario(state: ConfirmationState, score: str = "0.5", against: tuple[str, ...] = ()) -> Scenario:
    return Scenario(
        scenario_id="B", scenario_type=ScenarioType.LIQUIDITY_SWEEP_REVERSAL, direction=Direction.LONG, hypothesis="sweep reclaims",
        trigger_level=Decimal("100"), entry_zone_low=Decimal("99"), entry_zone_high=Decimal("101"),
        evidence_for=("sweep",), evidence_against=against, mandatory_confirmations=(), optional_confirmations=(),
        invalidation=("close below low",), score=Decimal(score), score_type=ProbabilityType.HEURISTIC_SCORE, state=state,
        trade_template={"entry_model": "RECLAIM"},
    )


def test_ruleset_version_is_fixed_and_named() -> None:
    assert GRADE_RULESET_VERSION == "grade/1.0.0"


def test_forced_confirmation_would_add_two_points() -> None:
    watching = _scenario(ConfirmationState.WATCHING)
    grade, reasons = grade_scenario(watching, Decimal("2"))
    forced, forced_reasons = grade_scenario(replace(watching, state=ConfirmationState.CONFIRMED), Decimal("2"))
    assert (grade, forced) == (Grade.B, Grade.A)
    assert "scenario_watching" in reasons and "scenario_confirmed" not in reasons
    assert "scenario_confirmed" in forced_reasons


def test_conflicting_evidence_costs_one_point_and_is_named() -> None:
    # Rule grade/1.0.0 as it is: a confirmed scenario with score and reward/risk still reaches A
    # with conflicting evidence (4 of 5 points). The reason is recorded so reviewers can see it.
    grade, reasons = grade_scenario(_scenario(ConfirmationState.CONFIRMED, against=("delta_divergence",)), Decimal("2"))
    assert grade is Grade.A and "conflicting_evidence_present" in reasons and "no_conflicting_evidence" not in reasons
    grade, _ = grade_scenario(_scenario(ConfirmationState.CONFIRMED, score="0.4", against=("delta_divergence",)), Decimal("2"))
    assert grade is Grade.B


@pytest.mark.parametrize("state, score, rr, against, expected", [
    (ConfirmationState.CONFIRMED, "0.5", "2", (), Grade.A),       # 2+1+1+1 = 5
    (ConfirmationState.CONFIRMED, "0.4", "2", (), Grade.A),       # 2+0+1+1 = 4
    (ConfirmationState.CONFIRMED, "0.4", "1.5", (), Grade.B),     # 2+0+0+1 = 3
    (ConfirmationState.WATCHING, "0.5", "2", (), Grade.B),        # 0+1+1+1 = 3
    (ConfirmationState.WATCHING, "0.5", "1.5", (), Grade.C),      # 2
    (ConfirmationState.PROPOSED, "0.1", "1.5", ("x",), Grade.C),  # 0
])
def test_grade_table(state, score, rr, against, expected) -> None:
    assert grade_scenario(_scenario(state, score, against), Decimal(rr))[0] is expected


def test_a_plus_is_never_awarded() -> None:
    states = list(ConfirmationState)
    scores = ("0", "0.44", "0.45", "1")
    rrs = (Decimal("0"), Decimal("1.99"), Decimal("2"), Decimal("10"))
    againsts = ((), ("a",))
    for state, score, rr, against in itertools.product(states, scores, rrs, againsts):
        assert grade_scenario(_scenario(state, score, against), rr)[0] is not Grade.A_PLUS


def test_builder_uses_the_same_rules() -> None:
    from src.orderflow_scenario.domain import MarketStateKind

    plan = build(Direction.LONG, MarketStateKind.BALANCE)
    assert plan is not None
    scenario = _scenario(ConfirmationState.CONFIRMED)
    # The builder grades the confirmed scenario it was given; same inputs, same answer.
    grade, reasons = grade_scenario(replace(scenario, scenario_type=plan.scenario_type, score=plan.confidence, evidence_against=plan.conflicting_evidence,
                                            trade_template={"entry_model": "LIMIT_RETEST"}), plan.expected_reward_risk)
    assert (plan.grade, plan.grade_reasons) == (grade, reasons)
    assert TradePlanBuilder()._grade(scenario, None, Decimal("2")) == grade_scenario(scenario, Decimal("2"))
