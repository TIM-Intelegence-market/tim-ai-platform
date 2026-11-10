"""Bereich "TIM-KI (Hermes)" im Control Center: Status-Kacheln, Fragefeld und die letzten Antworten.

Liest ``src.dashboard.hermes_bridge``. Das Fragefeld schickt an ``POST /neu/hermes/ask``; die öffentliche
Ansicht (tim-online.online) ist nur lesend, dort zeigt die Seite Status und Verlauf ohne Feld.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.dashboard import hermes_bridge
from src.dashboard.cockpit.page import COCKPIT_CSP, _e, _grid, _head, local_time, page
from src.dashboard.cockpit.tiles import Tile, make_tile

SCHEMA = "tim_cockpit_hermes/1"
SAFETY = "Nur lesend über tim-ops und tim-graph, keine Order, keine Schlüssel"
HERMES_CSP = COCKPIT_CSP.replace("form-action 'none'", "form-action 'self'")
HREF = "/neu/hermes"


def tile(status: dict[str, Any] | None, now: datetime | None = None) -> Tile:
    """Eine Kachel für die Lage: installiert, Schlüssel, letzte Antwort."""
    now = now or datetime.now(timezone.utc)
    if not status:
        return make_tile("hermes", "TIM-KI (Hermes)", "—", state="unknown", reason="Hermes-Status nicht lesbar", href=HREF, now=now)
    model = status.get("model") or "Modell unbekannt"
    if not status.get("installed"):
        return make_tile("hermes", "TIM-KI (Hermes)", "nicht installiert", state="unknown",
                         reason="Hermes-CLI auf diesem Rechner nicht gefunden", source=str(status.get("home") or ""), href=HREF, now=now)
    if not status.get("key_present"):
        return make_tile("hermes", "TIM-KI (Hermes)", f"{model}, ohne Schlüssel", state="warn",
                         reason="DeepSeek-Schlüssel fehlt in ~/.hermes/.env (App „Hermes Schlüssel eintragen“)", href=HREF, now=now)
    last = status.get("last") or {}
    if last and not last.get("ok"):
        return make_tile("hermes", "TIM-KI (Hermes)", f"{model}, letzte Frage ohne Antwort", state="warn",
                         reason=str(last.get("error") or "unbekannter Fehler"), href=HREF, now=now, extra={"kind": "info"})
    value = f"{model}, {status.get('asked_today', 0)} Frage(n) heute" if last else f"{model}, bereit"
    detail = f"Letzte Antwort {local_time(last.get('at'))} Uhr in {last.get('seconds')} s" if last else "Noch keine Frage gestellt"
    return make_tile("hermes", "TIM-KI (Hermes)", value, state="ok", detail=detail, source="hermes_bridge", href=HREF, now=now,
                     extra={"kind": "info"})


def build_hermes(state: Any, now: datetime | None = None, token: str = "", asked: str | None = None, error: str | None = None,
                 can_ask: bool = True) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    log_path = getattr(state, "hermes_log_path", None)
    status = hermes_bridge.status(log_path, now)
    main = tile(status, now)
    tiles = [
        main,
        make_tile("hermes_model", "Modell", f"{status.get('provider') or '—'} / {status.get('model') or '—'}",
                  state="ok" if status.get("model") else "unknown", reason="" if status.get("model") else "config.yaml ohne Modell",
                  source="~/.hermes/config.yaml", now=now, extra={"kind": "info"}),
        make_tile("hermes_mcp", "TIM-Anbindung", ", ".join(status.get("mcp_servers") or []) or "keine MCP-Server",
                  state="ok" if status.get("mcp_servers") else "warn",
                  reason="" if status.get("mcp_servers") else "Hermes kennt tim-ops/tim-graph nicht", now=now, extra={"kind": "info"}),
    ]
    log = list(reversed(hermes_bridge.load_log(log_path)))
    report, opinions, critic = None, None, []
    try:
        from src.dashboard import daily_critic

        critic = daily_critic.latest(getattr(state, "daily_critic_path", None), 14)
    except Exception:  # noqa: BLE001, S110 - die Seite zeigt den Rest auch ohne die Kritik
        pass
    try:  # TIMs eigene Aufträge an Hermes; fehlt eine Datei, bleibt der Abschnitt leer
        from src.dashboard import daily_report, plan_opinion

        report = daily_report.latest(getattr(state, "daily_report_path", None))
        stored = plan_opinion.load(getattr(state, "plan_opinion_path", None) or plan_opinion.DEFAULT_PATH) or {}
        recent = sorted((p for p in (stored.get("plans") or {}).values() if p.get("opinion")),
                        key=lambda p: str(p.get("created_at")), reverse=True)[:5]
        opinions = {"summary": stored.get("summary") or plan_opinion.summary(stored), "recent": recent}
    except Exception:  # noqa: BLE001, S110 - die Seite zeigt Status und Verlauf auch ohne diese Abschnitte
        pass
    return {"report": report, "opinions": opinions, "critic": critic, "schema": SCHEMA, "generated_at": now.isoformat(), "safety": SAFETY, "overall": main.state, "headline": main.value,
            "status": {k: v for k, v in status.items() if k != "last"}, "tiles": [t.to_dict() for t in tiles], "log": log,
            "token": token, "asked": asked, "error": error, "can_ask": can_ask, "max_question": hermes_bridge.MAX_QUESTION}


def _report_section(report: dict[str, Any] | None) -> str:
    head = "<section aria-labelledby='h-report'><h2 id='h-report'>Tagesbericht</h2>"
    if not report:
        return head + "<p class='empty'>Noch kein Bericht. Der nächste kommt um 8 oder 22 Uhr.</p></section>"
    text = (f"<p style='white-space:pre-wrap'>{_e(report.get('text'))}</p>" if report.get("text")
            else f"<p class='note'>Hermes hat nicht geantwortet ({_e(report.get('error'))}); hier die Fakten.</p>")
    facts = "".join(f"<li>{_e(line)}</li>" for line in report.get("facts") or [])
    return (f"{head}{text}<details><summary>Fakten dazu</summary><ul>{facts}</ul></details>"
            f"<p class='note'>Stand {_e(local_time(report.get('at'), with_date=True))} Uhr. Nur Papier-Journale und Marktdaten.</p></section>")


def _critic_section(reports: list[dict[str, Any]] | None) -> str:
    head = "<section aria-labelledby='h-critic'><h2 id='h-critic'>Kritik</h2>"
    if not reports:
        return head + "<p class='empty'>Noch keine Kritik. Die erste kommt um 7 Uhr.</p></section>"

    def one(report: dict[str, Any]) -> str:
        text = (f"<p style='white-space:pre-wrap'>{_e(report.get('text'))}</p>" if report.get("text")
                else f"<p class='note'>Hermes hat nicht geantwortet ({_e(report.get('error'))}); hier die Fakten.</p>")
        facts = "".join(f"<li>{_e(line)}</li>" for line in report.get("facts") or [])
        return f"{text}<details><summary>Fakten dazu</summary><ul>{facts}</ul></details>"

    older = "".join(f"<details><summary>Kritik vom {_e(local_time(r.get('at'), with_date=True))} Uhr</summary>{one(r)}</details>"
                    for r in reports[1:])
    return (f"{head}{one(reports[0])}<p class='note'>Stand {_e(local_time(reports[0].get('at'), with_date=True))} Uhr. Projekt und Chart "
            f"aus Nutzersicht, nur lesend; Hermes sieht Zahlen und Überschriften, kein Bild und keinen Code.</p>{older}</section>")


def _opinion_section(opinions: dict[str, Any] | None) -> str:
    head = "<section aria-labelledby='h-opinion'><h2 id='h-opinion'>Zweitmeinung zu den Plänen</h2>"
    summary = (opinions or {}).get("summary") or {}
    recent = (opinions or {}).get("recent") or []
    if not recent:
        return head + "<p class='empty'>Noch keine Zweitmeinung. Sie entsteht beim nächsten 15m- oder 1h-Plan.</p></section>"
    items = []
    for plan in recent:
        opinion = plan.get("opinion") or {}
        result = (plan.get("journal") or {}).get("net_r")
        meta = f"{local_time(plan.get('created_at'), with_date=True)} Uhr" + (f", Ergebnis {float(result):+.2f} R" if result is not None else "")
        items.append(f"<li><p><b>{_e(plan.get('direction'))} {_e(plan.get('timeframe'))}</b>, Urteil <b>{_e(opinion.get('verdict'))}</b></p>"
                     f"<p><b>Dafür:</b> {_e(opinion.get('pro') or '—')}</p><p><b>Dagegen:</b> {_e(opinion.get('contra') or '—')}</p>"
                     f"<p class='note'>{_e(meta)}</p></li>")
    rows = "; ".join(f"{_e(name)}: {row.get('n')} Pläne, {float(row.get('sum_net_r') or 0):+.2f} R"
                     for name, row in (summary.get("by_verdict") or {}).items()) or "noch kein geschlossener Plan"
    return (f"{head}<p class='note'>Nur Kommentar, kein Eingriff. {summary.get('closed', 0)} von {summary.get('target', 30)} "
            f"geschlossenen Plänen für das Urteil. Bisher: {rows}.</p>"
            f"<ul class='hermes-log' style='list-style:none;padding:0'>{''.join(items)}</ul></section>")


def hermes_body(model: dict[str, Any]) -> str:
    out = [_head("TIM-KI (Hermes)", model, model.get("overall"), str(model.get("headline") or "")), _grid(model.get("tiles") or [])]
    if model.get("error"):
        out.append(f"<div class='need'><ul><li><b class='s-warn'>Hinweis</b><span>{_e(model['error'])}</span></li></ul></div>")
    if model.get("can_ask"):
        out.append(
            "<section aria-labelledby='h-ask'><h2 id='h-ask'>Hermes fragen</h2>"
            f"<form method='post' action='/neu/hermes/ask' class='hermes-form'><input type='hidden' name='token' value='{_e(model.get('token'))}'>"
            f"<textarea name='question' rows='3' maxlength='{int(model.get('max_question') or 500)}' required "
            "placeholder='z. B. Wie ist die Orderflow-Lage gerade?' style='width:100%;box-sizing:border-box'></textarea>"
            "<p><button type='submit'>Fragen</button> <span class='note'>Antwort dauert meist 10–30 s; die Seite lädt danach neu.</span></p></form>"
            "</section>")
    else:
        out.append("<p class='note'>Fragen stellen geht nur direkt am Mac; die öffentliche Ansicht ist nur lesend.</p>")
    out.append(_report_section(model.get("report")))
    out.append(_critic_section(model.get("critic")))
    out.append(_opinion_section(model.get("opinions")))
    items = []
    for entry in (model.get("log") or [])[:10]:
        mark = " class='hermes-new'" if model.get("asked") and entry.get("id") == model.get("asked") else ""
        body = _e(entry.get("answer")) if entry.get("ok") else f"<span class='s-warn'>{_e(entry.get('error') or 'keine Antwort')}</span>"
        meta = f"{local_time(entry.get('at'))} Uhr" + (f", {entry.get('seconds')} s" if entry.get("seconds") is not None else "")
        items.append(f"<li{mark}><p><b>Du:</b> {_e(entry.get('question'))}</p><p style='white-space:pre-wrap'><b>Hermes:</b> {body}</p>"
                     f"<p class='note'>{_e(meta)}</p></li>")
    log_html = "<ul class='hermes-log' style='list-style:none;padding:0'>" + "".join(items) + "</ul>" if items else "<p class='empty'>Noch keine Fragen.</p>"
    out.append(f"<section aria-labelledby='h-log'><h2 id='h-log'>Letzte Antworten</h2>{log_html}</section>")
    out.append("<p class='note'>Hermes liest TIM nur über tim-ops und tim-graph. Er handelt nicht, sieht keine Schlüssel und ändert nichts.</p>")
    return "".join(out)


def render_hermes(model: dict[str, Any]) -> str:
    return page("TIM-KI (Hermes)", "hermes", hermes_body(model), refresh=False)
