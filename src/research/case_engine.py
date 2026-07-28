from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from src.models.market_data import Observation, ObservationKind


@dataclass(slots=True)
class ResearchCase:
    case_id: str
    symbol: str
    timeframe: str
    opened_at: datetime
    updated_at: datetime
    status: str = "OPEN"
    observation_ids: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    outcome: str | None = None
    rule_versions: dict[str, str] = field(default_factory=dict)
    documentation: str = "Research container only; not a setup, signal, or prediction."

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "symbol": self.symbol, "timeframe": self.timeframe, "opened_at": self.opened_at.isoformat(), "updated_at": self.updated_at.isoformat(), "status": self.status, "observation_ids": self.observation_ids, "evidence": self.evidence, "missing_evidence": self.missing_evidence, "outcome": self.outcome, "rule_versions": self.rule_versions, "documentation": self.documentation}


class ResearchCaseEngine:
    def __init__(self, case_window: timedelta = timedelta(minutes=30)) -> None:
        self.case_window = case_window
        self.cases: dict[str, ResearchCase] = {}

    def ingest(self, observation: Observation) -> ResearchCase:
        window = int(observation.observed_at.timestamp() // self.case_window.total_seconds())
        identity = f"{observation.symbol}:{observation.timeframe}:{window}"
        case_id = "case_" + hashlib.sha256(identity.encode()).hexdigest()[:16]
        case = self.cases.get(case_id)
        if case is None:
            case = ResearchCase(case_id, observation.symbol, observation.timeframe, observation.observed_at, observation.observed_at)
            self.cases[case_id] = case
        oid = str(observation.observation_id)
        if oid not in case.observation_ids:
            case.observation_ids.append(oid)
            case.evidence.append({"observation_id": oid, "kind": observation.kind.value, "observed_at": observation.observed_at.isoformat(), "input_hash": observation.input_hash, "provenance": observation.provenance})
            case.rule_versions[observation.rule_id] = observation.rule_version
            case.updated_at = max(case.updated_at, observation.observed_at)
        case.missing_evidence = self._missing(case)
        return case

    @staticmethod
    def _missing(case: ResearchCase) -> list[str]:
        kinds = {item["kind"] for item in case.evidence}
        missing = []
        if not ({ObservationKind.BOS_BULLISH.value, ObservationKind.BOS_BEARISH.value} & kinds):
            missing.append("structure_confirmation")
        if ObservationKind.REJECTION.value not in kinds:
            missing.append("level_reaction_context")
        if not ({ObservationKind.WEAK_CONTINUATION.value, ObservationKind.FAILED_CONTINUATION.value} & kinds):
            missing.append("continuation_context")
        return missing

    def close(self, case_id: str, outcome: str, observed_at: datetime) -> ResearchCase:
        case = self.cases[case_id]
        if case.status != "OPEN" or observed_at < case.updated_at:
            raise ValueError("Invalid research-case closure")
        case.status, case.outcome, case.updated_at = "CLOSED", outcome, observed_at
        return case
