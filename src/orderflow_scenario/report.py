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

    external = next((item["result"] for item in analysis.audit.get("engines", []) if item.get("engine") == "external_context"), None)
    if external:
        sections.extend(_external_section(external))

    community = next((item["result"] for item in analysis.audit.get("engines", []) if item.get("engine") == "community_calls"), None)
    if community:
        sections.extend(_community_section(community))

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


_ALIGNMENT_TEXT = {
    "ALIGNED": "TIM-Szenarien stimmen überein",
    "CONFLICT": "Widerspruch zu TIMs Szenarien",
    "PARTIAL": "TIM hat Szenarien in beide Richtungen",
    "UNTESTED": "TIM hat kein Szenario zum Abgleich",
    "NO_BIAS": "keine Richtung erkennbar",
}


def _external_section(external: dict[str, Any]) -> list[str]:
    lines = ["\nBRONCX-LEITFADEN (extern, gewichtet, zählt nicht als Bestätigung):"]
    lines.extend(_influence_lines(external.get("influence")))
    active = [entry for entry in external["entries"] if entry["status"] == "ACTIVE"]
    if not active:
        stale = sum(1 for entry in external["entries"] if entry["status"] == "STALE")
        lines.append(f"  Kein aktueller Beitrag (Frist {external['max_age_hours']:g} h; {stale} veraltet).")
        return lines
    for entry in active:
        guidance = entry["guidance"]
        label = " ".join(part for part in (guidance["bias"] if guidance["bias"] != "NONE" else None, entry["symbol"], entry["timeframe"]) if part)
        if entry["renews"]:
            line = f"  [vor {entry['age_hours']:g} h] Broncx bestätigt seine vorherige Sicht erneut."
        elif entry["alignment"] == "NO_BIAS":
            line = f"  [vor {entry['age_hours']:g} h] {label or 'Beitrag'}: Kontext ohne Richtung."
        else:
            line = f"  [vor {entry['age_hours']:g} h] {label}: {_ALIGNMENT_TEXT[entry['alignment']]}."
            if entry["renewed_at"]:
                line += " Von Broncx erneut bestätigt."
        lines.append(line)
        for check in entry["invalidation_checks"]:
            text = check["text"] if report_is_safe(check["text"]) else "(siehe Audit)"
            lines.append(f"    Invalidierung laut Broncx: {text} -> {check['status']}.")
        if entry["level_checks"]:
            levels = ", ".join(
                f"{check['level']} {check['role']}" + (" aus Bild, geschätzt" if check.get("source") == "chart" else "") + f" {check['status']}"
                + (f" ({check['distance_pct']} %)" if check["distance_pct"] is not None else "")
                for check in entry["level_checks"]
            )
            lines.append(f"    Prüf-Level: {levels}.")
    return lines


_NO_INFLUENCE_TEXT = {
    "no_active_direction": "kein aktueller Beitrag mit Richtung",
    "mixed_direction": "sein neuester Beitrag nennt beide Richtungen",
    "invalidated": "seine Invalidierung ist ausgelöst",
}


def _community_section(community: dict[str, Any]) -> list[str]:
    lines = ["\nGOATHUB-COMMUNITY-CALLS (nur Anzeige, keine Gewichtung, zählt nicht als Bestätigung):"]
    if not community["entries"]:
        lines.append(f"  Kein guter Call zu diesem Symbol (Frist {community['max_age_hours']:g} h).")
        return lines
    for entry in community["entries"]:
        label = " ".join(part for part in (entry["bias"], entry["symbol"], entry["timeframe"]) if part)
        first = entry["text"].strip().splitlines()[0][:120] if entry["text"].strip() else ""
        quote = f"\"{first}\"" if first and report_is_safe(first) else "(Text siehe Audit)"
        lines.append(f"  [vor {entry['age_hours']:g} h] {entry['author']} [{entry['grade']}] {label}: {quote}")
        for level in entry["levels"]:
            lines.append(f"    {level['role']} {level['level']}: {level['status']}" + (f" ({level['distance_pct']} %)" if level["distance_pct"] is not None else ""))
        for item in entry["invalidation"]:
            text = f"\"{item['text']}\"" if report_is_safe(item["text"]) else "(siehe Audit)"
            lines.append(f"    Invalidierung {text}: {item['status']}")
    return lines


def _influence_lines(influence: dict[str, Any] | None) -> list[str]:
    if not influence:
        return []
    view = influence["view"]
    if not view["bias"]:
        return [f"  Keine Gewichtung: {_NO_INFLUENCE_TEXT.get(view['reason'], view['reason'])}."]
    lines = [f"  Gewichtung nach Broncx-Richtung {view['bias']}:"]
    for item in influence["score_adjustments"]:
        lines.append(f"    Szenario {item['scenario_id']} ({item['direction']}): Score {float(item['before']):.2f} -> {float(item['after']):.2f}.")
    if not influence["score_adjustments"]:
        lines.append("    Keine gerichteten Szenarien zu gewichten.")
    if influence["level_scenarios"]:
        lines.append(f"  Szenarien an Broncx-Leveln: {', '.join(influence['level_scenarios'])} (brauchen TIMs eigene Bestätigung).")
    return lines


def report_is_safe(text: str) -> bool:
    lowered = text.lower()
    return not any(word in lowered for word in SENSITIVE_WORDS)
