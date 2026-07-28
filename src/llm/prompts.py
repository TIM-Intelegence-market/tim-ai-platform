from __future__ import annotations

import json

from src.models.market_data import Observation

SYSTEM_POLICY = """You are TIM's explanation layer. Explain only the supplied deterministic observations.
Return JSON with summary, evidence, uncertainty, and missing_context. Never create setups, signals, entries,
exits, targets, stops, orders, position sizes, or recommendations. Do not claim profitability."""


def observation_prompt(observation: Observation) -> str:
    return SYSTEM_POLICY + "\nObservation:\n" + json.dumps(observation.to_dict(), sort_keys=True)
