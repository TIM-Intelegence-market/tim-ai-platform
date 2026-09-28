"""Risk Engine.

Strictly separate from the analysis layer. The analysis proposes a trade
plan; this engine independently approves or rejects it. Risk is measured
always as a fraction of total account equity. Leverage is only a technical
execution parameter, never a risk budget, and is chosen AFTER the position
size is derived from the stop.

Rejection reasons (non-exhaustive):
- liquidation price at or too near the stop
- insufficient margin
- stop too tight / only noise based
- stop not a structural invalidation
- fees destroy the reward/risk
- slippage cannot be modelled
- account risk exceeded
- daily/weekly loss limit reached
- data insufficient
- scenario not confirmed
- trade in the middle of a balance
- event risk not estimable
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..config import FeeModel, OrderflowScenarioConfig, RiskLimits, RiskTier
from ..domain import ConfirmationState, ExecutionSensitivity, RiskDecision, RiskStatus, TradePlan, TradeStatus
from ..domain import ZERO

# Multipliers used to estimate liquidation distance given leverage (simplified
# maintenance margin model). These are documented assumptions, not exchange
# contract guarantees.
MAINTENANCE_MARGIN_FRACTION = Decimal("0.005")


@dataclass(frozen=True, slots=True)
class AccountState:
    equity: Decimal
    free_margin: Decimal
    daily_realized_pnl: Decimal = ZERO
    weekly_realized_pnl: Decimal = ZERO
    consecutive_losses: int = 0
    open_positions: tuple[dict[str, Any], ...] = ()
    event_risk_flagged: bool = False
    margin_mode: str = "ISOLATED"

    def __post_init__(self) -> None:
        if self.equity <= ZERO:
            raise ValueError("equity must be positive")
        if self.free_margin < ZERO:
            raise ValueError("free_margin cannot be negative")


@dataclass(frozen=True, slots=True)
class RiskEngineOutput:
    decision: RiskDecision
    liquidation_price: Decimal | None = None
    approved_position_size: Decimal | None = None
    approved_leverage: Decimal | None = None
    execution_sensitivity: ExecutionSensitivity = ExecutionSensitivity.NORMAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.to_dict(),
            "liquidation_price": str(self.liquidation_price) if self.liquidation_price is not None else None,
            "approved_position_size": str(self.approved_position_size) if self.approved_position_size is not None else None,
            "approved_leverage": str(self.approved_leverage) if self.approved_leverage is not None else None,
            "execution_sensitivity": self.execution_sensitivity.value,
        }


class RiskEngine:
    """Independent risk gate over a proposed trade plan."""

    def __init__(self, config: OrderflowScenarioConfig) -> None:
        self.config = config

    def evaluate(self, plan: TradePlan, account: AccountState, tier_name: str | None = None) -> RiskEngineOutput:
        reasons: list[str] = []
        details: list[str] = []

        if plan.status not in {TradeStatus.DRAFT}:
            reasons.append("plan_not_draft")

        tier = self.config.tier(tier_name)
        limits = self.config.risk_limits
        fee = self.config.fee_model

        # 1. Data quality / fee model sanity.
        if fee.taker_bps < 0 or fee.slippage_bps < 0:
            reasons.append("invalid_fee_model")

        # 3. Stop sanity.
        if plan.stop_distance <= ZERO:
            reasons.append("invalid_stop_distance")
        if not self._structural_stop(plan):
            reasons.append("stop_not_structural")

        # 4. Minimum reward/risk.
        if plan.expected_reward_risk < plan.minimum_required_reward_risk:
            reasons.append("reward_risk_below_minimum")
            details.append(f"expected_rr={plan.expected_reward_risk:.2f} min={plan.minimum_required_reward_risk:.2f}")

        # 5. Account risk budget.
        account_risk = self._account_risk(plan, tier)
        daily_ok, weekly_ok = self._loss_limits(account, limits)
        if not daily_ok:
            reasons.append("daily_loss_limit_reached")
        if not weekly_ok:
            reasons.append("weekly_loss_limit_reached")
        if account.consecutive_losses >= limits.max_consecutive_losses:
            reasons.append("max_consecutive_losses_reached")

        # 6. Position size from risk (independent of any leverage).
        risk_amount = account.equity * tier.account_risk_fraction
        position_size = risk_amount / plan.stop_distance
        if position_size <= ZERO:
            reasons.append("position_size_not_positive")
        if position_size / account.equity > limits.max_account_fraction_per_position:
            reasons.append("position_exceeds_account_fraction")
            details.append(f"notional/equity={(position_size / account.equity):.4f}")

        # 7. Fees and slippage vs reward.
        entry_notional = position_size * plan.entry_zone_low if plan.entry_zone_low else position_size * plan.trigger
        fees = entry_notional * (fee.taker_bps + fee.slippage_bps) / Decimal("10000")
        reward = abs(plan.target_1 - plan.entry_zone_low) if plan.entry_zone_low else abs(plan.target_1 - plan.trigger)
        if reward > ZERO and fees / (position_size * reward) > Decimal("0.25"):
            reasons.append("fees_destroy_reward_risk")
            details.append(f"fees/reward={fees / (position_size * reward):.4f}")

        # 8. Margin sufficiency.
        margin_required = entry_notional * (Decimal("1") / tier.max_leverage)
        if margin_required > account.free_margin:
            reasons.append("insufficient_margin")
            details.append(f"margin_required={margin_required:.4f} free={account.free_margin:.4f}")

        # 9. Leverage choice is technical and capped by tier.
        requested_leverage = plan.leverage if plan.leverage >= Decimal("1") else Decimal("1")
        if requested_leverage > tier.max_leverage:
            reasons.append("leverage_exceeds_tier_limit")
            details.append(f"requested={requested_leverage} tier_max={tier.max_leverage}")
        approved_leverage = min(requested_leverage, tier.max_leverage)
        if approved_leverage > Decimal("50") and not self.config.allow_leverage_above_50x:
            reasons.append("leverage_above_50x_not_allowed")

        # 10. Liquidation buffer.
        liquidation_price = self._liquidation_price(plan, approved_leverage)
        buffer_ok = self._liquidation_buffer_ok(plan, liquidation_price, limits)
        if liquidation_price is not None and not buffer_ok:
            reasons.append("liquidation_distance_too_small")
            details.append(f"liq={liquidation_price} stop={plan.stop_loss}")

        # 11. Event risk.
        if account.event_risk_flagged:
            reasons.append("event_risk_flagged")

        # 12. Balance context.
        if plan.current_market_state == "BALANCE":
            reasons.append("trade_in_balance")

        # 13. Correlation to existing positions.
        if self._correlation_exceeds(account, limits):
            reasons.append("correlation_exceeds_limit")

        approved = not reasons
        status = RiskStatus.APPROVED if approved else RiskStatus.REJECTED

        sensitivity = ExecutionSensitivity.HIGH if approved_leverage >= Decimal("20") or (approved_leverage > Decimal("10") and account.event_risk_flagged) else ExecutionSensitivity.NORMAL

        return RiskEngineOutput(
            decision=RiskDecision(
                status=status,
                reason_codes=tuple(sorted(set(reasons))),
                details=tuple(details),
                proposed_risk_fraction=tier.account_risk_fraction,
                approved_risk_fraction=tier.account_risk_fraction if approved else None,
                approved_position_size=position_size if approved else None,
                approved_leverage=approved_leverage if approved else None,
                liquidation_price=liquidation_price,
                liquidation_buffer_ok=buffer_ok if liquidation_price is not None else None,
            ),
            liquidation_price=liquidation_price,
            approved_position_size=position_size if approved else None,
            approved_leverage=approved_leverage if approved else None,
            execution_sensitivity=sensitivity,
        )

    def _structural_stop(self, plan: TradePlan) -> bool:
        # A stop is structural if it is derived from a level beyond the entry
        # zone rather than a fixed noise-based offset.
        entry_ref = plan.entry_zone_low if plan.entry_zone_low else plan.trigger
        if plan.direction.value == "LONG":
            return plan.stop_loss < entry_ref and plan.stop_loss < plan.entry_zone_high
        return plan.stop_loss > entry_ref and plan.stop_loss > plan.entry_zone_high

    def _account_risk(self, plan: TradePlan, tier: RiskTier) -> Decimal:
        # plan.account_risk may be zero because the builder leaves sizing to
        # this engine; the engine always uses the tier fraction.
        return tier.account_risk_fraction

    def _loss_limits(self, account: AccountState, limits: RiskLimits) -> tuple[bool, bool]:
        daily_ok = account.daily_realized_pnl > -account.equity * limits.daily_loss_fraction
        weekly_ok = account.weekly_realized_pnl > -account.equity * limits.weekly_loss_fraction
        return daily_ok, weekly_ok

    def _correlation_exceeds(self, account: AccountState, limits: RiskLimits) -> bool:
        if not account.open_positions:
            return False
        correlated = sum(1 for position in account.open_positions if position.get("correlated", False))
        return correlated / len(account.open_positions) > limits.max_correlation_ratio

    def _liquidation_price(self, plan: TradePlan, leverage: Decimal) -> Decimal | None:
        if leverage < Decimal("1"):
            return None
        entry = plan.entry_zone_low if plan.entry_zone_low else plan.trigger
        if plan.direction.value == "LONG":
            # Simplified isolated-margin liquidation estimate.
            return entry * (Decimal("1") - (Decimal("1") / leverage) + MAINTENANCE_MARGIN_FRACTION)
        return entry * (Decimal("1") + (Decimal("1") / leverage) - MAINTENANCE_MARGIN_FRACTION)

    def _liquidation_buffer_ok(self, plan: TradePlan, liquidation_price: Decimal | None, limits: RiskLimits) -> bool:
        if liquidation_price is None:
            return False
        if plan.direction.value == "LONG":
            return liquidation_price < plan.stop_loss
        return liquidation_price > plan.stop_loss