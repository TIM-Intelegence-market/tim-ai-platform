"""Discord-ready draft of TIM's current setup (text only, never posted by TIM).

The draft is derived from one finished analysis and claims nothing beyond it: a trade plan is shown
only when the decision engine produced one, otherwise the draft says that there is no setup and why.
Scenario scores are not shown (they are heuristic scores, not probabilities). A human reads the draft
and decides whether to post it.
"""

from __future__ import annotations

from .domain import AnalysisOutput, ConfirmationState, DecisionStatus
from .report import report_is_safe

__all__ = ["DISCLAIMER", "MAX_DRAFT_CHARS", "build_setup_draft"]

MAX_DRAFT_CHARS = 1900  # Discord allows 2000 characters per message
DISCLAIMER = "Forschungsentwurf von TIM, keine Anlageberatung und keine Handelsempfehlung. Keine Order wird ausgeführt."
_MAX_SCENARIOS = 3


def _safe(text: str) -> str:
    return text if report_is_safe(text) else "(Text siehe Audit)"


def _num(value: object) -> str:
    return format(value, "f") if hasattr(value, "quantize") else str(value)


def _scenario_lines(analysis: AnalysisOutput) -> list[str]:
    lines: list[str] = []
    active = [s for s in analysis.scenarios if s.state not in (ConfirmationState.EXPIRED, ConfirmationState.INVALIDATED)]
    for scenario in active[:_MAX_SCENARIOS]:
        pending = scenario.confirmation.mandatory_pending if scenario.confirmation else scenario.mandatory_confirmations
        label = "bestätigt" if scenario.state == ConfirmationState.CONFIRMED else "unbestätigt"
        line = f"- {scenario.scenario_type.value} ({scenario.direction.value}), {label}"
        if pending and scenario.state != ConfirmationState.CONFIRMED:
            line += f"; es fehlt: {_safe('; '.join(pending[:2]))}"
        if scenario.invalidation:
            line += f"; ungültig, wenn: {_safe(scenario.invalidation[0])}"
        lines.append(line)
    return lines


def build_setup_draft(analysis: AnalysisOutput) -> str:
    context = analysis.market_context
    decision = analysis.decision
    head = [
        f"**TIM · Setup-Entwurf · {context.symbol} {context.timeframe}**",
        f"Stand {analysis.timestamp.strftime('%Y-%m-%d %H:%M UTC')} · Datenqualität {analysis.data_quality.status}",
    ]
    body: list[str] = []
    plan = decision.trade_plan
    if decision.status == DecisionStatus.TRADE_PLAN and plan is not None:
        body.append(f"**Setup:** {plan.direction.value} {plan.symbol} ({plan.setup_name})")
        entry = f"{_num(plan.entry_zone_low)}..{_num(plan.entry_zone_high)}" if plan.entry_zone_low is not None and plan.entry_zone_high is not None else _num(plan.exact_entry)
        body.append(f"Einstieg {entry} · Stop {_num(plan.stop_loss)} · Ziele {_num(plan.target_1)} / {_num(plan.target_2)} / {_num(plan.target_3)}")
        body.append(f"Chance/Risiko {_num(plan.expected_reward_risk)} (Minimum {_num(plan.minimum_required_reward_risk)})")
        body.append(f"Ungültig, wenn: {_safe(plan.invalidation_logic)}")
        if plan.supporting_evidence:
            body.append("Dafür: " + _safe("; ".join(plan.supporting_evidence[:3])))
        if plan.conflicting_evidence:
            body.append("Dagegen: " + _safe("; ".join(plan.conflicting_evidence[:3])))
        if plan.conditions_still_missing:
            body.append("Noch offen: " + _safe("; ".join(plan.conditions_still_missing[:3])))
    else:
        body.append("**Kein Setup (NO TRADE).**")
        if decision.reason_codes:
            body.append("Gründe: " + ", ".join(decision.reason_codes))
        if decision.missing_confirmations:
            body.append("Fehlende Bestätigungen: " + _safe("; ".join(decision.missing_confirmations[:3])))
        scenarios = _scenario_lines(analysis)
        if scenarios:
            body.append("Beobachtet (noch kein Setup):")
            body.extend(scenarios)
    tail = ["", f"_{DISCLAIMER}_"]
    text = "\n".join(head + body)
    room = MAX_DRAFT_CHARS - len("\n".join(tail)) - 2
    if len(text) > room:
        text = text[: room - 1].rstrip() + "…"
    return text + "\n" + "\n".join(tail)
