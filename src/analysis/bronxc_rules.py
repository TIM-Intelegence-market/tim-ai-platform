from __future__ import annotations

from statistics import mean
from typing import Sequence

from src.models.market_data import Candle, Observation, ObservationKind


class BroncxRules:
    """Small deterministic Week-1 observation rules; never emits trading instructions."""

    def evaluate(self, candles: Sequence[Candle]) -> list[Observation]:
        if len(candles) < 6 or not candles[-1].closed:
            return []
        current, previous = candles[-1], candles[-2]
        recent = candles[-6:-1]
        avg_range = mean(max(item.high - item.low, 1e-12) for item in recent)
        avg_volume = mean(item.volume for item in recent)
        body = abs(current.close - current.open)
        upper_wick = current.high - max(current.open, current.close)
        lower_wick = min(current.open, current.close) - current.low
        observations: list[Observation] = []
        if max(upper_wick, lower_wick) >= avg_range * 0.8 and body <= avg_range * 0.4:
            observations.append(self._make(current, ObservationKind.REJECTION, 65, {"upper_wick": upper_wick, "lower_wick": lower_wick, "average_range": avg_range}))
        broke_high = previous.high > max(item.high for item in candles[-6:-2])
        broke_low = previous.low < min(item.low for item in candles[-6:-2])
        if (broke_high and current.close < previous.high) or (broke_low and current.close > previous.low):
            observations.append(self._make(current, ObservationKind.FAILED_CONTINUATION, 70, {"previous_high": previous.high, "previous_low": previous.low, "current_close": current.close}))
        if body <= avg_range * 0.25 and current.volume >= avg_volume * 1.5:
            observations.append(self._make(current, ObservationKind.ABSORPTION_CONTEXT, 60, {"body": body, "volume": current.volume, "average_volume": avg_volume}))
        if body <= avg_range * 0.3 and current.volume <= avg_volume * 0.7:
            observations.append(self._make(current, ObservationKind.WEAK_CONTINUATION, 55, {"body": body, "volume": current.volume, "average_volume": avg_volume}))
        return observations

    @staticmethod
    def _make(candle: Candle, kind: ObservationKind, confidence: int, evidence: dict) -> Observation:
        return Observation(kind=kind, symbol=candle.symbol, timeframe=candle.timeframe, observed_at=candle.close_time, summary=f"Deterministic {kind.value.lower().replace('_', ' ')} context observed.", confidence=confidence, evidence=evidence)
