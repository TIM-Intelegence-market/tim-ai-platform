from datetime import datetime, timedelta, timezone

from src.analysis.bronxc_rules import BroncxRules
from src.models.market_data import Candle, ObservationKind


def make(index: int, open_: float, high: float, low: float, close: float, volume: float) -> Candle:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index)
    return Candle("BTCUSDT", "1m", start, start + timedelta(minutes=1), open_, high, low, close, volume, 10)


def test_rejection_and_absorption_are_evidence_based() -> None:
    candles = [make(i, 100, 102, 98, 101, 10) for i in range(5)]
    candles.append(make(5, 100, 106, 99, 100.2, 20))
    observations = BroncxRules().evaluate(candles)
    kinds = {item.kind for item in observations}
    assert ObservationKind.REJECTION in kinds
    assert ObservationKind.ABSORPTION_CONTEXT in kinds
    assert all(item.source == "deterministic_rules" for item in observations)


def test_rules_require_closed_history() -> None:
    candles = [make(i, 100, 102, 98, 101, 10) for i in range(5)]
    assert BroncxRules().evaluate(candles) == []
