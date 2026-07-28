from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from src.models.market_data import Observation, ObservationKind
from src.research.case_engine import ResearchCase


@dataclass(frozen=True, slots=True)
class ShortTermReport:
    generated_at: datetime
    symbol: str
    timeframe: str
    observed_structure: tuple[str, ...]
    evidence: tuple[str, ...]
    conflicts: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    summary: str
    mode: str = "OBSERVE"
    limitation: str = "Explanation only; no signal, recommendation, or autonomous action."


class ShortTermAssistant:
    def explain(self, observations: Iterable[Observation], research_case: ResearchCase | None = None) -> ShortTermReport:
        items = sorted(observations, key=lambda item: (item.observed_at, str(item.observation_id)))
        if not items:
            return ShortTermReport(datetime.now(timezone.utc), "UNKNOWN", "UNKNOWN", (), (), (), ("market_observations",), "No deterministic short-term observations are available.")
        kinds = tuple(dict.fromkeys(item.kind.value for item in items))
        bullish = ObservationKind.BOS_BULLISH.value in kinds
        bearish = ObservationKind.BOS_BEARISH.value in kinds
        conflicts = ("bullish_and_bearish_structure_present",) if bullish and bearish else ()
        evidence = tuple(str(item.observation_id) for item in items)
        missing = tuple(research_case.missing_evidence) if research_case else ("research_case_context",)
        summary = f"{len(items)} deterministic observation(s): {', '.join(kinds)}."
        return ShortTermReport(datetime.now(timezone.utc), items[-1].symbol, items[-1].timeframe, kinds, evidence, conflicts, missing, summary)
