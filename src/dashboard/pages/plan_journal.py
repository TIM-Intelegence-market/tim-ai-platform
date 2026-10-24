from __future__ import annotations

from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.dashboard.chart_model import _fmt, _time
from src.dashboard.helpers import _safe
from src.dashboard.layout import _hero, _layout, _strip_states
from src.dashboard.plan_cost_check import COST_LIMIT_R, COST_UNKNOWN, COST_WITHIN_LIMIT, NOT_TRADABLE_COST, cost_check, cost_summary
from src.dashboard.plan_journal import GRADE_NOTE, MAX_HOLD_HOURS, PENDING_HOURS, RULE_STRUCT, counter_trend, summary

LOCAL = ZoneInfo("Europe/Berlin")
STATUS_LABELS = {
    "OPEN": ("info", "wartet auf Einstieg"),
    "FILLED": ("warn", "im Trade"),
    "CLOSED": ("ok", "geschlossen"),
    "INVALIDATED": ("unknown", "ungültig vor Einstieg"),
    "REPLACED": ("unknown", "ersetzt"),
    "EXPIRED": ("unknown", "abgelaufen"),
}
EXIT_LABELS = {"STOP": "Stop", "BREAK_EVEN": "Break-even nach TP1", "TP3": "TP3", "TIMEOUT": f"nach {MAX_HOLD_HOURS} h", "INVALIDATION": "Schluss jenseits der Ungültigkeit"}
EVIDENCE_LABELS = {
    "INSUFFICIENT_EVIDENCE": ("unknown", "keine Evidenz"),
    "NEGATIVE_EVIDENCE": ("crit", "negativ belegt"),
    "CANDIDATE_FROZEN": ("info", "Kandidat, Holdout offen"),
    "PASSED_HOLDOUT": ("ok", "Holdout bestanden"),
}
DECISION_LABELS = {"NO_TRADE": ("unknown", "NO_TRADE"), "PAPER_TRADE": ("warn", "Papier-Trade")}
COST_LABELS = {COST_WITHIN_LIMIT: "ok", NOT_TRADABLE_COST: "crit", COST_UNKNOWN: "unknown"}
LIMIT_TEXT = f"{COST_LIMIT_R:.2f} R".replace(".", ",")


def _local(value: Any) -> str:
    moment = _time(value)
    return moment.astimezone(LOCAL).strftime("%d.%m. %H:%M") if moment else "–"


def _r_text(value: float | None) -> str:
    if value is None:
        return "–"
    return f"{value:+.2f} R".replace(".", ",")


def _cost_cell(entry: Mapping[str, Any]) -> str:
    """Estimated roundtrip costs (entry to stop) against the 0,25-R limit; information only."""
    check = cost_check(entry)
    status = check["cost_status"]
    if check["cost_r"] is None:
        value = "–"
        title = f"Kosten nicht berechenbar ({check['cost_reason']}); nie automatisch eingehalten"
    else:
        value = f"{check['cost_r']:.2f} R · {check['cost_bps']:.1f} bp".replace(".", ",")
        title = (f"Schätzung Einstieg bis Stop nach {check['cost_model_version']}: Gebühren {check['fee_r_estimate']:.4f} R, "
                 f"Slippage {check['slippage_r_estimate']:.4f} R; Schwelle {LIMIT_TEXT} (Hypothese, nur Anzeige)")
    return (f"<td class='mono' title='{_safe(title)}'>{_safe(value)}"
            f"<br><span class='sev sev--{COST_LABELS[status]}'>{_safe(status)}</span></td>")


