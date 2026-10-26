"""Scenario Generator.

Generates two to five plausible scenarios from the market state, auction state,
and orderflow interpretation. Each scenario has a hypothesis, supporting and
conflicting evidence, mandatory and optional confirmations, and an explicit
invalidation set. No scenario is a trade; no scenario score triggers a trade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from ..domain import ConfirmationState, Direction, EntryModel, MarketStateKind, Scenario, ScenarioType
from ..domain import MarketState as MarketStateModel
from ..domain import AuctionState as AuctionStateModel
from ..domain import OrderflowInterpretation

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class LevelSet:
    """Liquidity and structural levels relevant to scenario generation."""

    range_high: Decimal | None = None
    range_low: Decimal | None = None
    value_area_high: Decimal | None = None
    value_area_low: Decimal | None = None
    session_high: Decimal | None = None
    session_low: Decimal | None = None
    previous_day_high: Decimal | None = None
    previous_day_low: Decimal | None = None
    weekly_high: Decimal | None = None
    weekly_low: Decimal | None = None
    midpoint: Decimal | None = None
    point_of_control: Decimal | None = None
    last_price: Decimal | None = None
    # TPO references (positioning.ProfileLevels): initial balance, unfinished auctions, naked POCs.
    initial_balance_high: Decimal | None = None
    initial_balance_low: Decimal | None = None
    poor_high: Decimal | None = None
    poor_low: Decimal | None = None
    naked_pocs: tuple[Decimal, ...] = ()
    # Broncx guidance (see external_context.active_view): his LEVEL prices and current direction.
    external_levels: tuple[Decimal, ...] = ()
    external_bias: str | None = None

    def __post_init__(self) -> None:
        for name, value in self._prices():
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")
        if any(value <= 0 for value in self.external_levels):
            raise ValueError("external_levels must be positive")
        if any(value <= 0 for value in self.naked_pocs):
            raise ValueError("naked_pocs must be positive")
        if self.external_bias not in {None, "LONG", "SHORT"}:
            raise ValueError("external_bias must be LONG, SHORT or None")

    def _prices(self):
        for name in (
            "range_high",
            "range_low",
            "value_area_high",
            "value_area_low",
            "session_high",
            "session_low",
            "previous_day_high",
            "previous_day_low",
            "weekly_high",
            "weekly_low",
            "midpoint",
            "point_of_control",
            "last_price",
            "initial_balance_high",
            "initial_balance_low",
            "poor_high",
            "poor_low",
        ):
            yield name, getattr(self, name)


def _build_scenario(
    scenario_id: str,
    scenario_type: ScenarioType,
    direction: Direction,
    hypothesis: str,
    evidence_for: tuple[str, ...],
    evidence_against: tuple[str, ...],
    mandatory: tuple[str, ...],
    optional: tuple[str, ...],
    invalidation: tuple[str, ...],
    trigger_level: Decimal | None,
    entry_low: Decimal | None,
    entry_high: Decimal | None,
    entry_model: EntryModel,
    score: Decimal,
) -> Scenario:
    return Scenario(
        scenario_id=scenario_id,
        scenario_type=scenario_type,
        direction=direction,
        hypothesis=hypothesis,
        trigger_level=trigger_level,
        entry_zone_low=entry_low,
        entry_zone_high=entry_high,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        mandatory_confirmations=mandatory,
        optional_confirmations=optional,
        invalidation=invalidation,
        score=score,
        score_type="UNCALIBRATED_CONFIDENCE",
        state=ConfirmationState.PROPOSED,
        confirmation=None,
        trade_template={"direction": direction.value, "entry_model": entry_model.value},
    )


class ScenarioGenerator:
    """Builds the scenario set for a single analysis."""

    def generate(
        self,
        market_state: MarketStateModel,
        auction_state: AuctionStateModel,
        orderflow: OrderflowInterpretation,
        levels: LevelSet,
    ) -> tuple[Scenario, ...]:
        scenarios: list[Scenario] = []
        primary = market_state.primary
        last = levels.last_price
        range_high = levels.range_high
        range_low = levels.range_low

        near_range_high = range_high is not None and last is not None and last >= range_high * Decimal("0.995") and last <= range_high * Decimal("1.02")
        near_range_low = range_low is not None and last is not None and last <= range_low * Decimal("1.005") and last >= range_low * Decimal("0.98")
        delta_constructive = orderflow.aggressive_side == "BUYERS"
        delta_bearish = orderflow.aggressive_side == "SELLERS"
        absorption_sellers = orderflow.absorption_hypothesis == "PASSIVE_SELLERS"
        absorption_buyers = orderflow.absorption_hypothesis == "PASSIVE_BUYERS"
        buyers_exhausted = orderflow.exhaustion_hypothesis == "BUYERS_EXHAUSTED"
        sellers_exhausted = orderflow.exhaustion_hypothesis == "SELLERS_EXHAUSTED"
        # Footprint: three or more stacked imbalances are aggression with continuation bias.
        stacked_buy = (orderflow.footprint or {}).get("stacked_buy", 0) >= 3
        stacked_sell = (orderflow.footprint or {}).get("stacked_sell", 0) >= 3

        # A retest of the breakout edge needs price near or above that edge. Far below it there is
        # no breakout to retest (25.10.2026: 30m LONG retest at 82.143 with BTC at 80.810, 1W LONG
        # retest at 126.326 with BTC at 82.116). "Near" is the 1 % window used for external levels;
        # a reclaim far below the low keeps the lower bound of near_range_low.
        below_breakout_edge = range_high is not None and last is not None and last < range_high * (1 - BREAKOUT_EDGE_WINDOW)
        below_reclaim_level = range_low is not None and last is not None and last < range_low * Decimal("0.98")

        # --- Scenario A: Breakout / Acceptance / Continuation ---
        breakout_interest = (primary in {MarketStateKind.BREAKOUT_ATTEMPT, MarketStateKind.ACCEPTANCE_ABOVE_VALUE, MarketStateKind.TREND_UP} or near_range_high) and not below_breakout_edge
        if breakout_interest:
            trigger = range_high or (last or Decimal("0"))
            entry_low = trigger * Decimal("1.001")
            entry_high = trigger * Decimal("1.008")
            evidence_for = ["tests_range_high" if near_range_high else "structure_supports_breakout"]
            if delta_constructive:
                evidence_for = evidence_for + ["delta_constructive"]
            if absorption_sellers:
                evidence_for = evidence_for + ["absorption_hypothesis_passive_sellers"]
            if sellers_exhausted:
                evidence_for = evidence_for + ["exhaustion_hypothesis_sellers_exhausted"]
            if stacked_buy:
                evidence_for = evidence_for + ["footprint_stacked_buy_imbalances"]
            evidence_against = []
            if absorption_buyers:
                evidence_against = evidence_against + ["absorption_hypothesis_passive_buyers"]
            if buyers_exhausted:
                evidence_against = evidence_against + ["exhaustion_hypothesis_buyers_exhausted"]
            if stacked_sell:
                evidence_against = evidence_against + ["footprint_stacked_sell_imbalances"]
            if delta_bearish:
                evidence_against = evidence_against + ["delta_bearish"]
            scenarios.append(
                _build_scenario(
                    scenario_id="A",
                    scenario_type=ScenarioType.BREAKOUT_ACCEPTANCE,
                    direction=Direction.LONG,
                    hypothesis="Breakout above the level with acceptance and constructive flow; retest defended.",
                    evidence_for=tuple(evidence_for),
                    evidence_against=tuple(evidence_against),
                    mandatory=(
                        "close_above_trigger_level",
                        "constructive_price_response",
                        "no_immediate_fall_back",
                        "retest_holds_or_momentum_continuation",
                        "valid_invalidation_defined",
                    ),
                    optional=("delta_positive", "open_interest_rising", "value_migrating", "volume_expanding", "spot_confirms_futures"),
                    invalidation=("close_back_below_trigger", "delta_positive_without_progress", "retest_lost"),
                    trigger_level=trigger,
                    entry_low=entry_low,
                    entry_high=entry_high,
                    entry_model=EntryModel.LIMIT_RETEST if entry_low is not None else EntryModel.MARKET_AFTER_CONFIRMATION,
                    score=Decimal("0.38"),
                )
            )

        # --- Scenario B: Liquidity sweep / reversal ---
        sweep_interest = (primary in {MarketStateKind.LIQUIDITY_SWEEP_LOW, MarketStateKind.REJECTION_BELOW_VALUE, MarketStateKind.FAILED_AUCTION_LOW} or near_range_low) and not below_reclaim_level
        if sweep_interest:
            trigger = range_low or (last or Decimal("0"))
            entry_low = trigger * Decimal("1.001") if trigger else None
            entry_high = trigger * Decimal("1.006") if trigger else None
            evidence_for = ["sweep_of_defined_liquidity"]
            if delta_bearish:
                evidence_for = evidence_for + ["delta_strongly_negative_without_follow_through"]
            if absorption_buyers:
                evidence_for = evidence_for + ["absorption_hypothesis_passive_buyers"]
            if sellers_exhausted:
                evidence_for = evidence_for + ["exhaustion_hypothesis_sellers_exhausted"]
            evidence_against = []
            if stacked_sell:
                evidence_against = evidence_against + ["footprint_stacked_sell_imbalances"]
            if orderflow.open_interest_interpretation == "short_accumulation":
                evidence_against = evidence_against + ["short_accumulation_conflicts_reversal"]
            scenarios.append(
                _build_scenario(
                    scenario_id="B",
                    scenario_type=ScenarioType.LIQUIDITY_SWEEP_REVERSAL,
                    direction=Direction.LONG,
                    hypothesis="Defined liquidity below was swept, price fails to sustain, and the level is reclaimed.",
                    evidence_for=tuple(evidence_for),
                    evidence_against=tuple(evidence_against),
                    mandatory=(
                        "defined_liquidity_swept",
                        "no_sustained_progress_below",
                        "level_reclaimed",
                        "reclaim_holds",
                        "invalidatable_stop_available",
                    ),
                    optional=("delta_negative_divergence", "buyer_absorption", "seller_exhaustion", "open_interest_falling", "long_liquidations_ending", "cvd_stabilizing"),
                    invalidation=("acceptance_below_level", "value_migrating_down", "open_interest_rising_with_price_fall", "reclaim_fails"),
                    trigger_level=trigger,
                    entry_low=entry_low,
                    entry_high=entry_high,
                    entry_model=EntryModel.RECLAIM,
                    score=Decimal("0.34"),
                )
            )

        # --- Scenario C: Rejection / failed breakout / reversal ---
        rejection_interest = primary in {MarketStateKind.REJECTION_ABOVE_VALUE, MarketStateKind.BREAKDOWN_ATTEMPT, MarketStateKind.FAILED_AUCTION_HIGH} or near_range_high
        if rejection_interest:
            trigger = range_high or (last or Decimal("0"))
            entry_low = trigger * Decimal("0.995") if trigger else None
            entry_high = trigger * Decimal("0.999") if trigger else None
            evidence_for = ["tested_upper_liquidity"]
            if delta_constructive:
                evidence_for = evidence_for + ["positive_delta_limited_progress"]
            if absorption_sellers:
                evidence_for = evidence_for + ["absorption_hypothesis_passive_sellers"]
            if buyers_exhausted:
                evidence_for = evidence_for + ["exhaustion_hypothesis_buyers_exhausted"]
            evidence_against = []
            if stacked_buy:
                evidence_against = evidence_against + ["footprint_stacked_buy_imbalances"]
            if orderflow.open_interest_interpretation == "long_accumulation":
                evidence_against = evidence_against + ["long_accumulation_conflicts_rejection"]
            scenarios.append(
                _build_scenario(
                    scenario_id="C",
                    scenario_type=ScenarioType.REJECTION_FAILED_BREAKOUT,
                    direction=Direction.SHORT,
                    hypothesis="Upper liquidity tested, acceptance fails, price falls back below the trigger and the retest fails.",
                    evidence_for=tuple(evidence_for),
                    evidence_against=tuple(evidence_against),
                    mandatory=(
                        "upper_trigger_tested",
                        "acceptance_above_fails",
                        "return_below_level",
                        "retest_from_below_fails",
                        "valid_invalidation_above",
                    ),
                    optional=("positive_delta_without_progress", "seller_absorption", "buyer_exhaustion", "open_interest_rising_into_rejection", "buyers_trapped"),
                    invalidation=("acceptance_above_level", "value_migrating_up", "constructive_breakout", "sellers_cannot_create_retreat"),
                    trigger_level=trigger,
                    entry_low=entry_low,
                    entry_high=entry_high,
                    entry_model=EntryModel.FAILED_RETEST,
                    score=Decimal("0.28"),
                )
            )

        # --- Fallback: balance / uncertain market needs neutral scenarios ---
        if not scenarios:
            scenarios.append(
                _build_scenario(
                    scenario_id="A",
                    scenario_type=ScenarioType.BALANCE_ROTATION,
                    direction=Direction.NEUTRAL,
                    hypothesis="Market trades a balance; rotation between range extremes with no directional edge.",
                    evidence_for=("balanced_structure",),
                    evidence_against=(),
                    mandatory=("range_extremes_respected", "no_acceptance_beyond_range"),
                    optional=("volume_drying_up_at_extremes", "delta_neutral"),
                    invalidation=("acceptance_beyond_range",),
                    trigger_level=None,
                    entry_low=None,
                    entry_high=None,
                    entry_model=EntryModel.ENTRY_ZONE,
                    score=Decimal("0.35"),
                )
            )
            scenarios.append(
                _build_scenario(
                    scenario_id="B",
                    scenario_type=ScenarioType.VALUE_REVERSION,
                    direction=Direction.NEUTRAL,
                    hypothesis="Price extends away from value and reverts toward the point of control.",
                    evidence_for=("extension_from_value",),
                    evidence_against=(),
                    mandatory=("price_reaches_value_edge", "no_initiative_follow_through"),
                    optional=("delta_opposing_extension",),
                    invalidation=("value_migrates_toward_extension",),
                    trigger_level=levels.point_of_control,
                    entry_low=None,
                    entry_high=None,
                    entry_model=EntryModel.PULLBACK,
                    score=Decimal("0.30"),
                )
            )

        # --- External levels: Broncx's levels near price, in his direction ---
        scenarios.extend(_external_level_scenarios(levels, scenarios, orderflow))

        # Normalize scores so the sum is approximately 1.0 and cap at max_scenarios.
        if scenarios:
            total = sum((scenario.score for scenario in scenarios), ZERO)
            if total > 0:
                scenarios = [
                    _replace_score(scenario, (scenario.score / total) * Decimal("0.9"))
                    for scenario in scenarios
                ]
            remainder = Decimal("0.9") - sum((scenario.score for scenario in scenarios), ZERO)
            scenarios = [_add_score(scenarios[0], remainder)] + scenarios[1:]

        return tuple(scenarios)


# A breakout retest (scenario A) is proposed only while price is within 1 % below the range high.
BREAKOUT_EDGE_WINDOW = Decimal("0.01")
# A Broncx level becomes a scenario only within 1 % of price, and not when TIM already has a trigger within 0.2 %.
EXTERNAL_LEVEL_WINDOW = Decimal("0.01")
EXTERNAL_LEVEL_DUPLICATE = Decimal("0.002")
MAX_EXTERNAL_SCENARIOS = 2


def _external_level_scenarios(levels: LevelSet, existing: list[Scenario], orderflow: OrderflowInterpretation) -> list[Scenario]:
    """Directional scenarios at Broncx's levels. Same mandatory confirmations as TIM's own templates."""
    bias, last = levels.external_bias, levels.last_price
    if bias not in {"LONG", "SHORT"} or last is None or last <= 0:
        return []
    triggers = [scenario.trigger_level for scenario in existing if scenario.trigger_level]
    accepted: list[Decimal] = []
    for level in sorted(set(levels.external_levels), key=lambda value: (abs(value - last), value)):
        if len(accepted) == MAX_EXTERNAL_SCENARIOS or abs(level - last) / last > EXTERNAL_LEVEL_WINDOW:
            break
        # Also against levels accepted just before: 83100 and 83110 are one place, not two scenarios.
        if all(abs(level - trigger) / trigger > EXTERNAL_LEVEL_DUPLICATE for trigger in triggers + accepted):
            accepted.append(level)
    # The id names the level, so a confirmation update can never land on a different level.
    return [_external_scenario(f"X-{bias}-{format(level.normalize(), 'f')}", bias, level, last, orderflow) for level in accepted]


def _external_scenario(scenario_id: str, bias: str, level: Decimal, last: Decimal, orderflow: OrderflowInterpretation) -> Scenario:
    buyers, sellers = orderflow.aggressive_side == "BUYERS", orderflow.aggressive_side == "SELLERS"
    if bias == "SHORT":
        evidence_for = ("delta_bearish",) if sellers else ()
        evidence_against = ("delta_constructive",) if buyers else ()
        if level >= last:
            scenario_type, entry_model = ScenarioType.REJECTION_FAILED_BREAKOUT, EntryModel.FAILED_RETEST
            hypothesis = f"Broncx level {level}: price tests it from below, acceptance above fails and the retest fails."
            mandatory = ("upper_trigger_tested", "acceptance_above_fails", "return_below_level", "retest_from_below_fails", "valid_invalidation_above")
            invalidation = ("acceptance_above_level", "value_migrating_up", "constructive_breakout")
            entry_low, entry_high = level * Decimal("0.995"), level * Decimal("0.999")
        else:
            scenario_type, entry_model = ScenarioType.BREAKOUT_ACCEPTANCE, EntryModel.LIMIT_RETEST
            hypothesis = f"Broncx level {level}: price closes below it, is accepted below and the retest from below fails."
            mandatory = ("close_below_trigger_level", "weak_price_response", "no_immediate_reclaim", "retest_from_below_fails", "valid_invalidation_defined")
            invalidation = ("close_back_above_trigger", "retest_reclaimed", "delta_negative_without_progress")
            entry_low, entry_high = level * Decimal("0.992"), level * Decimal("0.999")
        direction = Direction.SHORT
    else:
        evidence_for = ("delta_constructive",) if buyers else ()
        evidence_against = ("delta_bearish",) if sellers else ()
        if level <= last:
            scenario_type, entry_model = ScenarioType.LIQUIDITY_SWEEP_REVERSAL, EntryModel.RECLAIM
            hypothesis = f"Broncx level {level}: price tests it from above, fails to hold below and reclaims it."
            mandatory = ("defined_liquidity_swept", "no_sustained_progress_below", "level_reclaimed", "reclaim_holds", "invalidatable_stop_available")
            invalidation = ("acceptance_below_level", "value_migrating_down", "reclaim_fails")
            entry_low, entry_high = level * Decimal("1.001"), level * Decimal("1.006")
        else:
            scenario_type, entry_model = ScenarioType.BREAKOUT_ACCEPTANCE, EntryModel.LIMIT_RETEST
            hypothesis = f"Broncx level {level}: breakout above it with acceptance and constructive flow; retest defended."
            mandatory = ("close_above_trigger_level", "constructive_price_response", "no_immediate_fall_back", "retest_holds_or_momentum_continuation", "valid_invalidation_defined")
            invalidation = ("close_back_below_trigger", "delta_positive_without_progress", "retest_lost")
            entry_low, entry_high = level * Decimal("1.001"), level * Decimal("1.008")
        direction = Direction.LONG
    scenario = _build_scenario(
        scenario_id=scenario_id,
        scenario_type=scenario_type,
        direction=direction,
        hypothesis=hypothesis,
        evidence_for=evidence_for,
        evidence_against=evidence_against,
        mandatory=mandatory,
        optional=(),
        invalidation=invalidation,
        trigger_level=level,
        entry_low=entry_low,
        entry_high=entry_high,
        entry_model=entry_model,
        score=Decimal("0.30"),
    )
    scenario.trade_template["level_source"] = "broncx"
    return scenario


def _replace_score(scenario: Scenario, score: Decimal) -> Scenario:
    return Scenario(
        scenario_id=scenario.scenario_id,
        scenario_type=scenario.scenario_type,
        direction=scenario.direction,
        hypothesis=scenario.hypothesis,
        trigger_level=scenario.trigger_level,
        entry_zone_low=scenario.entry_zone_low,
        entry_zone_high=scenario.entry_zone_high,
        evidence_for=scenario.evidence_for,
        evidence_against=scenario.evidence_against,
        mandatory_confirmations=scenario.mandatory_confirmations,
        optional_confirmations=scenario.optional_confirmations,
        invalidation=scenario.invalidation,
        score=score,
        score_type=scenario.score_type,
        state=scenario.state,
        confirmation=scenario.confirmation,
        trade_template=scenario.trade_template,
    )


def _add_score(scenario: Scenario, amount: Decimal) -> Scenario:
    return _replace_score(scenario, min(Decimal("1"), max(ZERO, scenario.score + amount)))