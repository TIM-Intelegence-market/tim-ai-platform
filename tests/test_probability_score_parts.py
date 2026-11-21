from decimal import Decimal
from types import SimpleNamespace as NS

from src.orderflow_scenario.engines.probability import ProbabilityEngine


def _item(direction="LONG", side="BUYERS", dq=None, hints=()):
    scenario = NS(direction=NS(value=direction), evidence_for=("a", "b"), evidence_against=("c",))
    of = NS(aggressive_side=side, absorption_confirmed=True, exhaustion_confirmed=False,
            open_interest_interpretation=None, positioning={"bias_hints": hints})
    return NS(scenario=scenario, market_state=NS(primary=NS(value="TREND_UP")), orderflow=of,
              data_quality_confidence=dq, empirical_hit_rate=None, historical_similarity=None)


def test_parts_add_up_to_score():
    score, parts = ProbabilityEngine()._score_parts(_item(hints=("with_long:funding",)))
    assert parts["positionierung"] == 0.03
    assert parts["basis"] == 0.30
    assert score == Decimal("0.30") + Decimal("0.12") + Decimal("0.08") + Decimal("0.08") - Decimal("0.05") + Decimal("0.06") + Decimal("0.03")


def test_data_quality_factor_scales_score_and_is_recorded():
    full, _ = ProbabilityEngine()._score_parts(_item())
    score, parts = ProbabilityEngine()._score_parts(_item(dq=Decimal("0.5")))
    assert parts["datenqualitaet_faktor"] == 0.75
    assert score == full * Decimal("0.75")
