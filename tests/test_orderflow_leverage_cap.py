"""Hebel-Obergrenze: Spot (1x) erlaubt, höchstens 10x, nichts kann darüber gehen."""

import dataclasses
from decimal import Decimal

import pytest

from src.orderflow_scenario.config import MAX_LEVERAGE, RiskTier, config_from_dict, default_config
from src.orderflow_scenario.domain import Direction, MarketStateKind
from src.orderflow_scenario.engines.risk import AccountState, RiskEngine

from tests.test_orderflow_trade_plan_builder import build


def plan_with_leverage(leverage: str):
    plan = build(Direction.LONG, MarketStateKind.TREND_UP)
    assert plan is not None
    return dataclasses.replace(plan, leverage=Decimal(leverage))


def account():
    return AccountState(equity=Decimal("100000"), free_margin=Decimal("100000"))


def test_hard_cap_is_ten():
    assert MAX_LEVERAGE == Decimal("10")


def test_default_tiers_never_exceed_cap():
    assert all(tier.max_leverage <= MAX_LEVERAGE for tier in default_config().risk_tiers)


def test_tier_above_cap_is_rejected():
    with pytest.raises(ValueError, match="hard cap"):
        RiskTier("WILD", Decimal("0.005"), Decimal("11"), Decimal("1.5"))


def test_config_file_cannot_raise_cap():
    raw = default_config().to_dict()
    raw["risk_tiers"][1]["max_leverage"] = "20"
    with pytest.raises(ValueError, match="hard cap"):
        config_from_dict(raw)


@pytest.mark.parametrize("tier", ["CONSERVATIVE", "STANDARD", "AGGRESSIVE"])
def test_risk_engine_rejects_above_ten(tier):
    out = RiskEngine(default_config()).evaluate(plan_with_leverage("20"), account(), tier)
    assert out.approved_leverage is None
    assert any(code.startswith("leverage_exceeds") for code in out.decision.reason_codes)


@pytest.mark.parametrize("leverage", ["1", "10"])
def test_spot_and_ten_x_do_not_trip_leverage_codes(leverage):
    out = RiskEngine(default_config()).evaluate(plan_with_leverage(leverage), account(), "STANDARD")
    assert not any("leverage" in code for code in out.decision.reason_codes)
    if out.approved_leverage is not None:
        assert out.approved_leverage <= MAX_LEVERAGE
