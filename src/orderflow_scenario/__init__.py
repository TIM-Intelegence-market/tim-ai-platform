"""Orderflow Scenario and Trade Decision Manager.

A deterministic, observation-only extension of TIM that interprets market
data and orderflow from the perspective of a professional orderflow trader.
It never emits direct long/short advice; it produces scenarios with evidence,
confirmation state machines, and - only for a confirmed scenario - a trade
plan that must pass an independent Risk Engine.

Operational boundary: this package runs exclusively in OBSERVE / RESEARCH /
SIMULATE / PAPER / SHADOW modes. It contains no broker or exchange routing,
no live-order execution, no API keys for order execution, and no background
process that can submit orders. The default mode is OBSERVE.
"""

from .config import OrderflowScenarioConfig, config_from_dict, default_config
from .domain import (
    AuctionStateKind,
    ConfirmationState,
    DecisionStatus,
    Direction,
    EntryModel,
    ExecutionSensitivity,
    Grade,
    MarketStateKind,
    Mode,
    OrderflowStatementKind,
    ProbabilityType,
    RiskStatus,
    ScenarioType,
    TradeStatus,
    VettingMode,
)
from .version import SCHEMA_VERSION

__all__ = [
    "AuctionStateKind",
    "ConfirmationState",
    "DecisionStatus",
    "Direction",
    "EntryModel",
    "ExecutionSensitivity",
    "Grade",
    "MarketStateKind",
    "Mode",
    "OrderflowStatementKind",
    "ProbabilityType",
    "RiskStatus",
    "ScenarioType",
    "TradeStatus",
    "VettingMode",
    "OrderflowScenarioConfig",
    "config_from_dict",
    "default_config",
    "SCHEMA_VERSION",
]
