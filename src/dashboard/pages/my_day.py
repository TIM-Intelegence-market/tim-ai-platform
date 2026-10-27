"""Daily prep page (/my-day): the trader's morning prep with TIM's levels filled in."""

from __future__ import annotations

import html
from typing import Any, Mapping, Sequence

from src.dashboard.chart_model import _fmt
from src.dashboard.daily_prep import FOCUS, KINDS, MOODS, NO_TRADE_DAY, PREP, SKIP, latest_per_day, level_value
from src.dashboard.helpers import _safe
from src.dashboard.layout import _hero, _layout, _strip_states
from src.dashboard.pages.trader_journal import _local, journal_csp

SEVERITY = {PREP: "ok", NO_TRADE_DAY: "warn", SKIP: "unknown"}
DEFAULTS = {"body": "3", "head": "3", "carry": "0", "max_risk_r": "2", "max_trades": "3", "cutoff": "22:00"}
my_day_csp = journal_csp  # no script at all, forms post to this origin only


def _value(form: Mapping[str, str], key: str) -> str:
    return html.escape(str(form.get(key, DEFAULTS.get(key, ""))))


def _checked(form: Mapping[str, str], key: str, default: bool = False) -> str:
    on = str(form.get(key, "")) == "1" if form else default
    return " checked" if on else ""


def _today_banner(entry: Mapping[str, Any] | None) -> str:
    if not entry:
        return ("<section class='state-banner state-banner--warn'><div class='state-banner__primary'>"
                "<h2 class='state-banner__state'>Heute noch keine Vorbereitung</h2>"
                "<p class='state-banner__sub'>Erst vorbereiten, dann Charts aufmachen.</p></div></section>")
    kind = entry.get("kind")
    if kind != PREP:
        note = f": {entry['note']}" if entry.get("note") else ""
        return (f"<section class='state-banner state-banner--{SEVERITY.get(kind, 'unknown')}'><div class='state-banner__primary'>"
                f"<h2 class='state-banner__state'>Heute: {_safe(KINDS.get(kind, kind))}{_safe(note)}</h2>"
                f"<p class='state-banner__sub'>gespeichert {_safe(_local(entry.get('created_at')))}</p></div></section>")
    limits = entry.get("limits") or {}
    mood = entry.get("mood") or {}
    hints = "; ".join(entry.get("hints") or []) or "keine"
    return (
        "<section class='state-banner state-banner--ok'><div class='state-banner__primary'>"
        f"<h2 class='state-banner__state'>Heute vorbereitet ({_safe(_local(entry.get('created_at')))})</h2>"
        f"<p class='state-banner__sub'>Hinweise: {_safe(hints)}</p></div>"
        "<dl class='state-banner__metrics'>"
        f"<div class='state-banner__metric'><dt>Fokus</dt><dd>{_safe(', '.join(entry.get('focus') or []))}</dd></div>"
        f"<div class='state-banner__metric'><dt>Max. Risiko</dt><dd>{_safe(str(limits.get('max_risk_r')).replace('.', ','))} R</dd></div>"
        f"<div class='state-banner__metric'><dt>Max. Trades</dt><dd>{_safe(limits.get('max_trades'))}</dd></div>"
        f"<div class='state-banner__metric'><dt>Schluss</dt><dd>{_safe(limits.get('cutoff'))}</dd></div>"
        f"<div class='state-banner__metric'><dt>Körper / Kopf / Altlast</dt><dd>{_safe(mood.get('body'))} / {_safe(mood.get('head'))} / {_safe(mood.get('carry'))}</dd></div>"
        "</dl></section>"
    )


