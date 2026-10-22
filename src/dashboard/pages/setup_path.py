from __future__ import annotations

from typing import Any
from src.dashboard.design_system import severity as _severity_of

from src.dashboard.helpers import _number, _safe
from src.dashboard.layout import _hero, _layout, _strip_states

def _setup_chart(candles: list[dict[str, Any]]) -> str:
    closes = [value for item in candles[-30:] if (value := _number(item.get("close"))) is not None]
    if len(closes) < 2:
        return "<p class='empty'>Kein ausreichend vollständiger Candle-Verlauf für ein Chartbild.</p>"
    low, high = min(closes), max(closes)
    spread = max(high - low, high * 0.001)
    points = " ".join(f"{40 + i * 600 / (len(closes) - 1):.1f},{26 + (high - value) * 210 / spread:.1f}" for i, value in enumerate(closes))
    return f"<svg viewBox='0 0 680 280' role='img' aria-label='BTCUSDT Schlusskurse, sichtbares Zeitfenster'><rect x='40' y='26' width='600' height='210' class='setup-chart__frame'/><polyline points='{points}' class='setup-chart__line'/><text x='40' y='18'>{_safe(f'{high:,.2f}')}</text><text x='40' y='258'>{_safe(f'{low:,.2f}')}</text><text x='640' y='258' text-anchor='end'>letzter Schluss {_safe(f'{closes[-1]:,.2f}')}</text></svg>"


def _plan_lines(scenario: dict[str, Any]) -> list[str]:
    """One plan written out in words, like a hand-drawn chart."""
    from src.dashboard.chart_model import _fmt

    lines = [scenario.get("plan_text") or f"Plan {scenario.get('id')} {scenario.get('direction')}"]
    invalid = scenario.get("invalidation_level")
    if invalid:
        lines.append(invalid["text"])
    preview = scenario.get("preview") or {}
    if preview.get("stop_text"):
        lines.append(preview["stop_text"])
    targets = preview.get("targets") or []
    if targets:
        lines.append("Ziele: " + " · ".join(f"TP{i} {_fmt(t)}" for i, t in enumerate(targets[:2], start=1)))
    lines.append(f"Status {scenario.get('state')} · fehlt: {', '.join((scenario.get('missing_confirmations') or [])[:2]) or '–'}")
    return lines


def _plan_chart_section(chart: dict[str, Any]) -> str:
    from src.dashboard.pages.chart import _chart_svg

    analysis = chart.get("analysis") or {}
    plans = [s for s in analysis.get("scenarios", []) if s.get("plan_text")]
    cards = "".join(
        f"<article class='sp-plan sp-plan--{_safe(str(s.get('direction', '')).lower())}'><h3>{_safe(lines[0])}</h3><ul>"
        + "".join(f"<li>{_safe(line)}</li>" for line in lines[1:]) + "</ul></article>"
        for s in plans for lines in [_plan_lines(s)]
    ) or "<p class='cc-note'>Kein Plan mit Einstiegszone: Der Kurs steht nicht an einer Range-Kante.</p>"
    nxt = chart.get("next_block")
    block = f"Nächste Sperrzeit: {nxt['label']} {nxt['start'][11:16]}–{nxt['end'][11:16]} UTC ({nxt['start'][:10]}). " if nxt else ""
    decision = (analysis.get("decision") or {}).get("status", "UNAVAILABLE")
    return (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Erklärtes Chartbild</p>"
        f"<h2>TIMs Pläne im Chart ({_safe(chart.get('timeframe'))})</h2><p class='cc-section__note'>Zonen, Stop, Ungültigkeit und Ziele ausgeschrieben. "
        f"Entscheidung der Pipeline: {_safe(decision)}. <a href='/chart?tf={_safe(chart.get('timeframe'))}'>Großer Chart</a></p></div></div>"
        f"<div class='cc-surface tc-chart'>{_chart_svg(chart)}</div><div class='sp-plans'>{cards}</div>"
        f"<p class='cc-note'>{_safe(block)}Rund um die NY-Eröffnung (15 min davor bis 30 min danach) keine neuen Einstiege; das Fenster ist im Chart gelb markiert. "
        "Stop und Ziele sind eine Vorschau nach TIMs Regeln für unbestätigte Szenarien, keine Order und keine Anlageberatung.</p></section>"
    )


