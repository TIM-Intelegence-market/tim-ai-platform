"""Market State and Auction State Engines.

These engines classify the current market regime from deterministic rules over
candles. They produce a primary state, secondary states, evidence, conflicts,
confidence, missing data, and explicit invalidation conditions. They never
declare a directional trade; they only describe structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, pstdev
from typing import Any, Sequence

from src.models.market_data import Candle

from ..domain import AuctionState as AuctionStateModel
from ..domain import AuctionStateKind, MarketState as MarketStateModel
from ..domain import MarketStateKind

ZERO = Decimal("0")

# Swing detection window parameter.
PIVOT_WINDOW = 2


@dataclass(frozen=True, slots=True)
class Swing:
    index: int
    price: float
    kind: str  # HIGH | LOW


def swing_points(candles: Sequence[Candle], width: int = PIVOT_WINDOW) -> list[Swing]:
    result: list[Swing] = []
    for index in range(width, len(candles) - width):
        candle = candles[index]
        neighbours = candles[index - width : index] + candles[index + 1 : index + width + 1]
        if all(candle.high > item.high for item in neighbours):
            result.append(Swing(index, candle.high, "HIGH"))
        if all(candle.low < item.low for item in neighbours):
            result.append(Swing(index, candle.low, "LOW"))
    return result


def _rng(candles: Sequence[Candle]) -> tuple[float, float]:
    highs = [candle.high for candle in candles]
    lows = [candle.low for candle in candles]
    return min(lows), max(highs)


def _volatility_ratio(candles: Sequence[Candle]) -> float:
    if len(candles) < 5:
        return 1.0
    recent = [abs(candle.close - candle.open) / candle.open for candle in candles[-3:]]
    older = [abs(candle.close - candle.open) / candle.open for candle in candles[:-3]]
    return mean(recent) / mean(older) if older and mean(older) > 0 else 1.0


def _range_percent(candles: Sequence[Candle]) -> float:
    low, high = _rng(candles)
    last = candles[-1].close
    return (high - low) / last if last > 0 else 0.0


def _higher_highs_higher_lows(candles: Sequence[Candle]) -> tuple[bool, bool, list[str]]:
    swings = swing_points(candles)
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    evidence: list[str] = []
    hh = len(highs) >= 2 and highs[-1].price > highs[-2].price
    hl = len(lows) >= 2 and lows[-1].price > lows[-2].price
    if hh:
        evidence.append("higher_highs")
    if hl:
        evidence.append("higher_lows")
    return hh, hl, evidence


def _lower_highs_lower_lows(candles: Sequence[Candle]) -> tuple[bool, bool, list[str]]:
    swings = swing_points(candles)
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    evidence: list[str] = []
    lh = len(highs) >= 2 and highs[-1].price < highs[-2].price
    ll = len(lows) >= 2 and lows[-1].price < lows[-2].price
    if lh:
        evidence.append("lower_highs")
    if ll:
        evidence.append("lower_lows")
    return lh, ll, evidence


def _is_sweep(candles: Sequence[Candle], kind: str) -> bool:
    """Detect a liquidity sweep: extreme wick beyond a prior level with close back inside."""
    if len(candles) < PIVOT_WINDOW * 2 + 2:
        return False
    swings = swing_points(candles)
    if kind == "LOW":
        lows = [s for s in swings if s.kind == "LOW"]
        if len(lows) < 2:
            return False
        prior = lows[-1].price
        current = candles[-2]
        return current.low < prior and current.close > prior
    highs = [s for s in swings if s.kind == "HIGH"]
    if len(highs) < 2:
        return False
    prior = highs[-1].price
    current = candles[-2]
    return current.high > prior and current.close < prior


class MarketStateEngine:
    """Deterministic market-state classification from candles."""

    def evaluate(self, candles: Sequence[Candle]) -> MarketStateModel:
        if len(candles) < 2:
            return MarketStateModel(
                primary=MarketStateKind.UNCERTAIN,
                secondary=(),
                evidence=("insufficient_length",),
                conflicts=(),
                confidence=Decimal("0.2"),
                missing_data=("candles",),
                invalidation_conditions=("more_history_required",),
            )

        evidence: list[str] = []
        conflicts: list[str] = []
        last = candles[-1]
        prev = candles[-2]
        vol_ratio = _volatility_ratio(candles)
        rng_pct = _range_percent(candles)

        hh, hl, hh_evidence = _higher_highs_higher_lows(candles)
        lh, ll, ll_evidence = _lower_highs_lower_lows(candles)
        evidence.extend(hh_evidence)
        evidence.extend(ll_evidence)

        high = max(c.high for c in candles)
        low = min(c.low for c in candles)
        range_high = max(c.high for c in candles[-20:]) if len(candles) >= 20 else high
        range_low = min(c.low for c in candles[-20:]) if len(candles) >= 20 else low
        mid = (range_high + range_low) / 2

        secondary: list[MarketStateKind] = []
        primary: MarketStateKind = MarketStateKind.BALANCE

        # Volatility regime.
        if vol_ratio >= 1.5:
            secondary.append(MarketStateKind.EXPANSION)
            evidence.append(f"expansion({vol_ratio:.2f})")
        elif vol_ratio <= 0.7:
            secondary.append(MarketStateKind.COMPRESSION)
            evidence.append(f"compression({vol_ratio:.2f})")

        # Trend structure.
        bullish = hh and hl and last.close > mid
        bearish = lh and ll and last.close < mid
        if bullish:
            primary = MarketStateKind.TREND_UP
            evidence.append("bullish_structure_hh_hl")
        elif bearish:
            primary = MarketStateKind.TREND_DOWN
            evidence.append("bearish_structure_lh_ll")
        else:
            primary = MarketStateKind.BALANCE
            evidence.append("balanced_structure")

        # Breakout / breakdown attempts.
        if last.close > range_high * 1.0 and prev.close <= range_high:
            if last.close > range_high:
                primary = MarketStateKind.BREAKOUT_ATTEMPT
                evidence.append(f"breakout_above_range_high({range_high:.2f})")
        if last.close < range_low and prev.close >= range_low:
            primary = MarketStateKind.BREAKDOWN_ATTEMPT
            evidence.append(f"breakdown_below_range_low({range_low:.2f})")

        # Acceptance vs rejection.
        above_high = last.close > range_high
        below_low = last.close < range_low
        if above_high:
            if last.close > prev.close and vol_ratio >= 0.9:
                secondary.append(MarketStateKind.ACCEPTANCE_ABOVE_VALUE)
                evidence.append("acceptance_above_value")
            elif last.high > range_high and last.close <= range_high:
                secondary.append(MarketStateKind.REJECTION_ABOVE_VALUE)
                evidence.append("rejection_above_value_wick")
        if below_low:
            if last.close < prev.close and vol_ratio >= 0.9:
                secondary.append(MarketStateKind.ACCEPTANCE_BELOW_VALUE)
                evidence.append("acceptance_below_value")
            elif last.low < range_low and last.close >= range_low:
                secondary.append(MarketStateKind.REJECTION_BELOW_VALUE)
                evidence.append("rejection_below_value_wick")

        # Liquidity sweeps.
        if _is_sweep(candles, "LOW"):
            secondary.append(MarketStateKind.LIQUIDITY_SWEEP_LOW)
            evidence.append("liquidity_sweep_low")
        elif _is_sweep(candles, "HIGH"):
            secondary.append(MarketStateKind.LIQUIDITY_SWEEP_HIGH)
            evidence.append("liquidity_sweep_high")

        # Exhaustion heuristic: large range candle with tiny body, high-low wick.
        body = abs(last.close - last.open)
        total = last.high - last.low
        if total > 0 and (body / total) < 0.15 and vol_ratio >= 1.3:
            secondary.append(MarketStateKind.EXHAUSTION)
            evidence.append("exhaustion_pin_bar")

        # Conflicts.
        if bullish and bearish or (bullish and lh) or (bearish and hl):
            conflicts.append("mixed_structure")

        deduped = []
        for item in secondary:
            if item not in deduped:
                deduped.append(item)

        confidence = Decimal("0.75")
        if conflicts:
            confidence = confidence * Decimal("0.6")
        confidence = confidence * Decimal(str(max(0.5, min(1.0, len(candles) / 50))))

        invalidation: list[str] = []
        if primary in {MarketStateKind.TREND_UP, MarketStateKind.BREAKOUT_ATTEMPT}:
            invalidation.append("close_below_last_low")
        elif primary in {MarketStateKind.TREND_DOWN, MarketStateKind.BREAKDOWN_ATTEMPT}:
            invalidation.append("close_above_last_high")

        missing_data: list[str] = []
        if len(candles) < 50:
            missing_data.append("volume_profile_history")

        return MarketStateModel(
            primary=primary,
            secondary=tuple(deduped),
            evidence=tuple(evidence),
            conflicts=tuple(conflicts),
            confidence=confidence,
            missing_data=tuple(missing_data),
            invalidation_conditions=tuple(invalidation),
        )


class AuctionStateEngine:
    """Auction Market Theory classification from candlestick structure."""

    def evaluate(self, candles: Sequence[Candle], market_state: MarketStateModel | None = None) -> AuctionStateModel:
        if len(candles) < 2:
            return AuctionStateModel(
                primary=AuctionStateKind.BALANCE,
                secondary=(),
                evidence=("insufficient_length",),
                confidence=Decimal("0.2"),
            )

        evidence: list[str] = []
        secondary_auction: list[AuctionStateKind] = []
        last = candles[-1]
        prev = candles[-2]
        body = abs(last.close - last.open)
        total = last.high - last.low
        upper_wick = last.high - max(last.open, last.close)
        lower_wick = min(last.open, last.close) - last.low

        primary: AuctionStateKind = AuctionStateKind.BALANCE

        if total > 0:
            if (body / total) > 0.7:
                primary = AuctionStateKind.INITIATIVE_ACTIVITY
                evidence.append(f"initiative_body_ratio({body / total:.2f})")
            elif lower_wick > body and lower_wick > total * 0.5:
                primary = AuctionStateKind.REJECTION
                evidence.append("lower_wick_rejection")
            elif upper_wick > body and upper_wick > total * 0.5:
                primary = AuctionStateKind.REJECTION
                evidence.append("upper_wick_rejection")
            else:
                primary = AuctionStateKind.BALANCE
                evidence.append("balanced_auction")

        # Range extension.
        bodies = [abs(c.close - c.open) for c in candles[-6:]]
        if bodies and pstdev(bodies) > 0 and len(bodies) >= 3:
            last_three = bodies[-3:]
            first_three = bodies[:-3]
            if last_three and first_three and (mean(last_three) / mean(first_three)) > 1.5:
                secondary_auction.append(AuctionStateKind.RANGE_EXTENSION)
                evidence.append("range_extension")

        # Value migration direction inference from market state.
        if market_state is not None:
            if market_state.primary in {MarketStateKind.TREND_UP, MarketStateKind.ACCEPTANCE_ABOVE_VALUE, MarketStateKind.BREAKOUT_ATTEMPT}:
                secondary_auction.append(AuctionStateKind.VALUE_MIGRATION)
                evidence.append("value_migration_up_hypothesis")
            elif market_state.primary in {MarketStateKind.TREND_DOWN, MarketStateKind.ACCEPTANCE_BELOW_VALUE, MarketStateKind.BREAKDOWN_ATTEMPT}:
                secondary_auction.append(AuctionStateKind.VALUE_MIGRATION)
                evidence.append("value_migration_down_hypothesis")
            if market_state.primary in {MarketStateKind.FAILED_AUCTION_HIGH, MarketStateKind.FAILED_AUCTION_LOW}:
                secondary_auction.append(AuctionStateKind.FAILED_AUCTION)
                evidence.append("failed_auction_hypothesis")

        deduped = []
        for item in secondary_auction:
            if item not in deduped:
                deduped.append(item)

        confidence = Decimal("0.7")
        if market_state is not None:
            confidence = confidence * market_state.confidence

        return AuctionStateModel(primary=primary, secondary=tuple(deduped), evidence=tuple(evidence), confidence=confidence)