def _form(token: str, form: Mapping[str, str], levels: Sequence[Mapping[str, Any]], last: Any) -> str:
    focus = "".join(
        f"<label><input type='checkbox' name='f_{coin}' value='1'{_checked(form, f'f_{coin}', coin == 'BTC')}> {coin}</label> "
        for coin in FOCUS
    )
    moods = "".join(
        f"<div><label for='md-{key}'>{_safe(label)}</label><input id='md-{key}' name='{key}' type='number' min='0' max='5' step='1' required value='{_value(form, key)}'></div>"
        for key, label in MOODS
    )
    level_rows = "".join(
        f"<label><input type='checkbox' name='lv_{i}' value='{html.escape(level_value(level), quote=True)}'"
        f"{_checked(form, f'lv_{i}', True) if not form else (' checked' if form.get(f'lv_{i}') else '')}> "  # all ticked on a fresh form
        f"<b>{_safe(level['label'])}</b> <span class='mono'>{_safe(_fmt(level['price']))}</span></label><br>"
        for i, level in enumerate(levels)
    ) or "<p class='empty'>TIM hat gerade keine Level (zu wenige Kerzen). Eigene Level unten eintragen.</p>"
    price = f"Kurs jetzt {_fmt(last)}. " if isinstance(last, (int, float)) else ""
    return (
        "<form method='post' action='/my-day/save'>"
        f"<input type='hidden' name='token' value='{_safe(token)}'>"
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>F · Fokus</p><h2>Was handle ich heute?</h2></div></div>"
        f"<div class='filters'>{focus}</div></section>"
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>A · Check-in, Charts noch zu</p><h2>Wie geht's mir?</h2>"
        "<p class='cc-section__note'>0 = schlecht, 5 = top. Altlast: 0 = frei, 5 = schwer (Tilt von gestern, Stress).</p></div></div>"
        f"<div class='filters'>{moods}</div>"
        "<div class='field'><label for='md-carrying'>Ich schleppe mit … (es handelt heute nicht mit)</label>"
        f"<input id='md-carrying' name='carrying' maxlength='1000' value='{_value(form, 'carrying')}'></div></section>"
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>B · Level von TIM</p><h2>Level, die ich heute beobachte</h2>"
        f"<p class='cc-section__note'>{_safe(price)}TIM schlägt die nächsten Level vor (Tag, Woche, Monat, Quartal, Jahr, VWAP). Abhaken, was du nicht brauchst.</p></div></div>"
        f"<div class='field'>{level_rows}</div>"
        "<div class='field'><label for='md-extra'>Eigene Level (frei, eine Zeile je Level)</label>"
        f"<textarea id='md-extra' name='extra_levels' rows='3' cols='80' maxlength='1000'>{_value(form, 'extra_levels')}</textarea></div></section>"
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>C · Plan</p><h2>Was mache ich, wenn die Level kommen?</h2></div></div>"
        "<div class='field'><label for='md-plan'>Plan</label>"
        f"<textarea id='md-plan' name='plan' rows='4' cols='80' maxlength='1000' required>{_value(form, 'plan')}</textarea></div>"
        f"<label><input type='checkbox' name='counter_trend' value='1'{_checked(form, 'counter_trend')}> Ich plane heute einen oder mehrere <b>Gegentrend</b>-Trades.</label></section>"
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>D · Grenzen</p><h2>Tagesgrenzen in R</h2>"
        "<p class='cc-section__note'>R = Risiko eines Trades. Ist die Grenze erreicht, ist der Tag vorbei.</p></div></div>"
        "<div class='filters'>"
        f"<div><label for='md-risk'>Max. Risiko am Tag (R)</label><input id='md-risk' name='max_risk_r' type='number' min='0.1' max='20' step='0.1' required value='{_value(form, 'max_risk_r')}'></div>"
        f"<div><label for='md-trades'>Max. Trades</label><input id='md-trades' name='max_trades' type='number' min='1' max='50' step='1' required value='{_value(form, 'max_trades')}'></div>"
        f"<div><label for='md-cutoff'>Schlusszeit (Ortszeit)</label><input id='md-cutoff' name='cutoff' type='time' required value='{_value(form, 'cutoff')}'></div>"
        "</div></section>"
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>E · Ritual</p><h2>Atmen und Eid</h2></div></div>"
        f"<label><input type='checkbox' name='breathing' value='1'{_checked(form, 'breathing')}> Box-Atmung gemacht (4 s ein, 4 halten, 4 aus, 4 halten)</label><br>"
        f"<label><input type='checkbox' name='oath' value='1' required{_checked(form, 'oath')}> Ich halte mich heute an meinen Plan und meine Grenzen.</label>"
        "<p><button type='submit' name='kind' value='PREP'>Vorbereitung speichern</button> "
        "<button type='submit' name='kind' value='SKIP' formnovalidate>Heute überspringen</button> "
        "<button type='submit' name='kind' value='NO_TRADE_DAY' formnovalidate>No-Trade-Tag</button></p>"
        "</section></form>"
    )


