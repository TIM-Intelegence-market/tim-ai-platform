"""Orderflow Interpretation Engine.

This engine does not just report whether delta is positive or negative. It
interprets whether aggressive flow produces price progress, whether flow is
absorbed or exhausted, and what the open interest is doing. Every statement is
typed as OBSERVATION, INTERPRETATION, HYPOTHESIS, CONFIRMATION, or REFUTATION.

Absorption and exhaustion are kept apart by the *effort* behind the move
(docs/knowledge/ORDERFLOW_REGELN.md, rules R1-R4):

* Absorption: heavy aggressive volume, price does not progress in the direction of
  the delta. Someone passive is taking the other side.
* Exhaustion: the aggressive side thins out; volume and range shrink into the
  extreme, or the move stalls on little volume. Nobody is left to push.

With only two candles (no volume baseline) the engine keeps the classic read:
delta against price = absorption hypothesis. A thin-volume read never claims
absorption.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from src.models.market_data import Candle, Trade

from ..domain import OrderflowInterpretation, OrderflowStatement, OrderflowStatementKind
from ..domain import ZERO
from ..footprint import STACK_MIN, FootprintReading, FootprintSeries, analyze_footprint
from ..positioning import (
    PositioningInputs,
    ProfileLevels,
    interpret_positioning,
    interpret_profile,
    open_interest_price_response,
    window_price_response,
)

__all__ = ["OrderflowInputs", "OrderflowInterpretationEngine", "effort_context"]

# Volume of the last candle relative to the mean of the previous candles.
HEAVY_VOLUME_RATIO = Decimal("1.2")  # absorption needs effort at or above the recent norm
THIN_VOLUME_RATIO = Decimal("0.7")  # exhaustion: the aggressor is running out of participants
SHRINKING_RANGE_RATIO = Decimal("0.8")  # exhaustion into an extreme: pushes get smaller
EFFORT_BASELINE_CANDLES = 5


@dataclass(frozen=True, slots=True)
class OrderflowInputs:
    trades: Sequence[Trade] | None = None
    candles: Sequence[Candle] | None = None
    net_delta: Decimal | None = None
    aggressive_buy_volume: Decimal | None = None
    aggressive_sell_volume: Decimal | None = None
    total_volume: Decimal | None = None
    open_interest_trend: str | None = None  # RISING | FALLING | FLAT | UNKNOWN
    open_interest_with_price: str | None = None  # e.g. RISING_WITH_PRICE_UP
    delta_divergence: bool | None = None
    taker_buy_sell_ratio: Decimal | None = None
    volume_bubbles: tuple[str, ...] = ()
    extra_notes: tuple[str, ...] = ()
    # Funding, liquidations, OI series, orderbook depth; and volume profile / TPO (positioning.py).
    positioning: PositioningInputs | None = None
    profile: ProfileLevels | None = None
    # Signed delta per candle (oldest first, aligned with the tail of ``candles``). Optional;
    # used to confirm or refute exhaustion (fading delta, delta flip).
    delta_series: tuple[Decimal, ...] | None = None
    # Bid/ask volume per price level and candle (footprint.py). Optional; supplies the
    # delta series when none is given and confirms or refutes the reaction read.
    footprint: FootprintSeries | None = None

    def __post_init__(self) -> None:
        # net_delta (aggressive buy minus aggressive sell volume) is signed by
        # definition; a negative value means sellers were the aggressors.
        for label, value in (
            ("aggressive_buy_volume", self.aggressive_buy_volume),
            ("aggressive_sell_volume", self.aggressive_sell_volume),
            ("total_volume", self.total_volume),
        ):
            if value is not None and value < 0:
                raise ValueError(f"{label} cannot be negative")
        if self.open_interest_trend is not None and self.open_interest_trend not in {"RISING", "FALLING", "FLAT", "UNKNOWN"}:
            raise ValueError("invalid open_interest_trend")


def effort_context(candles: Sequence[Candle]) -> tuple[Decimal | None, Decimal | None]:
    """Return (volume_ratio, range_ratio) of the last candle against the previous candles.

    Both are ``None`` unless at least two earlier candles with volume exist, so a
    two-candle input has no effort baseline and falls back to the classic read.
    """
    if len(candles) < 3:
        return None, None
    previous = [c for c in candles[-(EFFORT_BASELINE_CANDLES + 1):-1] if c.volume > 0]
    if len(previous) < 2:
        return None, None
    last = candles[-1]
    mean_volume = Decimal(str(sum(c.volume for c in previous))) / Decimal(len(previous))
    mean_range = Decimal(str(sum(c.high - c.low for c in previous))) / Decimal(len(previous))
    volume_ratio = Decimal(str(last.volume)) / mean_volume
    range_ratio = Decimal(str(last.high - last.low)) / mean_range if mean_range > 0 else None
    return volume_ratio, range_ratio


def _delta_series_shape(series: Sequence[Decimal] | None, aggressor_positive: bool) -> str | None:
    """Classify the tail of a per-candle delta series for the given aggressor side.

    FLIP: the last candle's delta turned against the aggressor.
    FADING: the aggressor's delta shrank over the last three candles.
    EXPANDING: the aggressor's delta grew on the last candle.
    None: too short or inconclusive.
    """
    if not series or len(series) < 2:
        return None
    sign = Decimal(1) if aggressor_positive else Decimal(-1)
    signed = [value * sign for value in series]
    if signed[-1] < ZERO < signed[-2]:
        return "FLIP"
    if len(signed) >= 3 and signed[-3] > signed[-2] > signed[-1] > ZERO:
        return "FADING"
    if signed[-1] > signed[-2] > ZERO:
        return "EXPANDING"
    return None


class OrderflowInterpretationEngine:
    """Deterministic interpretation of aggressive flow, price response, and open interest."""

    def evaluate(self, inputs: OrderflowInputs) -> OrderflowInterpretation:
        statements: list[OrderflowStatement] = []
        missing: list[str] = []

        net_delta = inputs.net_delta
        buy_volume = inputs.aggressive_buy_volume
        sell_volume = inputs.aggressive_sell_volume
        total = inputs.total_volume
        candles = inputs.candles or []
        trades = inputs.trades or []
        footprint: FootprintReading | None = None
        delta_series = inputs.delta_series
        if inputs.footprint is not None:
            footprint = analyze_footprint(inputs.footprint)
            if delta_series is None:
                delta_series = inputs.footprint.delta_series
            if net_delta is None:
                # The last bar's delta matches the close-to-close price response below.
                net_delta = inputs.footprint.last.delta
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.OBSERVATION,
                        text="net_delta_derived_from_footprint_last_bar",
                        evidence_refs=("footprint",),
                    )
                )

        # --- 1. Observations from raw metrics ---
        if net_delta is not None:
            side = "BUYERS" if net_delta > ZERO else "SELLERS" if net_delta < ZERO else "NEUTRAL"
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.OBSERVATION,
                    text=f"net_delta={net_delta} aggressive_side={side}",
                    evidence_refs=("net_delta",),
                )
            )
        else:
            missing.append("net_delta")

        if buy_volume is not None and sell_volume is not None and (buy_volume + sell_volume) > ZERO:
            buy_ratio = buy_volume / (buy_volume + sell_volume)
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.OBSERVATION,
                    text=f"aggressive_buy_share={buy_ratio:.3f}",
                    evidence_refs=("aggressive_buy_volume", "aggressive_sell_volume"),
                )
            )
        else:
            missing.append("aggressive_volume")

        # --- 2. Price response ---
        price_response = "UNKNOWN"
        if len(candles) >= 2:
            move = candles[-1].close - candles[-2].close
            if candles[-2].close > 0:
                move_fraction = abs(move) / candles[-2].close
                if move_fraction < 0.001:
                    price_response = "FLAT"
                elif move > 0:
                    price_response = "UP"
                else:
                    price_response = "DOWN"
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.OBSERVATION,
                    text=f"close-to-close move = {move} ({price_response})",
                    evidence_refs=("candles",),
                )
            )

        # --- 3. Interpretation: flow vs price progress ---
        # A zero delta has no aggressive side (NEUTRAL), so neither the
        # interpretation nor the reaction read below applies.
        directional_delta = net_delta is not None and net_delta != ZERO
        delta_direction = bool(net_delta is not None and net_delta > ZERO)
        price_direction = price_response == "UP"
        flow_against_price = directional_delta and price_response in {"UP", "DOWN"} and delta_direction != price_direction
        flow_with_price = directional_delta and price_response in {"UP", "DOWN"} and delta_direction == price_direction
        if flow_against_price:
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.INTERPRETATION,
                    text="aggressive_buyers_limited_price_progress" if delta_direction else "aggressive_sellers_limited_price_progress",
                    evidence_refs=("net_delta", "candles"),
                    weight=Decimal("0.8"),
                )
            )
        elif flow_with_price:
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.INTERPRETATION,
                    text="aggressive_buyers_drive_price_up" if delta_direction else "aggressive_sellers_drive_price_down",
                    evidence_refs=("net_delta", "candles"),
                    weight=Decimal("0.8"),
                )
            )

        # --- 4. Reaction: absorption vs exhaustion (effort behind the move) ---
        volume_ratio, range_ratio = effort_context(candles)
        if volume_ratio is not None:
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.OBSERVATION,
                    text=f"volume_ratio={volume_ratio:.2f} range_ratio={range_ratio:.2f}" if range_ratio is not None else f"volume_ratio={volume_ratio:.2f}",
                    evidence_refs=("candles",),
                )
            )
        heavy = volume_ratio is not None and volume_ratio >= HEAVY_VOLUME_RATIO
        thin = volume_ratio is not None and volume_ratio < THIN_VOLUME_RATIO
        shrinking = range_ratio is not None and range_ratio < SHRINKING_RANGE_RATIO
        aggressor = "buyers" if delta_direction else "sellers"
        passive_side = "PASSIVE_SELLERS" if delta_direction else "PASSIVE_BUYERS"
        exhausted_side = "BUYERS_EXHAUSTED" if delta_direction else "SELLERS_EXHAUSTED"

        absorption_hypothesis: str | None = None
        absorption_confirmed = False
        exhaustion_hypothesis: str | None = None
        exhaustion_confirmed = False
        reaction = "UNRESOLVED"
        if flow_against_price:
            if thin:
                # R3: no progress on thin volume is not absorption; the aggressor simply ran out.
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.REFUTATION,
                        text="absorption_refuted_thin_volume",
                        evidence_refs=("candles", "net_delta"),
                    )
                )
                exhaustion_hypothesis = exhausted_side
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.HYPOTHESIS,
                        text=f"aggressive_{aggressor}_exhausted_thin_volume",
                        evidence_refs=("net_delta", "price_response", "candles"),
                        weight=Decimal("0.6"),
                    )
                )
            else:
                # R1: delta against price = someone passive is taking the other side.
                absorption_hypothesis = passive_side
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.HYPOTHESIS,
                        text="passive_sellers_absorb_market_buys" if delta_direction else "passive_buyers_absorb_market_sells",
                        evidence_refs=("net_delta", "price_response"),
                        weight=Decimal("0.6"),
                    )
                )
                if heavy:
                    statements.append(
                        OrderflowStatement(
                            kind=OrderflowStatementKind.INTERPRETATION,
                            text="absorption_effort_high_volume",
                            evidence_refs=("candles",),
                            weight=Decimal("0.7"),
                        )
                    )
        elif flow_with_price:
            if thin and shrinking:
                # R4: the move continues, but on shrinking volume and range: fuel is running out.
                exhaustion_hypothesis = exhausted_side
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.HYPOTHESIS,
                        text=f"aggressive_{aggressor}_fading_into_extreme",
                        evidence_refs=("net_delta", "candles"),
                        weight=Decimal("0.6"),
                    )
                )
            else:
                reaction = "CONTINUATION"
        elif directional_delta and price_response == "FLAT" and heavy:
            # R2: heavy one-sided effort, no price change at all.
            absorption_hypothesis = passive_side
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.HYPOTHESIS,
                    text="passive_sellers_absorb_market_buys_flat_price" if delta_direction else "passive_buyers_absorb_market_sells_flat_price",
                    evidence_refs=("net_delta", "price_response", "candles"),
                    weight=Decimal("0.6"),
                )
            )

        if absorption_hypothesis and inputs.delta_divergence is True:
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.CONFIRMATION,
                    text="absorption_supported_by_delta_divergence",
                    evidence_refs=("delta_divergence",),
                    weight=Decimal("0.9"),
                )
            )
            absorption_confirmed = True

        # --- 4a. Footprint: per-level evidence confirms or refutes the reaction read ---
        if footprint is not None:
            statements.extend(footprint.statements)
            if absorption_hypothesis and footprint.absorption_cluster == absorption_hypothesis:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.CONFIRMATION,
                        text="absorption_supported_by_footprint_cluster",
                        evidence_refs=("footprint",),
                        weight=Decimal("0.9"),
                    )
                )
                absorption_confirmed = True
            if exhaustion_hypothesis:
                aggressor_stack = footprint.stacked_buy if delta_direction else footprint.stacked_sell
                finished_at_extreme = footprint.finished_high if delta_direction else footprint.finished_low
                thin_at_extreme = footprint.thin_extreme == ("BUYERS_THIN_AT_HIGH" if delta_direction else "SELLERS_THIN_AT_LOW")
                if aggressor_stack >= STACK_MIN:
                    # Stacked imbalances on the aggressor's side: the push is alive, not exhausted.
                    statements.append(
                        OrderflowStatement(
                            kind=OrderflowStatementKind.REFUTATION,
                            text="exhaustion_refuted_stacked_imbalances",
                            evidence_refs=("footprint",),
                        )
                    )
                    exhaustion_hypothesis = None
                    if flow_with_price:
                        reaction = "CONTINUATION"
                elif finished_at_extreme or thin_at_extreme:
                    statements.append(
                        OrderflowStatement(
                            kind=OrderflowStatementKind.CONFIRMATION,
                            text="exhaustion_supported_by_finished_auction" if finished_at_extreme else "exhaustion_supported_by_thin_extreme",
                            evidence_refs=("footprint",),
                            weight=Decimal("0.9"),
                        )
                    )
                    exhaustion_confirmed = True

        if exhaustion_hypothesis:
            shape = _delta_series_shape(delta_series, delta_direction)
            if shape in {"FADING", "FLIP"}:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.CONFIRMATION,
                        text="exhaustion_supported_by_fading_delta" if shape == "FADING" else "exhaustion_supported_by_delta_flip",
                        evidence_refs=("delta_series",),
                        weight=Decimal("0.9"),
                    )
                )
                exhaustion_confirmed = True
            elif shape == "EXPANDING":
                # The aggressor is still adding: the stall is a pause, not exhaustion.
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.REFUTATION,
                        text="exhaustion_refuted_delta_expanding",
                        evidence_refs=("delta_series",),
                    )
                )
                exhaustion_hypothesis = None
                if flow_with_price:
                    reaction = "CONTINUATION"
            elif delta_series is None:
                missing.append("delta_series")

        if absorption_hypothesis:
            reaction = "ABSORPTION"
        elif exhaustion_hypothesis:
            reaction = "EXHAUSTION"

        # --- 4b. Positioning (funding, liquidations, OI series, orderbook depth) ---
        # Context values describe a window, so they are compared with the price move over that
        # window, never with the last close-to-close step.
        positioning = interpret_positioning(
            inputs.positioning,
            window_price_response(candles),
            open_interest_price_response(candles, inputs.positioning.open_interest) if inputs.positioning else None,
        )
        open_interest_with_price = inputs.open_interest_with_price
        open_interest_trend = inputs.open_interest_trend
        open_interest_refs: tuple[str, ...] = ("open_interest_with_price",)
        series_with_price, series_trend = positioning.open_interest_with_price, positioning.open_interest_trend
        explicit_trends = {value for value in (open_interest_trend, (open_interest_with_price or "").split("_")[0] or None) if value and value != "UNKNOWN"}
        conflict = bool(
            (open_interest_with_price and series_with_price and open_interest_with_price != series_with_price)
            or (series_trend and explicit_trends and explicit_trends != {series_trend})
        )
        if conflict:
            # Two sources disagree: neither is interpreted (fail closed).
            missing.append("conflict:open_interest_input_vs_series")
            open_interest_with_price = open_interest_trend = None
        elif not open_interest_with_price and series_with_price:
            # Derived from the supplied OI series and the price over the same span, never assumed.
            open_interest_with_price = series_with_price
            open_interest_refs = ("open_interest", "candles")
        open_interest_trend = open_interest_trend or (None if conflict else series_trend)

        # --- 5. Open interest interpretation ---
        oi_interpretation: str | None = None
        if open_interest_with_price:
            mapping = {
                "RISING_WITH_PRICE_UP": "long_accumulation",
                "RISING_WITH_PRICE_DOWN": "short_accumulation",
                "FALLING_WITH_PRICE_UP": "short_covering",
                "FALLING_WITH_PRICE_DOWN": "long_liquidation",
            }
            oi_interpretation = mapping.get(open_interest_with_price)
            if oi_interpretation:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.INTERPRETATION,
                        text=f"open_interest_{oi_interpretation}",
                        evidence_refs=open_interest_refs,
                        weight=Decimal("0.7"),
                    )
                )
        elif open_interest_trend and positioning.open_interest_trend is None:
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.OBSERVATION,
                    text=f"open_interest_trend={open_interest_trend}",
                    evidence_refs=("open_interest_trend",),
                )
            )

        # --- 6. Volume bubbles ---
        for bubble in inputs.volume_bubbles:
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.OBSERVATION,
                    text=f"volume_bubble={bubble}",
                    evidence_refs=("volume_bubbles",),
                )
            )

        # --- 8. Confidence ---
        observed = [s for s in statements if s.kind == OrderflowStatementKind.OBSERVATION]
        confidence = Decimal("0.55")
        confidence += Decimal(len(observed)) * Decimal("0.05")
        if absorption_hypothesis:
            confidence += Decimal("0.1")
        if absorption_confirmed:
            confidence += Decimal("0.15")
        if exhaustion_hypothesis:
            confidence += Decimal("0.1")
        if exhaustion_confirmed:
            confidence += Decimal("0.15")
        if inputs.delta_divergence is True:
            confidence += Decimal("0.05")
        # Context data adds a little confidence per category present, at most +0.08,
        # and does not count towards the observation bonus above.
        last_price = Decimal(str(candles[-1].close)) if candles else None
        profile_statements, profile_summary, profile_missing = interpret_profile(inputs.profile, last_price)
        categories = sum(1 for key in ("funding", "liquidations", "open_interest", "orderbook_depth") if key in positioning.summary)
        categories += 1 if profile_summary else 0
        confidence += min(Decimal("0.08"), Decimal("0.02") * categories)
        statements.extend(positioning.statements)
        statements.extend(profile_statements)
        # Gaps are listed once any context is supplied; analyses without context keep their output.
        if inputs.positioning is not None or inputs.profile is not None:
            missing.extend(positioning.missing)
            missing.extend(profile_missing)
        confidence = max(ZERO, min(Decimal("1"), confidence))

        return OrderflowInterpretation(
            aggressive_side=side if net_delta is not None else "UNKNOWN",
            price_response=price_response,
            absorption_hypothesis=absorption_hypothesis,
            absorption_confirmed=absorption_confirmed,
            open_interest_interpretation=oi_interpretation,
            statements=tuple(statements),
            confidence=confidence,
            missing_data=tuple(sorted(set(missing))) if (inputs.positioning or inputs.profile) else tuple(sorted(missing)),
            positioning=positioning.summary if inputs.positioning is not None else {},
            profile=profile_summary,
            reaction=reaction,
            exhaustion_hypothesis=exhaustion_hypothesis,
            exhaustion_confirmed=exhaustion_confirmed,
            footprint=footprint.summary if footprint is not None else {},
        )