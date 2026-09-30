"""Trade Plan Builder.

Builds a structured, risk-aware trade plan ONLY from a CONFIRMED scenario.
The plan is a DRAFT until the Risk Engine decides. Position sizing and risk
are not decided here; this builder records the proposed structure, while the
Risk Engine approves or rejects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from src.orderflow_scenario.version import RULESET_VERSION

from ..domain import (
    ConfirmationState,
    Direction,
    EntryModel,
    ExecutionSensitivity,
    Grade,
    MarketStateKind,
    Scenario,
    ScenarioType,
    TradePlan,
    TradeStatus,
    utc_now,
)
from ..domain import MarketState as MarketStateModel

ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True, slots=True)
class TradePlanInputs:
    scenario: Scenario
    market_state: MarketStateModel
    symbol: str
    venue: str
    market_type: str
    timeframe: str
    last_price: Decimal
    entry_model: EntryModel | None = None
    exact_entry: Decimal | None = None
    risk_tier_name: str = "STANDARD"
    minimum_reward_risk: Decimal = Decimal("1.5")
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.last_price <= ZERO:
            raise ValueError("last_price must be positive")
        if self.exact_entry is not None and self.exact_entry <= ZERO:
            raise ValueError("exact_entry must be positive")


def _atr(candles: list[tuple[Decimal, Decimal]], period: int = 14) -> Decimal:
    if not candles:
        return Decimal("1")
    window = candles[-period:]
    if not window:
        window = candles
    ranges = [abs(high - low) for high, low in window]
    return sum(ranges, ZERO) / len(ranges)


class TradePlanBuilder:
    """Builds a DRAFT trade plan from a confirmed scenario and current levels."""

    def build(self, inputs: TradePlanInputs) -> TradePlan | None:
        scenario = inputs.scenario
        if scenario.state != ConfirmationState.CONFIRMED:
            return None

        direction = scenario.direction
        if direction == Direction.NEUTRAL:
            return None

        last = inputs.last_price
        trigger = scenario.trigger_level or last
        entry_low = scenario.entry_zone_low or trigger
        entry_high = scenario.entry_zone_high or last
        # The scenario generator stores the entry model as its string value; an unknown name raises.
        entry_model = inputs.entry_model or EntryModel(scenario.trade_template.get("entry_model", EntryModel.MARKET_AFTER_CONFIRMATION))
        exact_entry = inputs.exact_entry or entry_low

        # Stop derived from structural invalidation.
        if direction == Direction.LONG:
            stop = self._stop_long(scenario, inputs)
            targets = self._targets_long(last, entry_low, stop, inputs)
        else:
            stop = self._stop_short(scenario, inputs)
            targets = self._targets_short(last, entry_low, stop, inputs)

        stop_distance = abs(entry_low - stop)
        if stop_distance <= ZERO:
            return None

        expected_rr = self._reward_risk(targets, entry_low, stop, direction)
        minimum_rr = inputs.minimum_reward_risk
        if expected_rr < minimum_rr:
            return None

        grade, grade_reasons = self._grade(scenario, inputs, expected_rr)

        sensitivity = ExecutionSensitivity.NORMAL
        account_risk = Decimal("0")
        position_size = Decimal("0")
        leverage = Decimal("1")

        trade_id = "td_" + f"{inputs.symbol}_{scenario.scenario_id}_{utc_now().strftime('%Y%m%d%H%M%S%f')}".replace(":", "")[-40:].lower()
        plan = TradePlan(
            trade_id=trade_id,
            timestamp=inputs.timestamp or utc_now(),
            symbol=inputs.symbol,
            venue=inputs.venue,
            market_type=inputs.market_type,
            timeframe=inputs.timeframe,
            scenario_id=scenario.scenario_id,
            scenario_type=scenario.scenario_type,
            direction=direction,
            setup_name=scenario.hypothesis[:80],
            current_market_state=inputs.market_state.primary.value,
            trigger=trigger,
            entry_model=entry_model,
            entry_zone_low=entry_low,
            entry_zone_high=entry_high,
            exact_entry=exact_entry,
            invalidation_logic="; ".join(scenario.invalidation),
            stop_loss=stop,
            stop_distance=stop_distance,
            target_1=targets[0],
            target_2=targets[1],
            target_3=targets[2],
            target_logic=f"structure_based_multi_target({direction.value})",
            expected_reward_risk=expected_rr,
            minimum_required_reward_risk=minimum_rr,
            confidence=scenario.score,
            probability_type=scenario.score_type,
            supporting_evidence=scenario.evidence_for,
            conflicting_evidence=scenario.evidence_against,
            conditions_still_missing=(),
            expiration_condition="confirmation expires after maximum hold time or on invalidation",
            maximum_hold_time="defined_by_management_plan",
            management_plan="move stop to break-even after target 1 reached; structural trailing afterwards",
            partial_take_profit_plan="reduce one third at target 1 and one third at target 2",
            break_even_rule="break-even after target 1 closes",
            trailing_rule="trail below the most recent higher low (long) or lower high (short)",
            cancellation_rule="cancel if entry zone is never reached within max hold time or data becomes stale",
            account_risk=account_risk,
            position_size=position_size,
            leverage=leverage,
            liquidation_distance=None,
            estimated_fees=ZERO,
            estimated_slippage=ZERO,
            status=TradeStatus.DRAFT,
            grade=grade,
            grade_reasons=grade_reasons,
            execution_sensitivity=sensitivity,
            audit_trace={
                "ruleset_version": RULESET_VERSION,
                "scenario_id": scenario.scenario_id,
                "source": "DETERMINISTIC_RULES",
                "live_execution": False,
            },
        )
        return plan

    def _stop_long(self, scenario: Scenario, inputs: TradePlanInputs) -> Decimal:
        ms = inputs.market_state
        if ms.primary in {MarketStateKind.BREAKOUT_ATTEMPT, MarketStateKind.TREND_UP}:
            return (scenario.entry_zone_low or inputs.last_price) * Decimal("0.995")
        return (scenario.entry_zone_low or inputs.last_price) * Decimal("0.99")

    def _stop_short(self, scenario: Scenario, inputs: TradePlanInputs) -> Decimal:
        ms = inputs.market_state
        if ms.primary in {MarketStateKind.REJECTION_ABOVE_VALUE, MarketStateKind.TREND_DOWN}:
            return (scenario.entry_zone_high or inputs.last_price) * Decimal("1.005")
        return (scenario.entry_zone_high or inputs.last_price) * Decimal("1.01")

    def _targets_long(self, last: Decimal, entry: Decimal, stop: Decimal, inputs: TradePlanInputs) -> tuple[Decimal, Decimal, Decimal]:
        risk = entry - stop
        return (entry + risk * Decimal("1.0"), entry + risk * Decimal("2.0"), entry + risk * Decimal("3.0"))

    def _targets_short(self, last: Decimal, entry: Decimal, stop: Decimal, inputs: TradePlanInputs) -> tuple[Decimal, Decimal, Decimal]:
        risk = stop - entry
        return (entry - risk * Decimal("1.0"), entry - risk * Decimal("2.0"), entry - risk * Decimal("3.0"))

    def _reward_risk(self, targets: tuple[Decimal, Decimal, Decimal], entry: Decimal, stop: Decimal, direction: Direction) -> Decimal:
        if direction == Direction.LONG:
            reward = targets[0] - entry
            risk = entry - stop
        else:
            reward = entry - targets[0]
            risk = stop - entry
        return reward / risk if risk > ZERO else ZERO

    def _grade(self, scenario: Scenario, inputs: TradePlanInputs, expected_rr: Decimal) -> tuple[Grade, tuple[str, ...]]:
        reasons: list[str] = []
        score = 0
        if scenario.state == ConfirmationState.CONFIRMED:
            score += 2
            reasons.append("scenario_confirmed")
        if scenario.score >= Decimal("0.45"):
            score += 1
            reasons.append(f"score_{scenario.score:.2f}")
            if "external_weight" in scenario.trade_template:
                reasons.append(f"score_includes_broncx_weight_{scenario.trade_template['external_weight']}")
        if expected_rr >= Decimal("2.0"):
            score += 1
            reasons.append(f"rr_{expected_rr:.2f}")
        if not scenario.evidence_against:
            score += 1
            reasons.append("no_conflicting_evidence")
        else:
            reasons.append("conflicting_evidence_present")
        if score >= 4:
            return Grade.A, tuple(reasons)
        if score == 3:
            return Grade.B, tuple(reasons)
        if score == 2:
            return Grade.C, tuple(reasons)
        return Grade.C, tuple(reasons)