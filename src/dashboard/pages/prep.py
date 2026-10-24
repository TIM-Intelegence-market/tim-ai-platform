"""Preparation page (/prep): HTF bias, value and session levels before the trade."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.dashboard.chart_model import _fmt
from src.dashboard.helpers import _safe
from src.dashboard.layout import _hero, _layout, _strip_states

LOCAL = ZoneInfo("Europe/Berlin")
BIAS_SEVERITY = {"LONG": "ok", "SHORT": "fail", "NEUTRAL": "warn", "UNKNOWN": "unknown"}
STATE_SEVERITY = {"UP": "ok", "DOWN": "fail", "RANGE": "warn", "UNKNOWN": "unknown"}


def _local(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).astimezone(LOCAL).strftime("%d.%m. %H:%M")
    except ValueError:
        return "–"


def _price(value: Any) -> str:
    return _fmt(float(value)) if isinstance(value, (int, float)) else "–"


def _pct(value: float) -> str:
    return f"{value:+.2f} %".replace(".", ",")


def _prep_page(data: dict[str, Any], model: Mapping[str, Any]) -> str:
    body = _hero("Vorbereitung", "Bias von oben, Vortages- und Wochen-Value, naked POCs und Sessions: Broncx' Schritte 1 bis 3 auf einer Seite. Nur Beobachtung, keine Order.")
    bias = model.get("bias") or {}
    where = model.get("location") or {}
    if not model.get("levels") and not model.get("htf"):
        notes = " ".join(model.get("notes") or ["Keine Daten."])
        body += f"<section class='cc-section'><p class='empty'>{_safe(notes)}</p></section>"
        return _layout("Vorbereitung", "Prep", body, strip=_strip_states(data))
    severity = BIAS_SEVERITY.get(str(bias.get("bias")), "unknown")
    body += (
        f"<section class='state-banner state-banner--{severity}'><div class='state-banner__primary'>"
        f"<span class='sev sev--{severity}'>{_safe(bias.get('bias', 'UNKNOWN'))}</span><h2 class='state-banner__state'>{_safe(bias.get('text'))}</h2>"
        f"<p class='state-banner__sub'>{_safe(where.get('label'))}: {_safe(where.get('hint'))}</p></div>"
        f"<dl class='state-banner__metrics'><div class='state-banner__metric'><dt>Kurs</dt><dd>{_safe(_price(model.get('last')))}</dd></div>"
        f"<div class='state-banner__metric'><dt>Stand</dt><dd>{_safe(_local(model.get('last_time')))}</dd></div></dl></section>"
    )
    rows = "".join(
        f"<tr><td>{_safe(label)}</td><td><span class='sev sev--{STATE_SEVERITY.get(info['state'], 'unknown')}'>{_safe(info['state'])}</span> {_safe(info['text'])}</td>"
        f"<td>{_safe(info['candles'])}</td><td>{_safe(' / '.join(_price(v) for v in info['swing_highs']) or '–')}</td>"
        f"<td>{_safe(' / '.join(_price(v) for v in info['swing_lows']) or '–')}</td></tr>"
        for label, info in (model.get("htf") or {}).items()
    )
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>1 · Bias von oben</p>"
        "<h2>Struktur auf 4h, 1D und 1W</h2><p class='cc-section__note'>Aus TIMs 1h-Kerzen gebaut. 1D und 4h bestimmen den Bias, die Woche bestätigt nur. "
        "„Lower timeframe bias does not invalidate higher timeframe bias.“</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Zeitebene</th><th>Struktur</th><th>Kerzen</th><th>letzte Swing-Hochs</th><th>letzte Swing-Tiefs</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
    )
    pd, pw = model.get("previous_day"), model.get("previous_week")
    value_rows = ""
    if pd:
        poor = ", ".join(name for flag, name in ((pd.get("poor_high"), "Poor High"), (pd.get("poor_low"), "Poor Low")) if flag) or "keine"
        value_rows += f"<tr><td>Vortag {_safe(pd['day'][8:10])}.{_safe(pd['day'][5:7])}.</td><td>{_price(pd.get('vah'))}</td><td>{_price(pd.get('poc'))}</td><td>{_price(pd.get('val'))}</td><td>{_price(pd['high'])} / {_price(pd['low'])}</td><td>{_safe(poor)}</td></tr>"
    if pw:
        value_rows += f"<tr><td>Vorwoche ab {_safe(pw['week'][8:10])}.{_safe(pw['week'][5:7])}.</td><td>{_price(pw.get('vah'))}</td><td>{_price(pw.get('poc'))}</td><td>{_price(pw.get('val'))}</td><td>{_price(pw['high'])} / {_price(pw['low'])}</td><td>–</td></tr>"
    ib = model.get("initial_balance")
    ib_text = (f"Initial Balance (erste 90 min des UTC-Tages): {_price(ib['high'])} / {_price(ib['low'])}, {ib['width']}"
               + ("" if ib["complete"] else " (läuft noch)") + ".") if ib else "Initial Balance: noch keine Kerzen heute."
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>2 · Kontext</p>"
        "<h2>Value von gestern und letzter Woche</h2><p class='cc-section__note'>Angenommen heißt: zwei 30m-Schlüsse jenseits der Kante. "
        "Poor High/Low: mindestens zwei 30m-Perioden am Extrem, eher ein Ziel als eine Wand.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Profil</th><th>VAH</th><th>POC</th><th>VAL</th><th>Hoch / Tief</th><th>unfertig</th></tr></thead>"
        f"<tbody>{value_rows or '<tr><td colspan=6 class=empty>Kein vollständiges Profil.</td></tr>'}</tbody></table></div>"
        f"<p class='cc-note'>{_safe(ib_text)}</p></section>"
    )
    last = model.get("last")
    level_rows = []
    marked = False
    for level in model.get("levels") or []:
        if not marked and last is not None and level["price"] < last:
            level_rows.append(f"<tr class='row--current'><td colspan='4'><b>Kurs {_safe(_price(last))}</b></td></tr>")
            marked = True
        level_rows.append(f"<tr><td>{_safe(level['label'])}</td><td class='mono'>{_safe(_price(level['price']))}</td><td class='mono'>{_safe(_pct(level['distance_pct']))}</td><td>{_safe(level['source'])}</td></tr>")
    if not marked and last is not None:
        level_rows.append(f"<tr class='row--current'><td colspan='4'><b>Kurs {_safe(_price(last))}</b></td></tr>")
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>3 · Orte</p>"
        "<h2>Level-Karte</h2><p class='cc-section__note'>Von oben nach unten, mit Abstand zum Kurs. Am Ort zählt die Reaktion, nicht das Level: "
        "gefangene Trader, Volumenspitze, Liquidationen.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Level</th><th>Preis</th><th>Abstand</th><th>Quelle</th></tr></thead>"
        f"<tbody>{''.join(level_rows)}</tbody></table></div></section>"
    )
    session_rows = "".join(
        f"<tr><td>{_safe(s['name'])}</td><td>{_safe(_local(s['start']))}–{_safe(_local(s['end'])[-5:])}</td><td>{_price(s['high'])}</td><td>{_price(s['low'])}</td><td>{'läuft' if s['running'] else 'vorbei'}</td></tr>"
        for s in model.get("sessions") or []
    ) or "<tr><td colspan='5' class='empty'>Noch keine Session mit Kerzen.</td></tr>"
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Timing</p><h2>Sessions</h2>"
        "<p class='cc-section__note'>Zeiten in deutscher Ortszeit. Broncx handelt am Wochenende nicht.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Session</th><th>Zeit</th><th>Hoch</th><th>Tief</th><th>Status</th></tr></thead>"
        f"<tbody>{session_rows}</tbody></table></div></section>"
    )
    notes = "".join(f"<li>{_safe(n)}</li>" for n in model.get("notes") or [])
    body += (
        "<section class='cc-section'><ul class='cc-list'>"
        f"<li>Quelle: {_safe(model.get('provenance'))}. Jedes Profil verteilt das Kerzenvolumen gleichmäßig über Hoch–Tief; Werte können von TradingView leicht abweichen.</li>"
        "<li>Tage und Wochen beginnen um 00:00 UTC. <a href='/api/prep'>JSON</a> · <a href='/setup-path'>Setup-Pfad</a> · <a href='/trader-journal'>Trader-Journal</a></li>"
        f"{notes}</ul></section>"
    )
    return _layout("Vorbereitung", "Prep", body, strip=_strip_states(data))
