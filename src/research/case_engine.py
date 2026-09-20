from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable

from src.models.market_data import Observation, ObservationKind


MISSING_REASONS = (
    "Outcome horizon not closed",
    "Gap überlappt Case",
    "zu wenige Observations",
    "Rule Version fehlt",
    "Replay nicht abgeschlossen",
    "Control/Negative Evidence fehlt",
    "Data Quality unter Schwelle",
    "Manual Review pending",
)

# Forward-only lifecycle. Terminal: CLOSED. QUARANTINED is terminal for
# defective observations (never delete, always explain).
_TRANSITIONS = {
    "OPEN": ("COLLECTING_EVIDENCE", "QUARANTINED"),
    "COLLECTING_EVIDENCE": ("READY_FOR_REVIEW", "QUARANTINED"),
    "READY_FOR_REVIEW": ("CONFIRMED", "REJECTED", "QUARANTINED"),
    "CONFIRMED": ("CLOSED",),
    "REJECTED": ("CLOSED",),
    "QUARANTINED": (),
    "CLOSED": (),
    # Legacy states remain readable; new transitions do not originate here.
    "MONITORING": ("COLLECTING_EVIDENCE", "QUARANTINED"),
    "INVALIDATED": ("CLOSED",),
}


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
    review_history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"case_id": self.case_id, "symbol": self.symbol, "timeframe": self.timeframe, "opened_at": self.opened_at.isoformat(), "updated_at": self.updated_at.isoformat(), "status": self.status, "observation_ids": self.observation_ids, "evidence": self.evidence, "missing_evidence": self.missing_evidence, "outcome": self.outcome, "rule_versions": self.rule_versions, "documentation": self.documentation, "review_history": self.review_history}


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

    def transition(self, case_id: str, to_status: str, observed_at: datetime, reason: str) -> ResearchCase:
        """Forward-only lifecycle transition with recorded justification."""
        case = self.cases[case_id]
        allowed = _TRANSITIONS.get(case.status, ())
        if to_status not in allowed or observed_at < case.updated_at:
            raise ValueError(f"Invalid transition {case.status} -> {to_status}")
        if not reason:
            raise ValueError("Transition requires a reason")
        case.status = to_status
        case.updated_at = observed_at
        case.review_history.append({"at": observed_at.isoformat(), "to": to_status, "reason": reason})
        return case

    def confirm(self, case_id: str, observed_at: datetime, reviewer: str) -> ResearchCase:
        """CONFIRMED only with full scientific criteria; else ValueError
        naming the first unmet criterion (never silently confirm)."""
        case = self.cases[case_id]
        if case.missing_evidence:
            raise ValueError(f"Cannot confirm: missing {case.missing_evidence[0]}")
        if not case.outcome:
            raise ValueError("Cannot confirm: Outcome horizon not closed")
        if not case.rule_versions:
            raise ValueError("Cannot confirm: Rule Version fehlt")
        if case.status != "READY_FOR_REVIEW":
            raise ValueError(f"Cannot confirm from status {case.status}: Manual Review pending")
        if not reviewer:
            raise ValueError("Cannot confirm: reviewer required")
        return self.transition(case_id, "CONFIRMED", observed_at, f"reviewer={reviewer}; criteria complete")

    def quarantine(self, case_id: str, observed_at: datetime, reason: str) -> ResearchCase:
        """Defective observations are quarantined, never deleted."""
        return self.transition(case_id, "QUARANTINED", observed_at, reason)
