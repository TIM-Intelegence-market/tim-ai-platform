"""TradePlanBuilder: plans built from generator scenarios serialize, and every market state has a stop."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.orderflow_scenario.domain import (
    ConfirmationState,
    Direction,
    EntryModel,
    MarketState,
    MarketStateKind,
    ProbabilityType,
    Scenario,
    ScenarioType,
)
from src.orderflow_scenario.engines.trade_plan import TradePlanBuilder, TradePlanInputs

NOW = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)


def scenario(direction: Direction, trade_template: dict) -> Scenario:
    return Scenario(
        scenario_id="s1",
        scenario_type=ScenarioType.BREAKOUT_ACCEPTANCE,
        direction=direction,
        hypothesis="breakout holds",
        trigger_level=Decimal("100"),
        entry_zone_low=Decimal("99"),
        entry_zone_high=Decimal("101"),
        evidence_for=("range_high_break",),
        evidence_against=(),
        mandatory_confirmations=(),
        optional_confirmations=(),
        invalidation=("close back inside range",),
        score=Decimal("0.5"),
        score_type=ProbabilityType.HEURISTIC_SCORE,
        state=ConfirmationState.CONFIRMED,
        # The scenario generator stores the entry model as its string value.
        trade_template=trade_template,
    )


def market(kind: MarketStateKind) -> MarketState:
    return MarketState(
        primary=kind,
        secondary=(),
        evidence=(),
        conflicts=(),
        confidence=Decimal("0.5"),
        missing_data=(),
        invalidation_conditions=(),
    )


def build(direction: Direction, kind: MarketStateKind, trade_template: dict | None = None, **extra):
    return TradePlanBuilder().build(
        TradePlanInputs(
            scenario=scenario(direction, {"entry_model": EntryModel.LIMIT_RETEST.value} if trade_template is None else trade_template),
            market_state=market(kind),
            symbol="BTCUSDT",
            venue="BINANCE",
            market_type="FUTURES",
            timeframe="4H",
            last_price=Decimal("100"),
            # Low enough that the builder returns a plan instead of rejecting it on reward/risk.
            minimum_reward_risk=Decimal("0.5"),
            timestamp=NOW,
            **extra,
        )
    )


@pytest.mark.parametrize("template", [{"entry_model": "LIMIT_RETEST"}, {}])
def test_plan_from_generator_template_serializes(template):
    plan = build(Direction.LONG, MarketStateKind.BALANCE, template)
    assert plan is not None
    expected = template.get("entry_model", "MARKET_AFTER_CONFIRMATION")
    assert plan.entry_model is EntryModel(expected)
    assert plan.to_dict()["entry_model"] == expected


def test_explicit_entry_model_wins_over_template():
    plan = build(Direction.LONG, MarketStateKind.BALANCE, entry_model=EntryModel.PULLBACK)
    assert plan.to_dict()["entry_model"] == "PULLBACK"


def test_unknown_entry_model_in_template_is_rejected():
    with pytest.raises(ValueError):
        build(Direction.LONG, MarketStateKind.BALANCE, {"entry_model": "RETEST"})


@pytest.mark.parametrize("kind", [MarketStateKind.BREAKOUT_ATTEMPT, MarketStateKind.TREND_UP])
def test_long_stop_in_breakout_and_trend_up_markets(kind):
    plan = build(Direction.LONG, kind)
    assert plan is not None
    # Structural stop just below the scenario's entry zone.
    assert plan.stop_loss == Decimal("99") * Decimal("0.995")