def _row(entry: Mapping[str, Any]) -> str:
    severity, label = STATUS_LABELS.get(str(entry.get("status")), ("unknown", str(entry.get("status"))))
    labels = list(entry.get("target_labels") or [])
    targets = " · ".join(
        f"TP{i} {_fmt(t)}{f' ({labels[i - 1]})' if i <= len(labels) else ''}{' ✓' if i <= len(entry.get('tp_hits') or []) else ''}"
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
    invalid_text = f"{entry.get('timeframe', '15m')}-Schluss {entry.get('invalidation_side')} {_fmt(invalid)}" if invalid is not None else "–"
    zone = f"{_fmt(min(entry['entry_low'], entry['entry_high']))}–{_fmt(max(entry['entry_low'], entry['entry_high']))}" if entry.get("entry_low") is not None and entry.get("entry_high") is not None else "–"
    direction = str(entry.get("direction"))
    trend = f" <span class='sev sev--warn'>gegen den Trend ({_safe(entry.get('market_state'))})</span>" if counter_trend(direction, entry.get("market_state")) else ""
    grade = entry.get("setup_grade") or "–"
    grade_title = f"{GRADE_NOTE}; Regeln {entry.get('grade_ruleset_version') or '–'}; Zustand {entry.get('graded_state') or '–'}; " + ", ".join(entry.get("grade_reasons") or [])
    ev_sev, ev_label = EVIDENCE_LABELS.get(str(entry.get("evidence_status")), ("unknown", str(entry.get("evidence_status") or "nicht geprüft")))
    ev_title = str((entry.get("evidence_ref") or {}).get("reason") or "")
    dec_sev, dec_label = DECISION_LABELS.get(str(entry.get("journal_decision")), ("unknown", str(entry.get("journal_decision") or "–")))
    dec_title = ", ".join(entry.get("journal_decision_reasons") or []) + f"; Pipeline: {entry.get('pipeline_decision') or '–'}"
    return (
        f"<tr><td>{_safe(_local(entry.get('created_at')))}</td>"
        f"<td><span class='tag tag--{_safe(direction.lower())}'>{_safe(direction)}</span> {_safe(entry.get('scenario_id'))}{trend}</td>"
        f"<td title='{_safe(grade_title)}'>{_safe(grade)}<small> heuristisch</small></td>"
        f"<td title='{_safe(ev_title)}'><span class='sev sev--{ev_sev}'>{_safe(ev_label)}</span></td>"
        f"<td title='{_safe(dec_title)}'><span class='sev sev--{dec_sev}'>{_safe(dec_label)}</span><small> {_safe(entry.get('execution_status') or '–')}</small></td>"
        f"<td>{_safe(zone)}</td><td>{_safe(_fmt(entry['entry']))}</td><td>{_safe(_fmt(entry['stop']))}</td>"
        f"{_cost_cell(entry)}<td>{_safe(invalid_text)}</td><td>{_safe(targets)}</td>"
        f"<td><span class='sev sev--{severity}'>{_safe(label)}</span></td><td class='mono'>{_safe(_r_text(entry.get('gross_r')))}</td>"
        f"<td class='mono' title='Gebühren {_safe(_r_text(entry.get('fee_r')))}, Slippage {_safe(_r_text(entry.get('slippage_r')))} ({_safe(entry.get('cost_model_version') or '–')})'>{_safe(_r_text(entry.get('net_r')))}</td>"
        f"<td>{_safe(' · '.join(detail) or '–')}</td></tr>"
    )


def _compare(tim: Mapping[str, Any], struct: Mapping[str, Any]) -> str:
    """Both rule versions side by side on the same market."""
    rows = []
    for name, journal, href in (("TIM-Regel (Stop pauschal, Ziele 1,5/2/3 R)", tim, "/journal"),
                                ("Struktur-Regel (Stop hinter dem Swing, Ziele an Liquidität)", struct, "/journal/struct")):
        stats = summary(journal)
        win_rate = f"{stats['win_rate'] * 100:.0f} %" if stats["win_rate"] is not None else "–"
        rows.append(f"<tr><td><a href='{href}'>{_safe(name)}</a></td><td>{stats['plans']}</td><td>{stats['closed']}</td>"
                    f"<td>{_safe(win_rate)}</td><td class='mono'>{_safe(_r_text(stats['sum_r']))}</td>"
                    f"<td class='mono'>{_safe(_r_text(stats['sum_r'] / stats['closed'] if stats['closed'] else None))}</td></tr>")
    skipped = struct.get("structure_skips") or {}
    skip_text = ", ".join(f"{reason}: {count}" for reason, count in sorted(skipped.items(), key=lambda item: -item[1])) or "noch keine"
    return (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Vergleich</p>"
        "<h2>Zwei Regelversionen parallel</h2><p class='cc-section__note'>Gleiche Pläne, gleicher Einstieg, gleiche Ungültigkeit. "
        "Die Struktur-Regel legt den Stop hinter den nächsten 30m-Swing und die Ziele an die nächsten Liquiditätsorte aus der Vorbereitung; "
        f"liegt das erste Ziel unter 1,5 R, gibt es keinen Plan. Verworfen bisher: {_safe(skip_text)}. "
        "Aussagekraft erst nach vielen geschlossenen Plänen.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Regel</th><th>Pläne</th><th>geschlossen</th><th>Trefferquote</th><th>Summe</th><th>je Plan</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></section>"
    )


def _plan_journal_page(data: dict[str, Any], journal: Mapping[str, Any], account_risk_percent: float = 0.5,
                       other: Mapping[str, Any] | None = None) -> str:
    """``journal`` is the shown rule version; ``other`` the parallel one for the comparison."""
    entries = list(journal.get("entries") or [])
    stats = summary(journal)
    struct = journal.get("rule") == RULE_STRUCT
    integrity = str(journal.get("integrity") or "")
    body = ""
    if integrity.startswith("LOG_BROKEN"):
        body += f"<section class='state-banner state-banner--crit'><div class='state-banner__primary'><span class='sev sev--crit'>GESPERRT</span><h2 class='state-banner__state'>Journal gesperrt</h2><p class='state-banner__sub'>Das Ereignislog ist beschädigt; es wird nichts geschrieben und nichts gezählt, bis es geprüft ist. {_safe(integrity)}</p></div></section>"
    evidence = (f"Nur Papier, keine Empfehlung: {GRADE_NOTE}. Jeder Plan trägt getrennt Grade, Evidenzstatus und Entscheidung; "
                "ohne belegte Evidenz ist die Entscheidung NO_TRADE (RESEARCH_ONLY).")
    if struct:
        body += _hero("Plan-Journal: Struktur-Regel", "Dieselben Pläne mit Stop hinter dem Swing und Zielen an der Liquidität (Broncx), parallel zur TIM-Regel verfolgt. " + evidence)
    else:
        body += _hero("Plan-Journal", "TIMs Long- und Short-Pläne aus dem Setup-Pfad, automatisch festgehalten und nach TIMs Regeln verfolgt. " + evidence)
    if other is not None:
        body += _compare(other if struct else journal, journal if struct else other)
    win_rate = f"{stats['win_rate'] * 100:.0f} %" if stats["win_rate"] is not None else "–"
    account = stats["sum_r"] * account_risk_percent
    long_, short = stats["by_direction"]["LONG"], stats["by_direction"]["SHORT"]
    costs = cost_summary(journal)
    body += (
        "<section class='cc-section'><div class='metricstrip'>"
        f"<dl class='metricstrip__item'><dt>Pläne</dt><dd>{stats['plans']}<small>{stats['open']} warten · {stats['filled']} im Trade</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Geschlossen</dt><dd>{stats['closed']}<small>Trefferquote {_safe(win_rate)}</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Summe (Brutto-R)</dt><dd>{_safe(_r_text(stats['sum_r']))}<small>vor Kosten; hypothetisch ≈ {account:+.2f} % Konto bei {str(account_risk_percent).replace('.', ',')} % Risiko je Plan</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Summe (Netto-R)</dt><dd>{_safe(_r_text(stats['sum_net_r']))}<small>nach Gebühren und Slippage, Kostenmodell {_safe(stats['cost_model_version'])}; {stats['net_wins']} netto positiv</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Entscheidungen</dt><dd>{stats['no_trade']} NO_TRADE<small>{stats['paper_trades']} Papier-Trades · kein Setup mit belegter Evidenz</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Long / Short</dt><dd>{_safe(_r_text(long_['sum_r']))} / {_safe(_r_text(short['sum_r']))}<small>{long_['closed']} / {short['closed']} geschlossen</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Kosten über {_safe(LIMIT_TEXT)}</dt><dd>{costs['not_tradable_cost']}<small>NOT_TRADABLE_COST · {costs['cost_within_limit']} eingehalten · {costs['cost_unknown']} unbekannt; nur Anzeige</small></dd></dl>"
        f"<dl class='metricstrip__item'><dt>Gegen den Trend</dt><dd>{stats['counter_trend']['plans']}<small>{stats['counter_trend']['closed']} geschlossen · {_safe(_r_text(stats['counter_trend']['sum_r']))}</small></dd></dl>"
        "</div></section>"
    )
    rows = "".join(_row(e) for e in reversed(entries[-300:])) or "<tr><td colspan='15' class='empty'>Noch keine Pläne. Der erste Eintrag entsteht beim nächsten 30m-Schluss, sobald der Setup-Pfad einen Plan zeigt.</td></tr>"
    updated = _local(journal.get("updated_at")) if journal.get("updated_at") else "noch nie"
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Journal</p>"
        f"<h2>Alle Pläne (neueste zuerst)</h2><p class='cc-section__note'>Zeiten in deutscher Ortszeit. Zuletzt aktualisiert {_safe(updated)}. "
        "<a href='/setup-path'>Setup-Pfad</a> · " + ("<a href='/journal'>TIM-Regel</a> · <a href='/api/plan-journal?rule=struct'>JSON</a>" if struct else "<a href='/journal/struct'>Struktur-Regel</a> · <a href='/api/plan-journal'>JSON</a>") + "</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Angelegt</th><th>Plan</th><th>Grade</th><th>Evidenz</th><th>Entscheidung</th><th>Zone</th><th>Einstieg</th><th>Stop</th><th>Kosten (Schätzung)</th>"
        "<th>Ungültig bei</th><th>Ziele</th><th>Status</th><th>Brutto-R</th><th>Netto-R</th><th>Verlauf</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></section>"
    )
    body += (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Regeln</p><h2>So wird gezählt</h2></div></div><ul class='cc-list'>"
        "<li>Bei jedem 30m-Schluss werden die Pläne des Setup-Pfads festgehalten. Ändert TIM die Marken einer Richtung, wird der alte Plan als „ersetzt“ geschlossen.</li>"
        "<li>Einstieg als Limit zum Einstiegskurs, geprüft auf 1m-Kerzen. Rund um die NY-Eröffnung (15 min davor bis 30 min danach) kein Einstieg.</li>"
        f"<li>30m-Schluss jenseits der Ungültigkeitsmarke: vor dem Einstieg ist der Plan ungültig, im Trade wird der Rest zu diesem Schluss geschlossen. Nach {PENDING_HOURS} h ohne Einstieg = abgelaufen.</li>"
        + ("<li>Struktur-Regel: Stop 0,05 % hinter dem nächsten 30m-Swing jenseits der Einstiegszone, TP1–TP3 an den nächsten Liquiditätsorten "
           "(Vortag, Vorwoche, naked POC, Sessions, IB, 30m-Swings; fehlende Ziele wiederholen das letzte). Erstes Ziel unter 1,5 R: kein Plan.</li>" if struct else "")
        + "<li>Im Trade nach TIMs Management: je ein Drittel an TP1, TP2 und TP3 (TIM-Regel: 1,5 R, 2 R, 3 R), Stop nach TP1 auf Einstand. Der strukturelle Trailing-Stop ist nicht nachgebildet.</li>"
        f"<li>Berühren Stop und Ziel dieselbe 1m-Kerze, zählt der Stop. Nach {MAX_HOLD_HOURS} h wird der Rest zum Kerzenkurs geschlossen.</li>"
        "<li>Ergebnis als Brutto-R (1 R = Abstand Einstieg–Stop) und Netto-R nach Forschungsprotokoll 1.1: Gebühr 0,05 % und Slippage 0,03 % je Seite auf Einstieg, jedes Drittel und den Rest, 0,05 % Slippage bei Stop-Ausführung; Kosten in R = Kosten / Stopabstand. Keine Order, keine Anlageberatung.</li>"
        "<li>Speicherung: Jede Änderung ist ein Ereignis im append-only, hash-verketteten Log (<code>tim_plan_journal.events.jsonl</code>); diese Seite ist eine daraus abgeleitete Sicht. Ein Neustart mit denselben Kerzen erzeugt keine neuen Ereignisse; korrigierte Kerzen zu einem schon verarbeiteten 30m-Schluss werden vermerkt, ändern aber keine Entscheidung.</li>"
        f"<li>Kosten-Schwelle (Hypothese, nur Anzeige): geschätzte Roundtrip-Kosten vom Einstieg bis zum Stop nach Protokoll 1.1, Gebühren auf den Kurs jeder Seite. "
        f"Über {_safe(LIMIT_TEXT)} heißt NOT_TRADABLE_COST, genau {_safe(LIMIT_TEXT)} gilt als eingehalten, fehlende oder ungültige Marken ergeben COST_UNKNOWN. "
        "Die Markierung ändert keinen Einstieg, Stop, Grade, keine Entscheidung und keine Ausführung.</li>"
        f"<li>Grade A/B/C: {GRADE_NOTE}. Benotet wird der tatsächliche Szenariozustand, nicht die Vorschau. A+ wird nicht vergeben, weil keine geprüfte Regel dafür existiert.</li>"
        "<li>Ausführbarkeit (nur Papier): Instrument BINANCE/SPOT/BTCUSDT mit Tick 0,01; der Einstieg wird gegen den Plan auf den Tick gerundet. Ein Short auf Spot gilt als nicht ausführbar (keine Leihe modelliert), Datenqualität unter PASS sperrt, veraltete Kerzen (älter als 30 min) erzeugen keine neuen Pläne.</li>"
        "<li>Evidenz: Urteil aus dem Hypothesenregister (docs/research_lab/REGISTER.jsonl) nur über eine geprüfte Regel-Äquivalenz; ohne diese „keine Evidenz“. Entscheidung NO_TRADE, solange Evidenz, Freigabe oder Pipeline fehlen. Grade, Evidenz und Entscheidung werden beim Festhalten gesetzt und danach nie geändert.</li>"
        "</ul></section>"
    )
    return _layout("Plan-Journal", "Plan Journal", body, strip=_strip_states(data))


def journal_note(journal: Mapping[str, Any]) -> str:
    """One line for the Setup-Pfad page."""
    stats = summary(journal)
    if str(journal.get("integrity") or "").startswith("LOG_BROKEN"):
        return "Plan-Journal gesperrt: Ereignislog beschädigt."
    return (f"Plan-Journal: {stats['plans']} Pläne festgehalten, {stats['open']} warten, {stats['filled']} im Trade, "
            f"{stats['closed']} geschlossen ({_r_text(stats['sum_r'])} brutto, {_r_text(stats['sum_net_r'])} netto). {stats['no_trade']} × NO_TRADE, nur Forschung.")

