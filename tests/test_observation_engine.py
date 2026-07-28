from datetime import datetime, timedelta, timezone

from src.models.market_data import Candle
from src.observation.engine import ObservationEngine


def _candles() -> list[Candle]:
    values = [(100, 100, 95, 98), (98, 105, 97, 102), (102, 110, 98, 104), (104, 106, 99, 103), (103, 104, 98, 102), (102, 109, 101, 109), (109, 113, 108, 112)]
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [Candle("BTCUSDT", "1m", start + timedelta(minutes=i), start + timedelta(minutes=i + 1), open_, high, low, close, 10, 10) for i, (open_, high, low, close) in enumerate(values)]


def test_engine_versions_provenance_and_deduplicates() -> None:
    engine = ObservationEngine()
    first = engine.evaluate(_candles())
    assert first
    assert all(item.observation_version == 1 for item in first)
    assert all(item.rule_version == "1.0.0" for item in first)
    assert all(item.input_hash for item in first)
    assert all(item.provenance == "PUBLIC_MARKET_DATA_DETERMINISTIC" for item in first)
    assert engine.evaluate(_candles()) == []


def test_stable_ids_survive_new_engine() -> None:
    left = ObservationEngine().evaluate(_candles())
    right = ObservationEngine().evaluate(_candles())
    assert [item.observation_id for item in left] == [item.observation_id for item in right]
