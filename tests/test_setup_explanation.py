from decimal import Decimal

from src.orderflow_scenario.domain import DataQualityReport, MarketState, MarketStateKind, OrderflowInterpretation
from src.orderflow_scenario.engines.scenario_generator import LevelSet
from src.orderflow_scenario.explanation import build_setup_explanation


def test_setup_explanation_separates_fib_levels_from_absorption_proof() -> None:
    result = build_setup_explanation(
        LevelSet(range_low=Decimal("80"), range_high=Decimal("100"), value_area_high=Decimal("96")),
        MarketState(MarketStateKind.BALANCE, (), ("balanced_structure",), (), Decimal("0.7"), (), ()),
        OrderflowInterpretation("BUYERS", "DOWN", "PASSIVE_SELLERS", False, None, (), Decimal("0.6"), ("net_delta",)),
        DataQualityReport("PASS", Decimal("0.9"), (), (), ()),
        (),
    )
    assert result["facts"]["fibonacci_retracements"]["0.618"] == "87.64"
    assert result["facts"]["absorption_status"] == "HYPOTHESIS_PASSIVE_SELLERS"
    assert "net_delta" in result["missing_evidence"]
