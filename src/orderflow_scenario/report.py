"""Natural-language report generation.

Generates a readable, ordered report alongside the structured JSON schema.
The report is derived deterministically from the analysis objects and makes no
independent claims.
"""

from __future__ import annotations

from typing import Any

from .domain import AnalysisOutput, ConfirmationState, DecisionStatus, Scenario

SENSITIVE_WORDS = ("key", "secret", "token", "password", "credential", "authorization")


def _scenario_status_line(scenario: Scenario) -> str:
    state = scenario.state.value
    line = f"SZENARIO {scenario.scenario_id}: {scenario.scenario_type.value} ({scenario.direction.value}). Status: {state}."
    if scenario.state == ConfirmationState.CONFIRMED:
        line += " Bestätigt."
    elif scenario.state == ConfirmationState.INVALIDATED:
        line += " Invalidiert."
    elif scenario.state == ConfirmationState.EXPIRED:
        line += " Abgelaufen."
    else:
        pending = scenario.confirmation.mandatory_pending if scenario.confirmation else scenario.mandatory_confirmations
        if pending:
            line += f" Bestätigung fehlt: {'; '.join(pending[:2])}."
    return line


def build_report(analysis: AnalysisOutput) -> str:
    sections: list[str] = []
    sections.append("MARKTSTATUS:")
    sections.append(f"  {analysis.market_state.primary.value} (Nebenzustände: {', '.join(s.value for s in analysis.market_state.secondary) or 'keine'}).")
    sections.append("  Auktion: " + analysis.auction_state.primary.value + ".")

    sections.append("\nORDERFLOW:")
    sections.append(f"  Aggressive Seite: {analysis.orderflow.aggressive_side}.")
    sections.append(f"  Preisreaktion: {analysis.orderflow.price_response}.")
    if analysis.orderflow.absorption_hypothesis:
        sections.append(f"  Absorption-Hypothese: {analysis.orderflow.absorption_hypothesis}.")
    if analysis.orderflow.open_interest_interpretation:
        sections.append(f"  Open Interest: {analysis.orderflow.open_interest_interpretation}.")

    sections.append("\nDatenqualität:")
    sections.append(f"  {analysis.data_quality.status} (Confidence {analysis.data_quality.confidence}).")

    for scenario in analysis.scenarios:
        sections.append("\n" + _scenario_status_line(scenario))

    explanation = next((item["result"] for item in analysis.audit.get("engines", []) if item.get("engine") == "setup_explanation"), None)
    if explanation:
        facts = explanation["facts"]
        sections.append("\nEVIDENZKETTE:")
        sections.append("  Support: " + (", ".join(f"{k}={v}" for k, v in facts["supports"].items()) or "nicht vorhanden") + ".")
        sections.append("  Resistance: " + (", ".join(f"{k}={v}" for k, v in facts["resistances"].items()) or "nicht vorhanden") + ".")
        sections.append("  Fibonacci: " + (", ".join(f"{k}={v}" for k, v in facts["fibonacci_retracements"].items()) or "nicht berechenbar") + ".")
        sections.append("  Absorption: " + facts["absorption_status"] + ".")
        missing = explanation["missing_evidence"]
        if missing:
            sections.append("  Fehlende Belege: " + ", ".join(missing) + ".")

    decision = analysis.decision
    sections.append("\nENTSCHEIDUNG:")
    if decision.status == DecisionStatus.NO_TRADE:
        sections.append("  NO TRADE.")
        if decision.reason_codes:
            sections.append("  Gründe: " + ", ".join(decision.reason_codes) + ".")
        if decision.missing_confirmations:
            sections.append("  Fehlende Bestätigungen: " + ", ".join(decision.missing_confirmations) + ".")
    else:
        plan = decision.trade_plan
        if plan is not None:
            sections.append(
                f"  Trade-Plan {plan.trade_id}: {plan.direction.value} {plan.symbol}. "
                f"Entry {plan.entry_zone_low}..{plan.entry_zone_high}, Stop {plan.stop_loss}. "
                f"Risiko {plan.account_risk*100:.2f}% Kontorisiko, Hebel {plan.leverage}."
            )

    sections.append("\nNÄCHSTE BEOBACHTUNG:")
    for item in decision.next_observation:
        sections.append(f"  - {item}")

    sections.append("\nBetriebsmodus: " + analysis.mode.value + ". Keine Live-Order-Ausführung.")
    return "\n".join(sections)


def report_is_safe(text: str) -> bool:
    lowered = text.lower()
    return not any(word in lowered for word in SENSITIVE_WORDS)
