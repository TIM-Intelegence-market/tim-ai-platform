"""Orderflow Interpretation Engine.

This engine does not just report whether delta is positive or negative. It
interprets whether aggressive flow produces price progress, whether flow is
absorbed, and what the open interest is doing. Every statement is typed as
OBSERVATION, INTERPRETATION, HYPOTHESIS, CONFIRMATION, or REFUTATION.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from src.models.market_data import Candle, Trade

from ..domain import OrderflowInterpretation, OrderflowStatement, OrderflowStatementKind
from ..domain import ZERO
from ..positioning import (
    PositioningInputs,
    ProfileLevels,
    interpret_positioning,
    interpret_profile,
    open_interest_price_response,
    window_price_response,
)

__all__ = ["OrderflowInputs", "OrderflowInterpretationEngine"]


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
        # interpretation nor the absorption hypothesis below applies.
        directional_delta = net_delta is not None and net_delta != ZERO
        if directional_delta and price_response in {"UP", "DOWN"}:
            delta_direction = net_delta > ZERO
            price_direction = price_response == "UP"
            if delta_direction and not price_direction:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.INTERPRETATION,
                        text="aggressive_buyers_limited_price_progress",
                        evidence_refs=("net_delta", "candles"),
                        weight=Decimal("0.8"),
                    )
                )
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.HYPOTHESIS,
                        text="passive_sellers_absorb_market_buys",
                        evidence_refs=("net_delta", "price_response"),
                        weight=Decimal("0.6"),
                    )
                )
            elif not delta_direction and price_direction:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.INTERPRETATION,
                        text="aggressive_sellers_limited_price_progress",
                        evidence_refs=("net_delta", "candles"),
                        weight=Decimal("0.8"),
                    )
                )
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.HYPOTHESIS,
                        text="passive_buyers_absorb_market_sells",
                        evidence_refs=("net_delta", "price_response"),
                        weight=Decimal("0.6"),
                    )
                )
            elif delta_direction and price_direction:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.INTERPRETATION,
                        text="aggressive_buyers_drive_price_up",
                        evidence_refs=("net_delta", "candles"),
                        weight=Decimal("0.8"),
                    )
                )
            elif not delta_direction and not price_direction:
                statements.append(
                    OrderflowStatement(
                        kind=OrderflowStatementKind.INTERPRETATION,
                        text="aggressive_sellers_drive_price_down",
                        evidence_refs=("net_delta", "candles"),
                        weight=Decimal("0.8"),
                    )
                )

        # --- 4. Absorption hypothesis ---
        absorption_hypothesis: str | None = None
        absorption_confirmed = False
        if directional_delta and price_response in {"UP", "DOWN"}:
            delta_direction = net_delta > ZERO
            price_direction = price_response == "UP"
            if delta_direction and not price_direction:
                absorption_hypothesis = "PASSIVE_SELLERS"
            elif not delta_direction and price_direction:
                absorption_hypothesis = "PASSIVE_BUYERS"
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

        # --- 7. Refutations ---
        if absorption_hypothesis == "PASSIVE_SELLERS" and price_response == "UP":
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.REFUTATION,
                    text="absorption_refuted_price_advanced",
                    evidence_refs=("candles",),
                )
            )
            absorption_confirmed = False
        elif absorption_hypothesis == "PASSIVE_BUYERS" and price_response == "DOWN":
            statements.append(
                OrderflowStatement(
                    kind=OrderflowStatementKind.REFUTATION,
                    text="absorption_refuted_price_fell",
                    evidence_refs=("candles",),
                )
            )
            absorption_confirmed = False

        # --- 8. Confidence ---
        observed = [s for s in statements if s.kind == OrderflowStatementKind.OBSERVATION]
        confidence = Decimal("0.55")
        confidence += Decimal(len(observed)) * Decimal("0.05")
        if absorption_hypothesis:
            confidence += Decimal("0.1")
        if absorption_confirmed:
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
        )