def _history(entries: Sequence[Mapping[str, Any]]) -> str:
    rows = []
    for entry in latest_per_day(entries):
        kind = entry.get("kind")
        limits = entry.get("limits") or {}
        detail = (f"{', '.join(entry.get('focus') or [])} · max {str(limits.get('max_risk_r')).replace('.', ',')} R, {limits.get('max_trades')} Trades, bis {limits.get('cutoff')}"
                  if kind == PREP else entry.get("note") or "–")
        rows.append(f"<tr><td class='mono'>{_safe(entry.get('day'))}</td><td><span class='sev sev--{SEVERITY.get(kind, 'unknown')}'>{_safe(KINDS.get(kind, kind))}</span></td>"
                    f"<td>{_safe(detail)}</td><td>{_safe(entry.get('plan') or '')}</td></tr>")
    body = "".join(rows) or "<tr><td colspan='4' class='empty'>Noch keine Einträge.</td></tr>"
    return (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Verlauf</p><h2>Letzte 14 Tage</h2>"
        "<p class='cc-section__note'>Je Tag zählt der letzte Eintrag. Ältere bleiben in der Datei (nur anhängen, nichts wird überschrieben).</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Tag</th><th>Art</th><th>Fokus und Grenzen</th><th>Plan</th></tr></thead>"
        f"<tbody>{body}</tbody></table></div></section>"
    )


def render_my_day(data: dict[str, Any], log: Mapping[str, Any], token: str, levels: Sequence[Mapping[str, Any]], last: Any,
                  today_entry: Mapping[str, Any] | None, form: Mapping[str, str] | None = None, error: str | None = None,
                  saved: str | None = None) -> str:
    body = _hero("Mein Tag", "Morgendliche Vorbereitung: Check-in, Level von TIM, Plan, Grenzen in R. Nur Papier und Selbstauskunft, keine Order.")
    if error:
        body += f"<section class='state-banner state-banner--fail'><div class='state-banner__primary'><h2 class='state-banner__state'>Nicht gespeichert</h2><p class='state-banner__sub'>{_safe(error)}</p></div></section>"
    elif saved:
        body += f"<section class='state-banner state-banner--ok'><div class='state-banner__primary'><h2 class='state-banner__state'>Gespeichert: {_safe(saved)}</h2></div></section>"
    body += _today_banner(today_entry)
    body += _form(token, form or {}, levels, last)
    body += _history(log.get("entries") or [])
    body += ("<section class='cc-section'><ul class='cc-list'><li>Datei: data/journal/daily_prep.json · <a href='/api/my-day'>JSON</a> · "
             "<a href='/prep'>Vorbereitung</a> · <a href='/trader-journal'>Trader-Journal</a></li></ul></section>")
    return _layout("Mein Tag", "My Day", body, strip=_strip_states(data), refresh=False)


def prep_banner(entry: Mapping[str, Any] | None) -> str:
    """Short line for /prep: is today prepared?"""
    if not entry:
        return ("<section class='state-banner state-banner--warn'><div class='state-banner__primary'>"
                "<h2 class='state-banner__state'>Mein Tag: heute noch nicht vorbereitet</h2>"
                "<p class='state-banner__sub'><a href='/my-day'>Jetzt vorbereiten</a>: Level sind schon eingetragen.</p></div></section>")
    if entry.get("kind") != PREP:
        return (f"<section class='state-banner state-banner--{SEVERITY.get(entry.get('kind'), 'unknown')}'><div class='state-banner__primary'>"
                f"<h2 class='state-banner__state'>Mein Tag: {_safe(KINDS.get(entry.get('kind'), entry.get('kind')))}</h2>"
                "<p class='state-banner__sub'><a href='/my-day'>ändern</a></p></div></section>")
    limits = entry.get("limits") or {}
    return ("<section class='state-banner state-banner--ok'><div class='state-banner__primary'>"
            f"<h2 class='state-banner__state'>Mein Tag: vorbereitet, max {_safe(str(limits.get('max_risk_r')).replace('.', ','))} R, "
            f"{_safe(limits.get('max_trades'))} Trades, Schluss {_safe(limits.get('cutoff'))}</h2>"
            "<p class='state-banner__sub'><a href='/my-day'>ansehen oder ändern</a></p></div></section>")
