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


def _setup_path_page(data: dict[str, Any]) -> str:
    candles = [item for item in data.get("candles", []) if isinstance(item, dict)]
    health, quality = data.get("operational_health", {}), data.get("research_quality", {})
    fresh, enough = health.get("status") == "GREEN", len(candles) >= 20
    quality_status = str(quality.get("validation_status") or quality.get("status") or "UNKNOWN").upper()
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
    body += f"<section class='state-banner state-banner--{status}'><div class='state-banner__primary'><span class='sev sev--{status}'>{gate}</span><h2 class='state-banner__state'>Analyse-Gate</h2><p class='state-banner__sub'>{_safe(gate_reason)}</p></div><dl class='state-banner__metrics'><div class='state-banner__metric'><dt>Provenance</dt><dd>{_safe(data.get('provenance'))}</dd></div><div class='state-banner__metric'><dt>Data age</dt><dd>{_safe(health.get('data_age_seconds'))}<small>Sekunden</small></dd></div><div class='state-banner__metric'><dt>Quality</dt><dd>{_safe(quality_status)}</dd></div></dl></section>"
    body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Zeitkontext</p><h2>Short, Mid und Long Term</h2><p class='cc-section__note'>Die Horizonte werden nicht zu einem unqualifizierten Score zusammengezogen.</p></div></div><div class='hgroup'><article class='horizon'><div class='horizon__head'><div><p class='horizon__key'>SHORT</p><h3>Aktuelle Reaktion</h3></div><span class='sev sev--{status}'>{gate}</span></div><table><tr><td>Letzter Schluss</td><td>{_safe(f'{latest:,.2f}' if latest is not None else 'UNAVAILABLE')}</td></tr><tr><td>Belege</td><td>Struktur, Delta/Footprint falls vorhanden</td></tr></table></article><article class='horizon'><div class='horizon__head'><div><p class='horizon__key'>MID</p><h3>Range &amp; Location</h3></div><span class='sev sev--{'ok' if enough else 'unknown'}'>{'PASS' if enough else 'UNKNOWN'}</span></div><table><tr><td>20-Candle-Range</td><td>{_safe(rng(candles[-20:]))}</td></tr><tr><td>Belege</td><td>Support, Resistance, Fib, Value</td></tr></table></article><article class='horizon'><div class='horizon__head'><div><p class='horizon__key'>LONG</p><h3>Übergeordneter Kontext</h3></div><span class='sev sev--unknown'>REQUIRED</span></div><table><tr><td>Sichtbare Range</td><td>{_safe(rng(candles))}</td></tr><tr><td>Belege</td><td>HTF-Struktur, Value-Migration, Regime</td></tr></table></article></div></section>"
    body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Erklärtes Chartbild</p><h2>Beobachtete Schlusskurse</h2><p class='cc-section__note'>Jüngste {len(candles[-30:])} gespeicherte Candles. Keine Zukunftswerte.</p></div></div><div class='cc-surface setup-chart'>{_setup_chart(candles)}</div></section>"
    body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Setup-Pfad</p><h2>Von Daten zu einer überprüfbaren Hypothese</h2></div></div><div class='pipeline'><div class='pipeline__stage'><b>1 · Governance</b><span class='sev sev--{status}'>{gate}</span><span class='pipeline__value'>Quelle, Frische, Vollständigkeit</span></div><div class='pipeline__stage'><b>2 · Kontext</b><span class='sev sev--unknown'>REQUIRED</span><span class='pipeline__value'>HTF, Regime, Value</span></div><div class='pipeline__stage'><b>3 · Location</b><span class='sev sev--unknown'>REQUIRED</span><span class='pipeline__value'>Support, Resistance, Fib</span></div><div class='pipeline__stage'><b>4 · Beweis</b><span class='sev sev--unknown'>REQUIRED</span><span class='pipeline__value'>Structure, Delta, Absorption</span></div><div class='pipeline__stage'><b>5 · Reflexion</b><span class='sev sev--info'>LOGGED</span><span class='pipeline__value'>Outcome, Fehlerkategorie, Review</span></div></div><p class='cc-note'>Absorption wird nur nach belegter aggressiver Ausführung und fehlendem Preisfortschritt angezeigt. Ohne Footprint-, Delta- oder Value-Profile-Daten bleibt die Aussage UNAVAILABLE.</p></section>"
    body += f"<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>Lernen &amp; Reparatur</p><h2>Feedback aus abgeschlossenen Research Cases</h2><p class='cc-section__note'>Fehler werden als Daten-, Kontext-, Location-, Struktur-, Orderflow- oder Confirmation-Problem protokolliert; Regeln ändern sich nicht automatisch.</p></div></div><div class='metricstrip'><dl class='metricstrip__item'><dt>Research Cases</dt><dd>{_safe(cases.get('total'))}</dd></dl><dl class='metricstrip__item'><dt>Geschlossen</dt><dd>{_safe(cases.get('closed'))}</dd></dl><dl class='metricstrip__item'><dt>Fehlende Evidenz</dt><dd>{len(missing)}<small>{_safe(', '.join(missing[:2]) or 'keine dokumentiert')}</small></dd></dl></div></section>"
    return _layout("Setup Path", "Setup Path", body, strip=_strip_states(data))
