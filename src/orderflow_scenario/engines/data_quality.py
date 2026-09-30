"""Data Quality Gate.

Deterministic checks that classify whether the analysis inputs are usable.
The gate never invents data: any field that is missing or unreadable is
reported and lowers confidence. When the inputs are insufficient, the gate
returns `INSUFFICIENT_DATA` and the pipeline must stop with NO_TRADE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Iterable, Sequence

from src.models.market_data import Candle, Trade

from ..domain import DataQualityReport, utc_now

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class DataQualityInputs:
    candles: Sequence[Candle]
    trades: Sequence[Trade] | None = None
    open_interest: Sequence[tuple[datetime, float]] | None = None
    price_now: float | None = None
    price_timestamp: datetime | None = None
    structured: bool = True
    screenshot_confidence: float | None = None
    estimated_prices: tuple[str, ...] = ()
    venue_mixed: bool = False
    delta_definition_verified: bool = True
    open_interest_venue_aggregated: bool = False
    time_unit_verified: bool = True
    spot_futures_separated: bool = True
    instrument: str | None = None
    source_name: str = "UNKNOWN"
    data_latency_seconds: float | None = None
    extra_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.price_now is not None and self.price_now <= 0:
            raise ValueError("price_now must be positive")
        if self.screenshot_confidence is not None and not (0 <= self.screenshot_confidence <= 1):
            raise ValueError("screenshot_confidence must be within [0,1]")
        if self.data_latency_seconds is not None and self.data_latency_seconds < 0:
            raise ValueError("data_latency_seconds cannot be negative")


class DataQualityGate:
    def __init__(self, max_price_age_seconds: float = 90.0, min_candles: int = 20) -> None:
        if max_price_age_seconds <= 0 or min_candles < 1:
            raise ValueError("invalid gate parameters")
        self.max_price_age_seconds = max_price_age_seconds
        self.min_candles = min_candles

    def evaluate(self, inputs: DataQualityInputs, observed_at: datetime | None = None) -> DataQualityReport:
        observed_at = observed_at or utc_now()
        missing: list[str] = []
        estimated: list[str] = list(inputs.estimated_prices)
        problems: list[str] = []

        if len(inputs.candles) < self.min_candles:
            missing.append(f"candles(<{self.min_candles})")
        bad_timestamps = [candle for candle in inputs.candles if candle.open_time.tzinfo is None]
        if bad_timestamps:
            missing.append("naive_candle_timestamps")
        if not inputs.trades:
            missing.append("trades")
        elif any(trade.event_time.tzinfo is None for trade in inputs.trades):
            missing.append("naive_trade_timestamps")
        if inputs.price_now is None:
            missing.append("price_now")
        if inputs.price_timestamp is not None:
            if observed_at.tzinfo is not None and inputs.price_timestamp.tzinfo is not None:
                age = (observed_at - inputs.price_timestamp).total_seconds()
                if age > self.max_price_age_seconds:
                    problems.append(f"stale_price({int(age)}s)")
        if inputs.venue_mixed:
            problems.append("mixed_venues")
        if not inputs.delta_definition_verified:
            problems.append("delta_definition_unverified")
        if not inputs.time_unit_verified:
            problems.append("time_unit_unverified")
        if not inputs.spot_futures_separated:
            problems.append("spot_futures_not_separated")
        if inputs.structured is False:
            problems.append("screenshot_based_data")
            if inputs.screenshot_confidence is not None:
                if inputs.screenshot_confidence < 0.6:
                    problems.append("screenshot_confidence_too_low")
                estimated.append("prices_from_screenshot")
        if inputs.extra_notes:
            problems.extend(inputs.extra_notes)
        if inputs.open_interest is not None and inputs.open_interest_venue_aggregated:
            estimated.append("open_interest_aggregated")
        if inputs.data_latency_seconds is not None and inputs.data_latency_seconds > self.max_price_age_seconds:
            problems.append(f"latency({int(inputs.data_latency_seconds)}s)")

        penalty = Decimal(len(missing)) * Decimal("0.12") + Decimal(len(problems)) * Decimal("0.08") + Decimal(len(estimated)) * Decimal("0.02")
        base = Decimal("0.9")
        confidence = max(ZERO, min(Decimal("1"), base - penalty))
        if not inputs.structured:
            confidence = confidence * Decimal("0.7")
        if not inputs.trades:
            confidence = confidence * Decimal("0.5")

        status = "PASS"
        # Without a price or without any candle there is nothing to analyse.
        if len(missing) >= 3 or (inputs.price_now is None) or not inputs.candles:
            status = "INSUFFICIENT_DATA"
        elif missing or problems:
            status = "PARTIAL"

        return DataQualityReport(status=status, confidence=confidence, missing_fields=tuple(sorted(missing)), estimated_fields=tuple(sorted(estimated)), problems=tuple(sorted(problems)))
