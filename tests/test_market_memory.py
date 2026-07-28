from datetime import datetime, timedelta, timezone

from src.memory.market_memory import MarketMemory
from src.models.market_data import Observation, ObservationKind


def obs(minutes: int, kind: ObservationKind = ObservationKind.REJECTION) -> Observation:
    return Observation(kind, "BTCUSDT", "1m", datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minutes), "context", 60, {"level": 65000}, rule_id="bronxc", rule_version="1.0.0", input_hash=str(minutes))


def test_similarity_is_deterministic_and_excludes_future() -> None:
    old, query, future = obs(1), obs(2), obs(3)
    memory = MarketMemory((old, future))
    results = memory.similar(query)
    assert [item.observation.observation_id for item in results] == [old.observation_id]
    assert results[0].similarity == 1.0
    assert "kind:REJECTION" in results[0].shared_features


def test_memory_deduplicates_restart_records() -> None:
    item = obs(1)
    memory = MarketMemory((item,))
    assert not memory.remember(item)
    assert memory.size == 1
