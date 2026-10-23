from __future__ import annotations

from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.dashboard.chart_model import _fmt, _time
from src.dashboard.helpers import _safe
from src.dashboard.layout import _hero, _layout, _strip_states
from src.dashboard.plan_journal import MAX_HOLD_HOURS, PENDING_HOURS, counter_trend, summary

LOCAL = ZoneInfo("Europe/Berlin")
STATUS_LABELS = {
    "OPEN": ("info", "wartet auf Einstieg"),
    "FILLED": ("warn", "im Trade"),
    "CLOSED": ("ok", "geschlossen"),
    "INVALIDATED": ("unknown", "ungültig vor Einstieg"),
    "REPLACED": ("unknown", "ersetzt"),
    "EXPIRED": ("unknown", "abgelaufen"),
}
EXIT_LABELS = {"STOP": "Stop", "BREAK_EVEN": "Break-even nach TP1", "TP3": "TP3", "TIMEOUT": f"nach {MAX_HOLD_HOURS} h", "INVALIDATION": "15m-Schluss jenseits der Ungültigkeit"}


def _local(value: Any) -> str:
    moment = _time(value)
    return moment.astimezone(LOCAL).strftime("%d.%m. %H:%M") if moment else "–"


def _r_text(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:+.2f} R".replace(".", ",")


def _row(entry: Mapping[str, Any]) -> str:
    severity, label = STATUS_LABELS.get(str(entry.get("status")), ("unknown", str(entry.get("status"))))
    targets = " · ".join(
        f"TP{i} {_fmt(t)}{' ✓' if i <= len(entry.get('tp_hits') or []) else ''}"
        for i, t in enumerate(entry.get("targets") or [], start=1)
    )
    detail = []
    if entry.get("filled_at"):
        detail.append(f"Einstieg {_local(entry['filled_at'])}")
    if entry.get("exit_reason"):
        detail.append(f"Ausstieg {EXIT_LABELS.get(entry['exit_reason'], entry['exit_reason'])} {_local(entry.get('closed_at'))}")
    elif entry.get("closed_at"):
        detail.append(_local(entry["closed_at"]))
    if entry.get("note"):
        detail.append(str(entry["note"]))
    if entry.get("data_gap"):
        detail.append("Datenlücke: " + str(entry["data_gap"]))
    invalid = entry.get("invalidation_level")
    invalid_text = f"15m-Schluss {entry.get('invalidation_side')} {_fmt(invalid)}" if invalid is not None else "–"
    zone = f"{_fmt(min(entry['entry_low'], entry['entry_high']))}–{_fmt(max(entry['entry_low'], entry['entry_high']))}" if entry.get("entry_low") is not None and entry.get("entry_high") is not None else "–"
    direction = str(entry.get("direction"))
    trend = f" <span class='sev sev--warn'>gegen den Trend ({_safe(entry.get('market_state'))})</span>" if counter_trend(direction, entry.get("market_state")) else ""
    return (
        f"<tr><td>{_safe(_local(entry.get('created_at')))}</td>"
        f"<td><span class='tag tag--{_safe(direction.lower())}'>{_safe(direction)}</span> {_safe(entry.get('scenario_id'))}{trend}</td>"
        f"<td>{_safe(zone)}</td><td>{_safe(_fmt(entry['entry']))}</td><td>{_safe(_fmt(entry['stop']))}</td>"
        f"<td>{_safe(invalid_text)}</td><td>{_safe(targets)}</td>"
        f"<td><span class='sev sev--{severity}'>{_safe(label)}</span></td><td class='mono'>{_safe(_r_text(entry.get('result_r')))}</td>"
        f"<td>{_safe(' · '.join(detail) or '–')}</td></tr>"
    )


