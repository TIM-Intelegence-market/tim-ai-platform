"""Evidence-first explanation for non-executing setup proposals."""

from __future__ import annotations

from decimal import Decimal

from .domain import DataQualityReport, MarketState, OrderflowInterpretation, Scenario
from .engines.scenario_generator import LevelSet


def build_setup_explanation(
    levels: LevelSet,
    market_state: MarketState,
    orderflow: OrderflowInterpretation,
    data_quality: DataQualityReport,
    scenarios: tuple[Scenario, ...],
) -> dict[str, object]:
    """Return facts, hypotheses, and explicit data gaps without inventing proof."""
    supports = _levels(levels, ("range_low", "value_area_low", "session_low", "previous_day_low", "weekly_low", "point_of_control", "initial_balance_low", "poor_low"))
    resistances = _levels(levels, ("range_high", "value_area_high", "session_high", "previous_day_high", "weekly_high", "point_of_control", "initial_balance_high", "poor_high"))
    fibs = _fib_levels(levels.range_low, levels.range_high)
    absorption = "UNAVAILABLE"
    if orderflow.absorption_confirmed:
        absorption = f"CONFIRMED_{orderflow.absorption_hypothesis}"
    elif orderflow.absorption_hypothesis:
        absorption = f"HYPOTHESIS_{orderflow.absorption_hypothesis}"
    exhaustion = "UNAVAILABLE"
    if orderflow.exhaustion_confirmed:
        exhaustion = f"CONFIRMED_{orderflow.exhaustion_hypothesis}"
    elif orderflow.exhaustion_hypothesis:
        exhaustion = f"HYPOTHESIS_{orderflow.exhaustion_hypothesis}"

    missing = list(dict.fromkeys((*data_quality.missing_fields, *orderflow.missing_data, *market_state.missing_data)))
    if not fibs:
        missing.append("range_high_and_range_low_for_fibonacci")
    return {
        "facts": {
            "market_state": market_state.primary.value,
            "market_state_evidence": list(market_state.evidence),
            "market_state_conflicts": list(market_state.conflicts),
            "supports": supports,
            "resistances": resistances,
            "fibonacci_retracements": fibs,
            "absorption_status": absorption,
            "exhaustion_status": exhaustion,
            "orderflow_reaction": orderflow.reaction,
            "orderflow_price_response": orderflow.price_response,
        },
        "interpretations": {
            "scenario_evidence": [
                {"scenario_id": item.scenario_id, "for": list(item.evidence_for), "against": list(item.evidence_against), "mandatory": list(item.mandatory_confirmations), "invalidation": list(item.invalidation)}
                for item in scenarios
            ],
            "rule": "A setup is conditional until its mandatory confirmations are observed; no individual level, Fibonacci ratio, absorption or exhaustion hypothesis is proof by itself.",
        },
        "missing_evidence": missing,
    }


def _levels(levels: LevelSet, names: tuple[str, ...]) -> dict[str, str]:
    return {name: str(value) for name in names if (value := getattr(levels, name)) is not None}


def _fib_levels(low: Decimal | None, high: Decimal | None) -> dict[str, str]:
    if low is None or high is None or high <= low:
        return {}
    span = high - low
    return {str(ratio): str((high - span * ratio).quantize(Decimal("0.01"))) for ratio in (Decimal("0.382"), Decimal("0.5"), Decimal("0.618"), Decimal("0.786"))}
