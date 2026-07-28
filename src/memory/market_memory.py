from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from src.models.market_data import Observation


def _features(observation: Observation) -> set[str]:
    evidence_keys = {f"evidence:{key}" for key in observation.evidence}
    return {f"kind:{observation.kind.value}", f"symbol:{observation.symbol}", f"timeframe:{observation.timeframe}", f"rule:{observation.rule_id}:{observation.rule_version}", *evidence_keys}


@dataclass(frozen=True, slots=True)
class SimilarObservation:
    observation: Observation
    similarity: float
    shared_features: tuple[str, ...]


class MarketMemory:
    """Deterministic historical memory. Similarity is Jaccard overlap, not a forecast."""

    def __init__(self, observations: Iterable[Observation] = ()) -> None:
        self._items: dict[str, Observation] = {str(item.observation_id): item for item in observations}

    def remember(self, observation: Observation) -> bool:
        key = str(observation.observation_id)
        if key in self._items:
            return False
        self._items[key] = observation
        return True

    def similar(self, query: Observation, limit: int = 10, minimum_similarity: float = 0.1) -> list[SimilarObservation]:
        query_features = _features(query)
        results = []
        for item in self._items.values():
            if item.observation_id == query.observation_id or item.observed_at > query.observed_at:
                continue
            features = _features(item)
            shared = query_features & features
            score = len(shared) / len(query_features | features)
            if score >= minimum_similarity:
                results.append(SimilarObservation(item, round(score, 6), tuple(sorted(shared))))
        return sorted(results, key=lambda item: (-item.similarity, -item.observation.observed_at.timestamp(), str(item.observation.observation_id)))[:limit]

    @property
    def size(self) -> int:
        return len(self._items)
