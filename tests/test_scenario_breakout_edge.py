"""A breakout retest is only proposed near or above the breakout edge (25.10.2026)."""

from decimal import Decimal
from types import SimpleNamespace

from src.orderflow_scenario.domain import MarketStateKind, ScenarioType
from src.orderflow_scenario.engines.scenario_generator import LevelSet, ScenarioGenerator

FLOW = SimpleNamespace(aggressive_side="BUYERS", absorption_hypothesis=None, exhaustion_hypothesis=None, footprint={}, open_interest_interpretation=None)


def _types(primary: MarketStateKind, last: str, high: str = "82060.88", low: str = "79220.74") -> set:
    levels = LevelSet(range_high=Decimal(high), range_low=Decimal(low), last_price=Decimal(last))
    scenarios = ScenarioGenerator().generate(SimpleNamespace(primary=primary), SimpleNamespace(), FLOW, levels)
    return {s.scenario_type for s in scenarios}


def test_trend_up_far_below_the_range_high_proposes_no_breakout_retest() -> None:
    # 30m on 25.10.: TREND_UP, range high 82.060,88, BTC at 80.810 (1,5 % below).
    assert ScenarioType.BREAKOUT_ACCEPTANCE not in _types(MarketStateKind.TREND_UP, "80810")
    # 1W: range high 126.199,63, BTC at 82.116.
    assert ScenarioType.BREAKOUT_ACCEPTANCE not in _types(MarketStateKind.TREND_UP, "82116", high="126199.63", low="49000")


def test_breakout_retest_stays_near_and_above_the_edge() -> None:
    assert ScenarioType.BREAKOUT_ACCEPTANCE in _types(MarketStateKind.TREND_UP, "81500")  # 0,7 % below
    assert ScenarioType.BREAKOUT_ACCEPTANCE in _types(MarketStateKind.TREND_UP, "82500")  # above: retest from above
    assert ScenarioType.BREAKOUT_ACCEPTANCE in _types(MarketStateKind.BREAKOUT_ATTEMPT, "82070")


def test_reclaim_far_below_the_range_low_proposes_no_sweep_reversal() -> None:
    assert ScenarioType.LIQUIDITY_SWEEP_REVERSAL in _types(MarketStateKind.LIQUIDITY_SWEEP_LOW, "79000")  # 0,3 % below
    assert ScenarioType.LIQUIDITY_SWEEP_REVERSAL not in _types(MarketStateKind.LIQUIDITY_SWEEP_LOW, "77000")  # 2,8 % below
