"""Trader journal page (/trader-journal): own paper trades behind Broncx' flowchart."""

from __future__ import annotations

import html

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.dashboard.chart_model import _fmt
from src.dashboard.helpers import _safe
from src.dashboard.layout import _content_security_policy_for, _hero, _layout, _strip_states
from src.dashboard.trader_journal import CONFLUENCES, DONE, GATE, NO_TRADE, REVIEW, summary

LOCAL = ZoneInfo("Europe/Berlin")
STATUS = {
    "OPEN": ("warn", "wartet auf Einstieg"), "FILLED": ("ok", "läuft"), "CLOSED": ("ok", "beendet"),
    "EXPIRED": ("unknown", "verfallen"), "CANCELLED": ("unknown", "zurückgezogen"), "NO_TRADE": ("fail", "kein Trade (Flussdiagramm)"),
}
REASON = {"STOP": "Stop", "TARGET": "Ziel", "TIMEOUT": "Zeitlimit"}
GATE_SHORT = {"in_plan": "nicht im Plan", "saw_setup": "Setup nicht gesehen", "timing": "Timing falsch", "rules": "Regel verletzt"}


def journal_csp(page: str) -> str:
    """The page's own CSP: no script at all, and forms may post to this origin only."""
    return _content_security_policy_for(page).replace("form-action 'none'", "form-action 'self'")