def _quality_evidence(data: dict[str, Any]) -> tuple[str, str]:
    """Return (status, source) for the data-quality part of the analysis gate.

    The research quality report (data/research/quality/latest.json) is only
    written by scripts/research_infrastructure_review.py. When it is missing,
    the gate uses the runtime's own measured 24h candle coverage
    (Rolling Liveness) instead of staying UNKNOWN forever.
    """
    quality = data.get("research_quality") or {}
    status = quality.get("validation_status") or quality.get("status")
    if status:
        return str(status).upper(), "Research-Qualitätsbericht"
    for item in (data.get("operations") or {}).get("datasets") or []:
        if isinstance(item, dict) and str(item.get("source", "")).endswith("rolling_liveness.json"):
            return str(item.get("status") or "UNKNOWN").upper(), f"Rolling Liveness 24h ({item.get('coverage', 'UNAVAILABLE')})"
    return "UNKNOWN", "kein Qualitätsnachweis vorhanden"


def _setup_path_page(data: dict[str, Any], chart: dict[str, Any] | None = None) -> str:
    candles = [item for item in data.get("candles", []) if isinstance(item, dict)]
    health = data.get("operational_health", {})
    fresh, enough = health.get("status") == "GREEN", len(candles) >= 20
    quality_status, quality_source = _quality_evidence(data)
    quality_ok = quality_status in {"PASS", "VALID", "GREEN", "OK"}
    gate = "PASS" if fresh and enough and quality_ok else "BLOCKED"
    status = _severity_of(gate)
    latest = _number(candles[-1].get("close")) if candles else None
    def rng(items: list[dict[str, Any]]) -> str:
        values = [value for item in items if (value := _number(item.get("close"))) is not None]
        return f"{min(values):,.2f} – {max(values):,.2f}" if values else "UNAVAILABLE"
    cases = data.get("case_counts", {})
    missing = sorted({str(x) for case in data.get("research_cases", []) for x in case.get("missing_evidence", []) if x})
    body = _hero("Setup Path", "Erklärte BTC-Analyse mit Daten-Governance, drei Zeithorizonten und rückgekoppelter Fehlerprüfung.")
    body += "<p class='cc-note' aria-live='polite'>Live-Synchronisierung aktiv: Der Analysepfad wird bei neuen Daten automatisch aus einem konsistenten Snapshot neu aufgebaut.</p>"
    gate_reason = "Frische Daten, mindestens 20 Candles und bestätigte Datenqualität verfügbar." if gate == "PASS" else "Setup-Vorschläge gesperrt: Frische, ausreichende Candle-Historie oder bestätigte Datenqualität fehlt."
    body += f"<section class='state-banner state-banner--{status}'><div class='state-banner__primary'><span class='sev sev--{status}'>{gate}</span><h2 class='state-banner__state'>Analyse-Gate</h2><p class='state-banner__sub'>{_safe(gate_reason)}</p></div><dl class='state-banner__metrics'><div class='state-banner__metric'><dt>Provenance</dt><dd>{_safe(data.get('provenance'))}</dd></div><div class='state-banner__metric'><dt>Data age</dt><dd>{_safe(health.get('data_age_seconds'))}<small>Sekunden</small></dd></div><div class='state-banner__metric'><dt>Quality</dt><dd>{_safe(quality_status)}<small>{_safe(quality_source)}</small></dd></div></dl></section>"
    body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Zeitkontext</p><h2>Short, Mid und Long Term</h2><p class='cc-section__note'>Die Horizonte werden nicht zu einem unqualifizierten Score zusammengezogen.</p></div></div><div class='hgroup'><article class='horizon'><div class='horizon__head'><div><p class='horizon__key'>SHORT</p><h3>Aktuelle Reaktion</h3></div><span class='sev sev--{status}'>{gate}</span></div><table><tr><td>Letzter Schluss</td><td>{_safe(f'{latest:,.2f}' if latest is not None else 'UNAVAILABLE')}</td></tr><tr><td>Belege</td><td>Struktur, Delta/Footprint falls vorhanden</td></tr></table></article><article class='horizon'><div class='horizon__head'><div><p class='horizon__key'>MID</p><h3>Range &amp; Location</h3></div><span class='sev sev--{'ok' if enough else 'unknown'}'>{'PASS' if enough else 'UNKNOWN'}</span></div><table><tr><td>20-Candle-Range</td><td>{_safe(rng(candles[-20:]))}</td></tr><tr><td>Belege</td><td>Support, Resistance, Fib, Value</td></tr></table></article><article class='horizon'><div class='horizon__head'><div><p class='horizon__key'>LONG</p><h3>Übergeordneter Kontext</h3></div><span class='sev sev--unknown'>REQUIRED</span></div><table><tr><td>Sichtbare Range</td><td>{_safe(rng(candles))}</td></tr><tr><td>Belege</td><td>HTF-Struktur, Value-Migration, Regime</td></tr></table></article></div></section>"
    if chart and chart.get("candles"):
        body += _plan_chart_section(chart)
    else:
        body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Erklärtes Chartbild</p><h2>Beobachtete Schlusskurse</h2><p class='cc-section__note'>Jüngste {len(candles[-30:])} gespeicherte Candles. Keine Zukunftswerte.</p></div></div><div class='cc-surface setup-chart'>{_setup_chart(candles)}</div></section>"
    body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Setup-Pfad</p><h2>Von Daten zu einer überprüfbaren Hypothese</h2></div></div><div class='pipeline'><div class='pipeline__stage'><b>1 · Governance</b><span class='sev sev--{status}'>{gate}</span><span class='pipeline__value'>Quelle, Frische, Vollständigkeit</span></div><div class='pipeline__stage'><b>2 · Kontext</b><span class='sev sev--unknown'>REQUIRED</span><span class='pipeline__value'>HTF, Regime, Value</span></div><div class='pipeline__stage'><b>3 · Location</b><span class='sev sev--unknown'>REQUIRED</span><span class='pipeline__value'>Support, Resistance, Fib</span></div><div class='pipeline__stage'><b>4 · Beweis</b><span class='sev sev--unknown'>REQUIRED</span><span class='pipeline__value'>Structure, Delta, Absorption</span></div><div class='pipeline__stage'><b>5 · Reflexion</b><span class='sev sev--info'>LOGGED</span><span class='pipeline__value'>Outcome, Fehlerkategorie, Review</span></div></div><p class='cc-note'>Stufen 2 bis 4 werden noch nicht automatisch berechnet; REQUIRED heißt hier: Beleg fehlt, nicht Fehler. </p><p class='cc-note'>Absorption wird nur nach belegter aggressiver Ausführung und fehlendem Preisfortschritt angezeigt. Ohne Footprint-, Delta- oder Value-Profile-Daten bleibt die Aussage UNAVAILABLE.</p></section>"
    body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Lernen &amp; Reparatur</p><h2>Feedback aus abgeschlossenen Research Cases</h2><p class='cc-section__note'>Fehler werden als Daten-, Kontext-, Location-, Struktur-, Orderflow- oder Confirmation-Problem protokolliert; Regeln ändern sich nicht automatisch.</p></div></div><div class='metricstrip'><dl class='metricstrip__item'><dt>Research Cases</dt><dd>{_safe(cases.get('total'))}</dd></dl><dl class='metricstrip__item'><dt>Geschlossen</dt><dd>{_safe(cases.get('closed'))}</dd></dl><dl class='metricstrip__item'><dt>Fehlende Evidenz</dt><dd>{len(missing)}<small>{_safe(', '.join(missing[:2]) or 'keine dokumentiert')}</small></dd></dl></div></section>"
    return _layout("Setup Path", "Setup Path", body, strip=_strip_states(data))
