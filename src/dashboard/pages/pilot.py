"""Pilot view: what a coach or pilot customer may see.

Only allowlisted case fields are rendered (``PILOT_CASE_FIELDS``) plus the
verifiable export links and the RETROSPECTIVE summary. No operational,
health, runtime, path or event data. Served locally like the rest of the
dashboard (127.0.0.1); intended for screen sharing.
"""

from __future__ import annotations

import html
from typing import Any
from urllib.parse import quote

from src.dashboard.helpers import _case_status, _safe
from src.dashboard.layout import CSS
from src.dashboard.state import DashboardState
from src.research.case_export import DISCLAIMER
from src.research.retrospective import case_retrospective

PILOT_CASE_FIELDS = ("case_id", "symbol", "timeframe", "opened_at", "status", "outcome")
STATUS_LABELS = {
    "OPEN": "offen", "COLLECTING_EVIDENCE": "sammelt Belege", "READY_FOR_REVIEW": "zur Prüfung", "MONITORING": "in Beobachtung",
    "CONFIRMED": "bestätigt", "CLOSED": "abgeschlossen", "REJECTED": "verworfen", "INVALIDATED": "verworfen", "QUARANTINED": "in Quarantäne",
}


def _pilot_case(case: dict[str, Any], observations: list[dict[str, Any]], validations: list[dict[str, Any]]) -> str:
    view = {key: case.get(key) for key in PILOT_CASE_FIELDS}
    status = str(view["status"] or "").upper()
    href = html.escape("/exports/case/" + quote(str(view["case_id"] or ""), safe=""), quote=True)
    try:
        blocks = case_retrospective(case, observations, validations)
    except (KeyError, ValueError):
        blocks = []
    retro = "".join(
        f"<li>{_safe(block.get('observation_type'))}, n={_safe(block.get('sample_size'))}: "
        + (", ".join(f"{_safe(name)} {_safe(count)}" for name, count in (block.get("outcomes") or {}).items()) if block.get("outcomes") else "zu wenige vergleichbare Fälle")
        + "</li>"
        for block in blocks
    )
    retro_html = f"<p class='card__label'>Rückblick <span class='badge badge--snapshot'>RETROSPECTIVE</span></p><ul class='retro'>{retro}</ul>" if retro else ""
    return (
        "<article class='card pilot-case'>"
        f"<div class='panel__head'><span class='mono'>{_safe(view['case_id'])}</span>"
        f"<span class='badge badge--{_case_status(status)}'>{_safe(STATUS_LABELS.get(status, status))}</span></div>"
        f"<p class='card__note'>{_safe(view['symbol'])} · {_safe(view['timeframe'])} · eröffnet {_safe(view['opened_at'])}</p>"
        f"<p>Ergebnis: <b>{_safe(view['outcome'], 'offen')}</b> · Belege: {len(case.get('evidence') or [])}</p>"
        f"{retro_html}"
        f"<p><a class='tag' href='{href}.html' target='_blank' rel='noopener'>Beleg öffnen</a> <a class='tag' href='{href}.json'>JSON</a></p>"
        "</article>"
    )


def render_pilot(state: DashboardState) -> str:
    with state.lock:
        cases = [dict(item) for item in state.research_cases]
        observations = [dict(item) for item in state.orderflow_observations]
        validations = [dict(item) for item in state.orderflow_validations]
    cases.sort(key=lambda item: str(item.get("opened_at") or ""), reverse=True)
    items = "".join(_pilot_case(case, observations, validations) for case in cases) or "<p class='empty'>Noch keine Research-Fälle vorhanden.</p>"
    body = (
        "<div class='hero'><div><h1>TIM Research-Belege</h1>"
        "<p>Nachprüfbare Marktanalysen: jeder Fall mit Zeitstempel, verwendeten Daten und SHA-256-Fingerabdruck.</p></div>"
        "<div class='observe'>NUR LESEN</div></div>"
        "<section class='panel'><h2>Was ist ein Research-Beleg?</h2>"
        "<p>Ein Beleg hält fest, welche Beobachtungen zu einem Zeitpunkt vorlagen. Der Fingerabdruck (Hash) ändert sich, "
        "sobald auch nur ein Zeichen verändert wird. Die Beleg-Seite prüft das selbst im Browser.</p>"
        "<p>Als Zeitnachweis zählt, wann der Hash zuerst veröffentlicht wurde. Der Rückblick zählt nur vergangene, "
        "gleichartige Fälle, deren Ausgang zum Zeitpunkt des Falls bereits feststand.</p>"
        f"<p class='safety-callout'>{html.escape(DISCLAIMER)}</p></section>"
        f"<section class='panel'><h2>Research-Fälle</h2><div class='grid pilot-grid'>{items}</div></section>"
    )
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Research-Belege · TIM</title><style>{CSS}.pilot-grid{{grid-template-columns:repeat(auto-fill,minmax(320px,1fr))}}"
        "@media (max-width:760px){.pilot-grid{grid-template-columns:minmax(0,1fr)}}.retro{margin:4px 0 8px;padding-left:18px}</style></head>"
        "<body><header class='topbar'><div class='topbar__inner'><span class='brand'>TIM<small>TRANSPARENT INTELLIGENCE FOR MARKETS</small></span>"
        "<span class='tag'>Pilotansicht</span></div></header>"
        f"<main class='shell'>{body}</main></body></html>"
    )