def _plan_journal_page(data: dict[str, Any], journal: Mapping[str, Any], account_risk_percent: float = 0.5) -> str:
    entries = list(journal.get("entries") or [])
    stats = summary(journal)
    body = _hero("Plan-Journal", "TIMs Long- und Short-Pläne aus dem Setup-Pfad, automatisch festgehalten und nach TIMs Regeln verfolgt. Nur Papier.")
    win_rate = f"{stats['win_rate'] * 100:.0f} %" if stats["win_rate"] is not None else "–"
    account = stats["sum_r"] * account_risk_percent
    long_, short = stats["by_direction"]["LONG"], stats["by_direction"]["SHORT"]
    body += (
        "<section class='cc-section'><div class='metricstrip'>"
        f"<dl class='metricstrip__item'><dt>Pläne</dt><dd>{stats['plans']}<small>{stats['open']} warten · {stats['filled']} im Trade</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Geschlossen</dt><dd>{stats['closed']}<small>Trefferquote {_safe(win_rate)}</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Summe</dt><dd>{_safe(_r_text(stats['sum_r']))}<small>≈ {account:+.2f} % Konto bei {str(account_risk_percent).replace('.', ',')} % Risiko je Plan</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Long / Short</dt><dd>{_safe(_r_text(long_['sum_r']))} / {_safe(_r_text(short['sum_r']))}<small>{long_['closed']} / {short['closed']} geschlossen</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Gegen den Trend</dt><dd>{stats['counter_trend']['plans']}<small>{stats['counter_trend']['closed']} geschlossen · {_safe(_r_text(stats['counter_trend']['sum_r']))}</small></dd></dl>"
        "</div></section>"
    )
    rows = "".join(_row(e) for e in reversed(entries[-300:])) or "<tr><td colspan='10' class='empty'>Noch keine Pläne. Der erste Eintrag entsteht beim nächsten 15m-Schluss, sobald der Setup-Pfad einen Plan zeigt.</td></tr>"
    updated = _local(journal.get("updated_at")) if journal.get("updated_at") else "noch nie"
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Journal</p>"
        f"<h2>Alle Pläne (neueste zuerst)</h2><p class='cc-section__note'>Zeiten in deutscher Ortszeit. Zuletzt aktualisiert {_safe(updated)}. "
        "<a href='/setup-path'>Setup-Pfad</a> · <a href='/api/plan-journal'>JSON</a></p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Angelegt</th><th>Plan</th><th>Zone</th><th>Einstieg</th><th>Stop</th>"
        "<th>Ungültig bei</th><th>Ziele</th><th>Status</th><th>Ergebnis</th><th>Verlauf</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
    )
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Regeln</p><h2>So wird gezählt</h2></div></div><ul class='cc-list'>"
        "<li>Bei jedem 15m-Schluss werden die Pläne des Setup-Pfads festgehalten. Ändert TIM die Marken einer Richtung, wird der alte Plan als „ersetzt“ geschlossen.</li>"
        "<li>Einstieg als Limit zum Einstiegskurs, geprüft auf 1m-Kerzen. Rund um die NY-Eröffnung (15 min davor bis 30 min danach) kein Einstieg.</li>"
        f"<li>15m-Schluss jenseits der Ungültigkeitsmarke: vor dem Einstieg ist der Plan ungültig, im Trade wird der Rest zu diesem Schluss geschlossen. Nach {PENDING_HOURS} h ohne Einstieg = abgelaufen.</li>"
        "<li>Im Trade nach TIMs Management: je ein Drittel an TP1 (1,5 R), TP2 (2 R) und TP3 (3 R), Stop nach TP1 auf Einstand. Der strukturelle Trailing-Stop ist nicht nachgebildet.</li>"
        f"<li>Berühren Stop und Ziel dieselbe 1m-Kerze, zählt der Stop. Nach {MAX_HOLD_HOURS} h wird der Rest zum Kerzenkurs geschlossen.</li>"
        "<li>Ergebnis in R (1 R = Abstand Einstieg–Stop). Keine Gebühren, kein Slippage. Keine Order, keine Anlageberatung.</li>"
        "</ul></section>"
    )
    return _layout("Plan-Journal", "Plan Journal", body, strip=_strip_states(data))


def journal_note(journal: Mapping[str, Any]) -> str:
    """One line for the Setup-Pfad page."""
    stats = summary(journal)
    return (f"Plan-Journal: {stats['plans']} Pläne festgehalten, {stats['open']} warten, {stats['filled']} im Trade, "
            f"{stats['closed']} geschlossen ({_r_text(stats['sum_r'])}).")

