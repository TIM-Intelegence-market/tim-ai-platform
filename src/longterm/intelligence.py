from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class LongTermSnapshot:
    observed_at: datetime
    btc_dominance: float | None
    total_market_change_30d: float | None
    sector_changes_30d: dict[str, float]
    macro_risk_state: str
    source_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LongTermContext:
    observed_at: datetime
    market_cycle_context: str
    dominance_context: str
    sector_leaders: tuple[str, ...]
    macro_context: str
    missing_evidence: tuple[str, ...]
    provenance: str = "DETERMINISTIC_LONG_TERM_CONTEXT"
    limitation: str = "Descriptive historical context only; not portfolio or trading advice."


class LongTermIntelligence:
    ALLOWED_MACRO = {"RISK_ON", "RISK_OFF", "MIXED", "UNKNOWN"}

    def evaluate(self, snapshot: LongTermSnapshot) -> LongTermContext:
        if snapshot.observed_at.tzinfo is None or snapshot.macro_risk_state not in self.ALLOWED_MACRO:
            raise ValueError("Invalid long-term snapshot")
        missing = []
        if snapshot.total_market_change_30d is None:missing.append("total_market_change_30d")
        if snapshot.btc_dominance is None:missing.append("btc_dominance")
        if not snapshot.sector_changes_30d:missing.append("sector_changes_30d")
        cycle = "UNAVAILABLE" if snapshot.total_market_change_30d is None else "EXPANDING" if snapshot.total_market_change_30d > 5 else "CONTRACTING" if snapshot.total_market_change_30d < -5 else "RANGE"
        dominance = "UNAVAILABLE" if snapshot.btc_dominance is None else "BTC_HIGH" if snapshot.btc_dominance >= 55 else "BTC_LOW" if snapshot.btc_dominance <= 45 else "BALANCED"
        leaders = tuple(name for name, _ in sorted(snapshot.sector_changes_30d.items(), key=lambda item: (-item[1], item[0]))[:3])
        return LongTermContext(snapshot.observed_at, cycle, dominance, leaders, snapshot.macro_risk_state, tuple(missing))
