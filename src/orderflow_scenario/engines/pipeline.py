"""Pipeline orchestrator for the Orderflow Scenario and Trade Decision Manager.

Composes the deterministic engines into the full pipeline:

MARKET DATA -> DATA QUALITY -> MARKET STATE -> AUCTION STATE ->
ORDERFLOW INTERPRETATION -> SCENARIO GENERATOR -> PROBABILITY ->
CONFIRMATION -> TRADE PLAN BUILDER -> RISK ENGINE -> DECISION -> REPORT.

Every path ends in a machine-readable AnalysisOutput. The pipeline contains
no network, persistence, or order path. When data quality is insufficient the
pipeline short-circuits to NO_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from src.knowledge.broncx_feed import BroncxPost
from src.knowledge.goathub_feed import GoatHubMessage
from src.models.market_data import Candle, Trade

from ..audit import AuditBuilder, analysis_id_for
from ..explanation import build_setup_explanation
from ..community_calls import DEFAULT_CALL_MAX_AGE, build_community_calls
from ..external_context import DEFAULT_MAX_AGE, active_view, apply_external_weight, build_external_context
from ..config import OrderflowScenarioConfig, default_config
from ..domain import (
    AnalysisOutput,
    AuctionStateKind,
    ConfirmationState,
    Decision,
    DecisionStatus,
    MarketContext,
    MarketStateKind,
    Mode,
    Scenario,
    utc_now,
)
from ..domain import MarketState as MarketStateModel
from ..domain import AuctionState as AuctionStateModel
from ..domain import OrderflowInterpretation
from ..positioning import PositioningInputs, ProfileLevels
from .confirmation import ConfirmationEngine, ConfirmationUpdate
from .data_quality import DataQualityGate, DataQualityInputs
from .decision import DecisionEngine, DecisionEngineInput
from .market_state import AuctionStateEngine, MarketStateEngine
from .orderflow_interpretation import OrderflowInputs, OrderflowInterpretationEngine
from .probability import ProbabilityEngine, ProbabilityEngineInput
from .risk import AccountState, RiskEngine
from .scenario_generator import LevelSet, ScenarioGenerator
from .trade_plan import TradePlanBuilder, TradePlanInputs
from ..report import build_report


@dataclass(frozen=True, slots=True)
class PipelineInputs:
    market_context: MarketContext
    candles: Sequence[Candle]
    trades: Sequence[Trade] | None = None
    price_now: Decimal | None = None
    price_timestamp: datetime | None = None
    net_delta: Decimal | None = None
    aggressive_buy_volume: Decimal | None = None
    aggressive_sell_volume: Decimal | None = None
    total_volume: Decimal | None = None
    open_interest_trend: str | None = None
    open_interest_with_price: str | None = None
    delta_divergence: bool | None = None
    volume_bubbles: tuple[str, ...] = ()
    levels: LevelSet | None = None
    # Funding, liquidations, OI series, orderbook depth; volume profile / TPO (positioning.py).
    positioning: PositioningInputs | None = None
    profile: ProfileLevels | None = None
    screenshot_confidence: float | None = None
    structured: bool = True
    estimated_prices: tuple[str, ...] = ()
    venue_mixed: bool = False
    delta_definition_verified: bool = True
    time_unit_verified: bool = True
    spot_futures_separated: bool = True
    open_interest_venue_aggregated: bool = False
    data_latency_seconds: float | None = None
    source_name: str = "UNKNOWN"
    confirmation_updates: tuple[ConfirmationUpdate, ...] = ()
    account: AccountState | None = None
    requested_leverage: Decimal = Decimal("1")
    risk_tier_name: str = "STANDARD"
    kill_switch_enabled: bool = True
    observed_at: datetime | None = None
    # External guidance (Broncx via Discord): audit and report only, never evidence.
    external_posts: tuple[BroncxPost, ...] = ()
    external_max_age: timedelta = DEFAULT_MAX_AGE
    # GoatHub community calls: audit and report only, no score weight, never evidence.
    community_messages: tuple[GoatHubMessage, ...] = ()
    community_max_age: timedelta = DEFAULT_CALL_MAX_AGE

    def __post_init__(self) -> None:
        if self.requested_leverage < Decimal("1"):
            raise ValueError("requested_leverage must be >= 1")


class Pipeline:
    def __init__(self, config: OrderflowScenarioConfig | None = None) -> None:
        self.config = config or default_config()
        self.data_quality_gate = DataQualityGate()
        self.market_state_engine = MarketStateEngine()
        self.auction_state_engine = AuctionStateEngine()
        self.orderflow_engine = OrderflowInterpretationEngine()
        self.scenario_generator = ScenarioGenerator()
        self.probability_engine = ProbabilityEngine()
        self.confirmation_engine = ConfirmationEngine()
        self.trade_plan_builder = TradePlanBuilder()
        self.risk_engine = RiskEngine(self.config)
        self.decision_engine = DecisionEngine()

    def run(self, inputs: PipelineInputs) -> AnalysisOutput:
        observed_at = inputs.observed_at or utc_now()
        audit = AuditBuilder()
        audit.add_input("candles", [{"symbol": c.symbol, "timeframe": c.timeframe, "open_time": c.open_time.isoformat(), "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume, "closed": c.closed} for c in inputs.candles])
        if inputs.trades:
            audit.add_input("trades", [{"symbol": t.symbol, "trade_id": t.trade_id, "event_time": t.event_time.isoformat(), "price": t.price, "quantity": t.quantity, "buyer_is_maker": t.buyer_is_maker} for t in inputs.trades])

        # 1. Data Quality Gate.
        quality_inputs = DataQualityInputs(
            candles=inputs.candles,
            trades=inputs.trades,
            price_now=float(inputs.price_now) if inputs.price_now is not None else None,
            price_timestamp=inputs.price_timestamp,
            structured=inputs.structured,
            screenshot_confidence=inputs.screenshot_confidence,
            estimated_prices=inputs.estimated_prices,
            venue_mixed=inputs.venue_mixed,
            delta_definition_verified=inputs.delta_definition_verified,
            time_unit_verified=inputs.time_unit_verified,
            spot_futures_separated=inputs.spot_futures_separated,
            open_interest_venue_aggregated=inputs.open_interest_venue_aggregated,
            data_latency_seconds=inputs.data_latency_seconds,
            source_name=inputs.source_name,
        )
        quality = self.data_quality_gate.evaluate(quality_inputs, observed_at=observed_at)

        # Broncx's current view (external guidance): weights scenarios and adds his levels, never confirms.
        external_view = None
        external_adjustments: list[dict] = []
        if inputs.external_posts:
            external_view = active_view(
                inputs.external_posts,
                observed_at=observed_at,
                symbol=inputs.market_context.symbol,
                candles=inputs.candles,
                price_now=inputs.price_now,
                max_age=inputs.external_max_age,
            )

        # 2. Market State and Auction State.
        if quality.status == "INSUFFICIENT_DATA":
            market_state = MarketStateModel(
                primary=MarketStateKind.UNCERTAIN,
                secondary=(),
                evidence=("data_quality_insufficient",),
                conflicts=(),
                confidence=Decimal("0.1"),
                missing_data=tuple(quality.missing_fields),
                invalidation_conditions=(),
            )
            auction_state = AuctionStateModel(
                primary=AuctionStateKind.BALANCE, secondary=(), evidence=("data_quality_insufficient",), confidence=Decimal("0.1")
            )
            orderflow = OrderflowInterpretation(
                aggressive_side="UNKNOWN",
                price_response="UNKNOWN",
                absorption_hypothesis=None,
                absorption_confirmed=False,
                open_interest_interpretation=None,
                statements=(),
                confidence=Decimal("0.1"),
                missing_data=tuple(quality.missing_fields),
            )
            scenarios: tuple[Scenario, ...] = ()
        else:
            market_state = self.market_state_engine.evaluate(inputs.candles)
            auction_state = self.auction_state_engine.evaluate(inputs.candles, market_state)
            orderflow = self.orderflow_engine.evaluate(
                OrderflowInputs(
                    trades=inputs.trades,
                    candles=inputs.candles,
                    net_delta=inputs.net_delta,
                    aggressive_buy_volume=inputs.aggressive_buy_volume,
                    aggressive_sell_volume=inputs.aggressive_sell_volume,
                    total_volume=inputs.total_volume,
                    open_interest_trend=inputs.open_interest_trend,
                    open_interest_with_price=inputs.open_interest_with_price,
                    delta_divergence=inputs.delta_divergence,
                    volume_bubbles=inputs.volume_bubbles,
                    positioning=inputs.positioning,
                    profile=inputs.profile,
                )
            )
            levels = _with_profile(inputs.levels or self._levels_from_candles(inputs.candles, inputs.price_now), inputs.profile)
            if external_view is not None and external_view.bias is not None:
                levels = replace(levels, external_levels=external_view.levels, external_bias=external_view.bias)
            scenarios = self.scenario_generator.generate(market_state, auction_state, orderflow, levels)
            scenario_inputs = [
                ProbabilityEngineInput(
                    scenario=scenario,
                    market_state=market_state,
                    auction_state=auction_state,
                    orderflow=orderflow,
                    data_quality_confidence=quality.confidence,
                )
                for scenario in scenarios
            ]
            scenarios = self.probability_engine.evaluate(scenario_inputs)
            if external_view is not None:
                scenarios, external_adjustments = apply_external_weight(scenarios, external_view)

            # Confirmation updates.
            updates_by_id = {update.scenario_id: update for update in inputs.confirmation_updates}
            scenarios = tuple(
                self.confirmation_engine.apply(scenario, updates_by_id[scenario.scenario_id])
                if scenario.scenario_id in updates_by_id
                else scenario
                for scenario in scenarios
            )

        # 3. Trade plan builder (only for CONFIRMED scenarios).
        trade_plan = None
        risk_decision = None
        if scenarios:
            confirmed = [s for s in scenarios if s.state == ConfirmationState.CONFIRMED]
            if confirmed and quality.passed():
                best = confirmed[0]
                last_price = inputs.price_now or (Decimal(inputs.candles[-1].close) if inputs.candles else None)
                if last_price is not None:
                    plan_inputs = TradePlanInputs(
                        scenario=best,
                        market_state=market_state,
                        symbol=inputs.market_context.symbol,
                        venue=inputs.market_context.venue,
                        market_type=inputs.market_context.market_type,
                        timeframe=inputs.market_context.timeframe,
                        last_price=last_price,
                        risk_tier_name=inputs.risk_tier_name,
                        minimum_reward_risk=self.config.tier(inputs.risk_tier_name).min_reward_risk,
                        timestamp=observed_at,
                    )
                    trade_plan = self.trade_plan_builder.build(plan_inputs)
                    if trade_plan is not None:
                        trade_plan = _mark_confirmed(trade_plan, best)
                        account = inputs.account or AccountState(equity=Decimal("10000"), free_margin=Decimal("10000"))
                        risk_output = self.risk_engine.evaluate(trade_plan, account, inputs.risk_tier_name)
                        risk_decision = risk_output.decision
                        if risk_output.approved_leverage is not None and inputs.requested_leverage > Decimal("1"):
                            trade_plan = _with_leverage(trade_plan, inputs.requested_leverage)
                        trade_plan = _with_risk_status(trade_plan, risk_decision)

        # 4. Decision.
        decision = self.decision_engine.decide(
            DecisionEngineInput(
                data_quality=quality,
                scenarios=scenarios,
                trade_plan=trade_plan,
                risk=risk_decision,
                mode=self.config.mode.value,
                kill_switch_enabled=self.config.kill_switch_enabled and inputs.kill_switch_enabled,
                config=self.config,
                orderflow=orderflow,
            )
        )
        if decision.status == DecisionStatus.NO_TRADE:
            trade_plan = None

        # 5. Audit + report.
        audit.add_engine("market_state", "1.0.0", market_state.to_dict())
        audit.add_engine("orderflow", "1.0.0", orderflow.to_dict())
        audit.add_engine("scenarios", "1.0.0", [s.to_dict() for s in scenarios])
        audit.add_engine(
            "setup_explanation", "1.0.0",
            build_setup_explanation(levels if quality.status != "INSUFFICIENT_DATA" else self._levels_from_candles(inputs.candles, inputs.price_now), market_state, orderflow, quality, scenarios),
        )
        if inputs.external_posts:
            audit.add_input("external_posts", [post.to_dict() for post in inputs.external_posts])
            audit.add_engine(
                "external_context", "1.0.0",
                build_external_context(
                    inputs.external_posts,
                    observed_at=observed_at,
                    symbol=inputs.market_context.symbol,
                    candles=inputs.candles,
                    price_now=inputs.price_now,
                    scenarios=scenarios,
                    max_age=inputs.external_max_age,
                    influence={
                        "view": external_view.to_dict(),
                        "score_adjustments": external_adjustments,
                        "level_scenarios": [item.scenario_id for item in scenarios if item.trade_template.get("level_source") == "broncx"],
                    },
                ),
            )
        if inputs.community_messages:
            audit.add_engine(
                "community_calls", "1.0.0",
                build_community_calls(
                    inputs.community_messages,
                    observed_at=observed_at,
                    symbol=inputs.market_context.symbol,
                    candles=inputs.candles,
                    price_now=inputs.price_now,
                    max_age=inputs.community_max_age,
                ),
            )
        audit_payload = audit.build(mode=self.config.mode.value, kill_switch_enabled=self.config.kill_switch_enabled and inputs.kill_switch_enabled, timestamp=observed_at)

        analysis = AnalysisOutput(
            schema_version="1.0.0",
            analysis_id=analysis_id_for(inputs.market_context.symbol, inputs.market_context.venue, observed_at),
            timestamp=observed_at,
            market_context=inputs.market_context,
            mode=self.config.mode,
            data_quality=quality,
            market_state=market_state,
            auction_state=auction_state,
            orderflow=orderflow,
            scenarios=scenarios,
            decision=decision,
            report_text="",
            audit=audit_payload,
        )
        report = build_report(analysis)
        analysis = AnalysisOutput(
            schema_version=analysis.schema_version,
            analysis_id=analysis.analysis_id,
            timestamp=analysis.timestamp,
            market_context=analysis.market_context,
            mode=analysis.mode,
            data_quality=analysis.data_quality,
            market_state=analysis.market_state,
            auction_state=analysis.auction_state,
            orderflow=analysis.orderflow,
            scenarios=analysis.scenarios,
            decision=analysis.decision,
            report_text=report,
            audit=analysis.audit,
        )
        return analysis

    def _levels_from_candles(self, candles: Sequence[Candle], price_now: Decimal | None) -> LevelSet:
        closes = [c.close for c in candles]
        last = price_now if price_now is not None else (Decimal(closes[-1]) if closes else None)
        if not candles:
            # No candles, no structural levels; callers end in INSUFFICIENT_DATA / NO_TRADE.
            return LevelSet(last_price=last)
        return LevelSet(
            range_high=Decimal(max(c.high for c in candles)),
            range_low=Decimal(min(c.low for c in candles)),
            midpoint=Decimal((max(c.high for c in candles) + min(c.low for c in candles)) / 2),
            session_high=Decimal(max(c.high for c in candles[-6:])),
            session_low=Decimal(min(c.low for c in candles[-6:])),
            last_price=last,
        )


def _with_profile(levels: LevelSet, profile: ProfileLevels | None) -> LevelSet:
    """Profile levels fill only what the caller did not set explicitly."""
    if profile is None:
        return levels
    updates = {}
    for name in ("point_of_control", "value_area_high", "value_area_low", "initial_balance_high", "initial_balance_low", "poor_high", "poor_low"):
        if getattr(levels, name) is None and getattr(profile, name) is not None:
            updates[name] = getattr(profile, name)
    if not levels.naked_pocs and profile.naked_pocs:
        updates["naked_pocs"] = profile.naked_pocs
    return replace(levels, **updates) if updates else levels


def _mark_confirmed(plan, scenario: Scenario):
    return _with_trace(plan, {"scenario_confirmed": True, "scenario_id": scenario.scenario_id, "scenario_state": scenario.state.value})


def _with_risk_status(plan, risk_decision):
    return _with_trace(plan, {"risk_status": risk_decision.status.value, "risk_reason_codes": list(risk_decision.reason_codes)})


def _with_trace(plan, extra: dict[str, Any]):
    trace = dict(plan.audit_trace)
    trace.update(extra)
    return plan.__class__(
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
        account_risk=plan.account_risk,
        position_size=plan.position_size,
        leverage=plan.leverage,
        liquidation_distance=plan.liquidation_distance,
        estimated_fees=plan.estimated_fees,
        estimated_slippage=plan.estimated_slippage,
        status=plan.status,
        grade=plan.grade,
        grade_reasons=plan.grade_reasons,
        execution_sensitivity=plan.execution_sensitivity,
        audit_trace=trace,
        vetting_mode=plan.vetting_mode,
    )


def _with_leverage(plan, leverage: Decimal):
    return _with_trace(plan, {"requested_leverage": leverage})