def _local(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(LOCAL).strftime("%d.%m. %H:%M")
    except ValueError:
        return "–"


def _value(form: Mapping[str, str], key: str) -> str:
    return html.escape(str(form.get(key, "")))  # not _safe: an empty field must stay empty


def _yes_no(name: str, form: Mapping[str, str]) -> str:
    picked = str(form.get(name, ""))
    return "".join(
        f"<label><input type='radio' name='{name}' value='{value}'{' checked' if picked == value else ''} required> {label}</label> "
        for value, label in (("ja", "Ja"), ("nein", "Nein"))
    )


def _entry_form(token: str, form: Mapping[str, str], context_line: str) -> str:
    direction = str(form.get("direction", ""))
    gate = "".join(f"<li><b>{_safe(question)}</b><br>{_yes_no(key, form)}</li>" for key, question in GATE)
    checks = "".join(
        f"<label><input type='checkbox' name='c_{key}' value='1'{' checked' if form.get(f'c_{key}') == '1' else ''}> {_safe(label)}</label>"
        for key, label in CONFLUENCES
    )
    return (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Vor dem Trade</p>"
        "<h2>Neuer Eintrag</h2><p class='cc-section__note'>Erst das Flussdiagramm, dann der Trade. Ein „Nein“ und der Eintrag wird als "
        "„kein Trade“ gebucht: das ist auch ein Ergebnis. TIM hängt seinen Kontext an und verfolgt den Trade auf 1m-Kerzen. Nur Papier.</p>"
        f"<p class='cc-note'>TIM jetzt: {_safe(context_line)}</p></div></div>"
        "<form method='post' action='/trader-journal/entry'>"
        f"<input type='hidden' name='token' value='{_safe(token)}'>"
        "<ol class='cc-list'>" + gate + "</ol>"
        "<div class='filters'>"
        "<div><label for='tj-direction'>Richtung</label><select id='tj-direction' name='direction' required>"
        f"<option value=''>wählen</option><option value='LONG'{' selected' if direction == 'LONG' else ''}>Long</option>"
        f"<option value='SHORT'{' selected' if direction == 'SHORT' else ''}>Short</option></select></div>"
        f"<div><label for='tj-entry'>Einstieg (Limit)</label><input id='tj-entry' name='entry' inputmode='decimal' required value='{_value(form, 'entry')}'></div>"
        f"<div><label for='tj-stop'>Stop</label><input id='tj-stop' name='stop' inputmode='decimal' required value='{_value(form, 'stop')}'></div>"
        f"<div><label for='tj-target'>Ziel</label><input id='tj-target' name='target' inputmode='decimal' required value='{_value(form, 'target')}'></div>"
        "</div>"
        "<div class='field'><label for='tj-thesis'>These: warum hier, was muss passieren?</label>"
        f"<textarea id='tj-thesis' name='thesis' rows='4' cols='80' maxlength='1000' required>{_value(form, 'thesis')}</textarea></div>"
        f"<p class='cc-note'>Konfluenzen</p><div class='filters'>{checks}</div>"
        "<p><button type='submit'>Eintrag speichern</button></p></form></section>"
    )


def _review_form(token: str, entry: Mapping[str, Any]) -> str:
    fields = []
    for key, question in REVIEW:
        if key == "again":
            fields.append(f"<div><label>{_safe(question)}</label>{_yes_no('again', {})}</div>")
        else:
            fields.append(f"<div><label for='rv-{_safe(entry['id'])}-{key}'>{_safe(question)}</label>"
                          f"<textarea id='rv-{_safe(entry['id'])}-{key}' name='{key}' rows='2' maxlength='1000' required></textarea></div>")
    return (
        f"<details><summary>Rückblick zu {_safe(entry['id'])}</summary><form method='post' action='/trader-journal/review'>"
        f"<input type='hidden' name='token' value='{_safe(token)}'><input type='hidden' name='id' value='{_safe(entry['id'])}'>"
        f"<div class='filters'>{''.join(fields)}</div><p><button type='submit'>Rückblick speichern</button></p></form></details>"
    )


def _cancel_form(token: str, entry: Mapping[str, Any]) -> str:
    return (
        "<form method='post' action='/trader-journal/cancel'>"
        f"<input type='hidden' name='token' value='{_safe(token)}'><input type='hidden' name='id' value='{_safe(entry['id'])}'>"
        "<button type='submit'>zurückziehen</button></form>"
    )


def _result(entry: Mapping[str, Any]) -> str:
    if entry.get("status") == "CLOSED":
        return f"{entry['result_r']:+.2f} R ({REASON.get(entry.get('exit_reason'), entry.get('exit_reason'))})".replace(".", ",")
    if entry.get("status") == "FILLED":
        return f"läuft, MFE {entry.get('max_favorable_r', 0):+.2f} R / MAE {entry.get('max_adverse_r', 0):+.2f} R".replace(".", ",")
    if entry.get("status") == NO_TRADE:
        return ", ".join(GATE_SHORT.get(key, key) for key in entry.get("gate_failed") or [])
    return entry.get("note") or "–"


def render_trader_journal(data: dict[str, Any], journal: Mapping[str, Any], token: str, context_line: str,
                          form: Mapping[str, str] | None = None, error: str | None = None, saved: str | None = None) -> str:
    body = _hero("Trader-Journal", "Deine eigenen Papier-Trades hinter Broncx' Flussdiagramm, mit TIMs Kontext und Rückblick. Keine Order, kein Echtgeld.")
    if error:
        body += f"<section class='state-banner state-banner--fail'><div class='state-banner__primary'><h2 class='state-banner__state'>Nicht gespeichert</h2><p class='state-banner__sub'>{_safe(error)}</p></div></section>"
    elif saved:
        body += f"<section class='state-banner state-banner--ok'><div class='state-banner__primary'><h2 class='state-banner__state'>Gespeichert: {_safe(saved)}</h2></div></section>"
    stats = summary(journal)
    win = "–" if stats["win_rate"] is None else f"{stats['win_rate'] * 100:.0f} %"
    body += (
        "<section class='state-banner state-banner--unknown'><dl class='state-banner__metrics'>"
        f"<div class='state-banner__metric'><dt>Trades</dt><dd>{stats['trades']}</dd></div>"
        f"<div class='state-banner__metric'><dt>kein Trade</dt><dd>{stats['no_trades']}</dd></div>"
        f"<div class='state-banner__metric'><dt>beendet</dt><dd>{stats['closed']} · Trefferquote {_safe(win)}</dd></div>"
        f"<div class='state-banner__metric'><dt>Summe</dt><dd>{_r(stats['sum_r'])}</dd></div>"
        f"<div class='state-banner__metric'><dt>mit / gegen Bias</dt><dd>{_r(stats['with_bias_r'])} ({stats['with_bias']}) / {_r(stats['against_bias_r'])} ({stats['against_bias']})</dd></div>"
        f"<div class='state-banner__metric'><dt>Rückblick offen</dt><dd>{stats['review_open']}</dd></div></dl></section>"
    )
    body += _entry_form(token, form or {}, context_line)
    rows = []
    for entry in reversed(list(journal.get("entries") or [])[-200:]):
        severity, label = STATUS.get(str(entry.get("status")), ("unknown", str(entry.get("status"))))
        hints = "; ".join(list(entry.get("warnings") or []) + ([entry["data_gap"]] if entry.get("data_gap") else []))
        action = ""
        if entry.get("status") == "OPEN":
            action = _cancel_form(token, entry)
        elif (entry.get("status") in DONE or entry.get("status") == NO_TRADE) and not entry.get("review"):
            action = _review_form(token, entry)
        elif entry.get("review"):
            review = entry["review"]
            action = (f"<details><summary>Rückblick</summary><p><b>Passiert:</b> {_safe(review.get('happened'))}<br><b>Warum:</b> {_safe(review.get('why'))}<br>"
                      f"<b>Wieder?</b> {'Ja' if review.get('again') else 'Nein'}<br><b>Gelernt:</b> {_safe(review.get('learned'))}</p></details>")
        confluences = ", ".join(label for key, label in CONFLUENCES if key in (entry.get("confluences") or [])) or "keine"
        rows.append(
            f"<tr><td class='mono'>{_safe(entry.get('id'))}<br>{_safe(_local(entry.get('created_at')))}</td>"
            f"<td>{_safe(entry.get('direction'))}</td>"
            f"<td class='mono'>{_safe(_fmt(entry['entry']))} / {_safe(_fmt(entry['stop']))} / {_safe(_fmt(entry['target']))}<br>{_safe(_r(entry.get('planned_r') or 0, sign=False))}</td>"
            f"<td><span class='sev sev--{severity}'>{_safe(label)}</span><br>{_safe(_result(entry))}</td>"
            f"<td>{_safe(entry.get('thesis'))}<br><small>Konfluenzen: {_safe(confluences)}</small>"
            f"<br><small>TIM: {_safe((entry.get('context') or {}).get('summary') or '–')}</small>"
            + (f"<br><small>Hinweis: {_safe(hints)}</small>" if hints else "") + f"</td><td>{action}</td></tr>"
        )
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Einträge</p><h2>Journal</h2>"
        "<p class='cc-section__note'>Einstieg als Limit: ausgelöst, sobald eine 1m-Kerze den Preis erreicht. Stop zählt vor dem Ziel, wenn eine Kerze beides trifft. "
        "24 h ohne Einstieg: verfallen. 72 h nach dem Einstieg: zum Kerzenkurs geschlossen.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Eintrag</th><th>Richtung</th><th>Einstieg / Stop / Ziel</th><th>Stand</th><th>These</th><th>Aktion</th></tr></thead>"
        f"<tbody>{''.join(rows) or '<tr><td colspan=6 class=empty>Noch kein Eintrag.</td></tr>'}</tbody></table></div></section>"
    )
    week_rows = "".join(
        f"<tr><td>{_safe(w['week'])}</td><td>{w['trades']}</td><td>{w['no_trades']}</td><td>{w['closed']}</td><td>{w['wins']}</td><td>{_safe(_r(w['sum_r']))}</td><td>{w['reviewed']}</td></tr>"
        for w in stats["weeks"]
    ) or "<tr><td colspan='7' class='empty'>Noch keine Woche.</td></tr>"
    failures = ", ".join(f"{GATE_SHORT[key]}: {count}" for key, count in stats["gate_failures"].items() if count) or "keine"
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Wochenrückblick</p><h2>Pro Woche</h2>"
        f"<p class='cc-section__note'>Woran das Flussdiagramm bisher gestoppt hat: {_safe(failures)}.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Woche</th><th>Trades</th><th>kein Trade</th><th>beendet</th><th>Gewinner</th><th>Summe</th><th>mit Rückblick</th></tr></thead>"
        f"<tbody>{week_rows}</tbody></table></div>"
        "<p class='cc-note'>Diese Seite aktualisiert sich nicht von selbst, damit deine Eingabe nicht verloren geht. "
        "<a href='/trader-journal'>Neu laden</a> · <a href='/prep'>Vorbereitung</a> · <a href='/api/trader-journal'>JSON</a></p></section>"
    )
    return _layout("Trader-Journal", "Trader Journal", body, strip=_strip_states(data), refresh=False)


def _r(value: float, sign: bool = True) -> str:
    return (f"{value:+.2f} R" if sign else f"{value:.2f} R").replace(".", ",")
