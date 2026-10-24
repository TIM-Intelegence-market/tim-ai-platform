"""gex_regime observation: describes the gamma regime of one chain snapshot.

It is context, not a signal, forecast or trade setup.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.options_gamma.gex import GexProfile

RULE_ID = "gex_regime"
RULE_VERSION = "1.0.0"
PROVENANCE = "OPTIONS_CHAIN_SNAPSHOT_DETERMINISTIC"

_SUMMARIES = {
    "POSITIVE_GAMMA_REGIME": "Estimated dealer gamma is positive: hedging tends to dampen moves (range context).",
    "NEGATIVE_GAMMA_REGIME": "Estimated dealer gamma is negative: hedging tends to amplify moves (volatile context).",
    "NEUTRAL_GAMMA_REGIME": "Estimated dealer gamma is zero: no regime context.",
}


@dataclass(frozen=True, slots=True)
class GexObservation:
    observation_id: str
    kind: str
    symbol: str
    observed_at: datetime
    summary: str
    evidence: tuple[dict[str, Any], ...]
    rule_id: str
    rule_version: str
    input_hash: str
    provenance: str = PROVENANCE
    mode: str = "OBSERVE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "kind": self.kind,
            "symbol": self.symbol,
            "observed_at": self.observed_at.isoformat(),
            "summary": self.summary,
            "evidence": [dict(item) for item in self.evidence],
            "rule_id": self.rule_id,
            "rule_version": self.rule_version,
            "input_hash": self.input_hash,
            "provenance": self.provenance,
            "mode": self.mode,
        }


def _distance_pct(level: float | None, spot: float) -> float | None:
    return None if level is None else round((level - spot) / spot * 100, 4)


class GexObservationEngine:
    """Turns a GexProfile into one regime observation. Never scores or forecasts."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def evaluate(self, profile: GexProfile) -> list[GexObservation]:
        if not profile.strikes:
            return []
        kind = profile.regime + "_REGIME"
        evidence = (
            {"field": "net_gex_usd_per_1pct", "value": round(profile.net_gex, 2)},
            {"field": "spot", "value": profile.spot},
            {"field": "gamma_flip", "value": None if profile.gamma_flip is None else round(profile.gamma_flip, 2), "distance_pct": _distance_pct(profile.gamma_flip, profile.spot)},
            {"field": "call_wall", "value": profile.call_wall, "distance_pct": _distance_pct(profile.call_wall, profile.spot)},
            {"field": "put_wall", "value": profile.put_wall, "distance_pct": _distance_pct(profile.put_wall, profile.spot)},
            {"field": "assumption", "value": "dealers long calls, short puts; open interest hides real positioning"},
            {"field": "skipped_expired_quotes", "value": profile.skipped_expired},
        )
        payload = {"rule_id": RULE_ID, "rule_version": RULE_VERSION, "kind": kind, "input_hash": profile.input_hash}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        observation_id = "gexobs_" + digest[:24]
        if observation_id in self._seen:
            return []
        self._seen.add(observation_id)
        return [
            GexObservation(
                observation_id=observation_id,
                kind=kind,
                symbol=profile.symbol,
                observed_at=profile.as_of,
                summary=_SUMMARIES[kind],
                evidence=evidence,
                rule_id=RULE_ID,
                rule_version=RULE_VERSION,
                input_hash=profile.input_hash,
            )
        ]
