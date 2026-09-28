"""Decision Engine.

Assembles the final decision: NO_TRADE (default) or a risk-approved trade plan.
NO_TRADE is a first-class, desired outcome. A trade plan is produced only when
a scenario is CONFIRMED, the trade plan builder succeeds, and the Risk Engine
approves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from ..config import OrderflowScenarioConfig
from ..domain import ConfirmationState, Decision, DecisionStatus, RiskStatus, Scenario, TradePlan, TradeStatus
from ..domain import DataQualityReport
from ..domain import OrderflowInterpretation
from ..domain import RiskDecision

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class DecisionEngineInput:
    data_quality: DataQualityReport
    scenarios: tuple[Scenario, ...]
    trade_plan: TradePlan | None
    risk: RiskDecision | None
    mode: str
    kill_switch_enabled: bool
    config: OrderflowScenarioConfig
    orderflow: OrderflowInterpretation | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"OBSERVE", "RESEARCH", "SIMULATE", "PAPER", "SHADOW"}:
            raise ValueError(f"mode {self.mode!r} is not an allowed operational mode")


class DecisionEngine:
    """Deterministic assembly of the final decision."""

    def decide(self, inputs: DecisionEngineInput) -> Decision:
        reason_codes: list[str] = []
        missing_confirmations: list[str] = []
        next_observation: list[str] = []

        if inputs.kill_switch_enabled is False:
            reason_codes.append("KILL_SWITCH_ACTIVE")
        if inputs.data_quality.status == "INSUFFICIENT_DATA":
            reason_codes.append("INSUFFICIENT_DATA")
        if inputs.data_quality.status == "PARTIAL" and inputs.data_quality.confidence < inputs.config.risk_limits.data_quality_min_confidence:
            reason_codes.append("DATA_QUALITY_TOO_LOW")

        confirmed = [s for s in inputs.scenarios if s.state == ConfirmationState.CONFIRMED]
        if not confirmed:
            reason_codes.append("NO_SCENARIO_CONFIRMED")
        for scenario in inputs.scenarios:
            if scenario.state in {ConfirmationState.PROPOSED, ConfirmationState.WATCHING, ConfirmationState.PARTIALLY_CONFIRMED}:
                if scenario.confirmation and scenario.confirmation.mandatory_pending:
                    missing_confirmations.extend(scenario.confirmation.mandatory_pending[:2])

        trade_plan = inputs.trade_plan
        risk = inputs.risk

        if reason_codes or trade_plan is None or risk is None or risk.status != RiskStatus.APPROVED:
            if trade_plan is not None and risk is not None and risk.status == RiskStatus.REJECTED:
                reason_codes.append("RISK_REJECTED")
            if trade_plan is None and confirmed:
                reason_codes.append("TRADE_PLAN_NOT_BUILDABLE")
            next_observation.append("monitor_price_reaction_at_defined_levels")
            next_observation.append("monitor_delta_and_open_interest_evolution")
            return Decision(
                status=DecisionStatus.NO_TRADE,
                reason_codes=tuple(sorted(set(reason_codes))),
                missing_confirmations=tuple(sorted(set(missing_confirmations))),
                next_observation=tuple(next_observation),
                trade_plan=None,
                risk=risk,
            )

        # Risk approved.
        vetting_mode = inputs.config.vetting_mode
        if vetting_mode.value == "PAPER":
            status = TradeStatus.PAPER_APPROVED
        elif vetting_mode.value == "SHADOW":
            status = TradeStatus.SHADOW_APPROVED
        else:
            status = TradeStatus.PAPER_APPROVED
        trade_plan = _with_status(trade_plan, status, risk, vetting_mode)
        return Decision(
            status=DecisionStatus.TRADE_PLAN,
            reason_codes=(),
            missing_confirmations=(),
            next_observation=("manage_active_trade_per_management_plan",),
            trade_plan=trade_plan,
            risk=risk,
        )


def _with_status(plan: TradePlan, status: TradeStatus, risk: RiskDecision, vetting_mode: Any = None) -> TradePlan:
    return TradePlan(
        trade_id=plan.trade_id,
        timestamp=plan.timestamp,
        symbol=plan.symbol,
        venue=plan.venue,
        market_type=plan.market_type,
        timeframe=plan.timeframe,
        scenario_id=plan.scenario_id,
        scenario_type=plan.scenario_type,
        direction=plan.direction,
        setup_name=plan.setup_name,
        current_market_state=plan.current_market_state,
        trigger=plan.trigger,
        entry_model=plan.entry_model,
        entry_zone_low=plan.entry_zone_low,
        entry_zone_high=plan.entry_zone_high,
        exact_entry=plan.exact_entry,
        invalidation_logic=plan.invalidation_logic,
        stop_loss=plan.stop_loss,
        stop_distance=plan.stop_distance,
        target_1=plan.target_1,
        target_2=plan.target_2,
        target_3=plan.target_3,
        target_logic=plan.target_logic,
        expected_reward_risk=plan.expected_reward_risk,
        minimum_required_reward_risk=plan.minimum_required_reward_risk,
        confidence=plan.confidence,
        probability_type=plan.probability_type,
        supporting_evidence=plan.supporting_evidence,
        conflicting_evidence=plan.conflicting_evidence,
        conditions_still_missing=plan.conditions_still_missing,
        expiration_condition=plan.expiration_condition,
        maximum_hold_time=plan.maximum_hold_time,
        management_plan=plan.management_plan,
        partial_take_profit_plan=plan.partial_take_profit_plan,
        break_even_rule=plan.break_even_rule,
        trailing_rule=plan.trailing_rule,
        cancellation_rule=plan.cancellation_rule,
        account_risk=risk.approved_risk_fraction or plan.account_risk,
        position_size=risk.approved_position_size or plan.position_size,
        leverage=risk.approved_leverage or plan.leverage,
        liquidation_distance=risk.liquidation_price,
        estimated_fees=plan.estimated_fees,
        estimated_slippage=plan.estimated_slippage,
        status=status,
        grade=plan.grade,
        grade_reasons=plan.grade_reasons,
        execution_sensitivity=plan.execution_sensitivity,
        audit_trace=plan.audit_trace,
        vetting_mode=vetting_mode or plan.vetting_mode,
    )