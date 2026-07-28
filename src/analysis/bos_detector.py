from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.models.market_data import Candle, Observation, ObservationKind


@dataclass(frozen=True, slots=True)
class SwingPoint:
    index: int
    price: float
    kind: str


class BOSDetector:
    def __init__(self, pivot_width: int = 2, minimum_break_fraction: float = 0.0) -> None:
        if pivot_width < 1 or minimum_break_fraction < 0:
            raise ValueError("Invalid BOS parameters")
        self.pivot_width = pivot_width
        self.minimum_break_fraction = minimum_break_fraction

    def swing_points(self, candles: Sequence[Candle]) -> list[SwingPoint]:
        width, result = self.pivot_width, []
        for index in range(width, len(candles) - width):
            candle = candles[index]
            neighbours = candles[index - width:index] + candles[index + 1:index + width + 1]
            if all(candle.high > item.high for item in neighbours):
                result.append(SwingPoint(index, candle.high, "HIGH"))
            if all(candle.low < item.low for item in neighbours):
                result.append(SwingPoint(index, candle.low, "LOW"))
        return result

    def detect(self, candles: Sequence[Candle]) -> Observation | None:
        minimum = self.pivot_width * 2 + 2
        if len(candles) < minimum:
            return None
        current = candles[-1]
        if not current.closed:
            return None
        swings = self.swing_points(candles[:-1])
        highs = [point for point in swings if point.kind == "HIGH"]
        lows = [point for point in swings if point.kind == "LOW"]
        if highs:
            level = highs[-1].price * (1 + self.minimum_break_fraction)
            if candles[-2].close <= level < current.close:
                return self._observation(current, ObservationKind.BOS_BULLISH, highs[-1])
        if lows:
            level = lows[-1].price * (1 - self.minimum_break_fraction)
            if candles[-2].close >= level > current.close:
                return self._observation(current, ObservationKind.BOS_BEARISH, lows[-1])
        return None

    @staticmethod
    def _observation(candle: Candle, kind: ObservationKind, swing: SwingPoint) -> Observation:
        direction = "above" if kind is ObservationKind.BOS_BULLISH else "below"
        return Observation(kind=kind, symbol=candle.symbol, timeframe=candle.timeframe, observed_at=candle.close_time, summary=f"Closed candle moved {direction} confirmed swing {swing.kind.lower()} at {swing.price:.2f}.", confidence=75, evidence={"swing_price": swing.price, "swing_index": swing.index, "close": candle.close, "closed_candle": True})
