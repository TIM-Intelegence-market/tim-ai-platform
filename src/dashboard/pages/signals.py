from __future__ import annotations

import html
from typing import Any

from src.dashboard.components import _quality_exception_rows, _retrospective_outcome_rows, _signal_context_rows
from src.dashboard.constants import DASHBOARD_VERSION, ORDERFLOW_VISIBLE_LIMIT
from src.dashboard.helpers import _age_seconds, _json_block, _required, _safe, _short
from src.dashboard.layout import _hero, _layout, _strip_states
from src.dashboard.state import DashboardState

def _signal_research_page(state: DashboardState, data: dict[str, Any], selected_id: str | None) -> str:
    rows, counts, summary, cases, active = _signal_research_rows(state, data)
    _, exception_items = _quality_exception_rows(data)
    with state.lock:
        observations = [dict(item) for item in state.orderflow_observations[-ORDERFLOW_VISIBLE_LIMIT:]]
        validations = [dict(item) for item in state.orderflow_validations]
    selected = next((item for item in observations if str(item.get("observation_id")) == str(selected_id)), None) or (observations[0] if observations else None)
    symbol = data.get("market_status", {}).get("symbol", "BTCUSDT")
    stream_status = data.get("system_health", {}).get("stream", "unknown")
    last_capture = observations[-1].get("observed_at") if observations else data.get("timestamp")
    freshness = _age_seconds(last_capture)
    latest_rule = (selected or {}).get("rule_version") or data.get("readiness", {}).get("schema_version", "MISSING:rule_version")
    pipeline_version = data.get("readiness", {}).get("generator_version") or data.get("research_quality", {}).get("generator_version") or DASHBOARD_VERSION
    quality_summary = data.get("research_quality", {}).get("validation_status") or data.get("readiness", {}).get("validation_status") or "UNKNOWN"
    open_validations = sum(1 for item in validations if not item.get("complete"))
    completed_cases = sum(1 for item in cases if str(item.get("status", "")).upper() == "CLOSED")
    summary_grid = (
        "<div class='meta-grid'>"
        f"<article class='card'><div class='card__label'>Sichtbare Observations</div><div class='card__value'>{counts['shown']}</div><div class='card__note'>Persistierter Ausschnitt</div></article>"
        f"<article class='card'><div class='card__label'>Offene Validierungen</div><div class='card__value'>{open_validations}</div><div class='card__note'>5m / 15m / 30m offen</div></article>"
        f"<article class='card'><div class='card__label'>Abgeschlossene Research Cases</div><div class='card__value'>{completed_cases}</div><div class='card__note'>Retrospektiv geschlossen</div></article>"
        f"<article class='card'><div class='card__label'>Data Quality Summary</div><div class='card__value'>{_safe(quality_summary)}</div><div class='card__note'>Read-only Gate</div></article>"
        f"<article class='card'><div class='card__label'>Modus</div><div class='card__value'>OBSERVE</div><div class='card__note'>No trading / no signals</div></article>"
        "</div>"
    )
    selected_detail = ""
    if selected:
        validation = next((item for item in validations if str(item.get("observation_id")) == str(selected.get("observation_id"))), {})
        evidence = selected.get("evidence", [])
        evidence_names = sorted({str(value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key")) for value in evidence if isinstance(value, dict) and (value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key"))})
        selected_detail = (
            "<section class='panel'><div class='panel__head'><h2>Evidence Card</h2><span class='badge badge--yellow'>DETAIL</span></div>"
            "<div class='detail-grid'><dl class='detail'>"
            f"<dt>observation_id</dt><dd class='mono'>{_safe(selected.get('observation_id'))}</dd>"
            f"<dt>timestamp_utc</dt><dd>{_safe(selected.get('observed_at'))}</dd>"
            f"<dt>symbol</dt><dd>{_safe(selected.get('symbol') or symbol)}</dd>"
            f"<dt>timeframe</dt><dd>{_safe(selected.get('timeframe'))}</dd>"
            f"<dt>observation_type</dt><dd>{_safe(selected.get('kind'))}</dd>"
            f"<dt>rule_id</dt><dd>{_safe(selected.get('rule_id'))}</dd>"
            f"<dt>rule_version</dt><dd>{_safe(selected.get('rule_version'))}</dd>"
            f"<dt>fulfilled_conditions</dt><dd>{_safe(', '.join(evidence_names) or 'MISSING:fulfilled_conditions')}</dd>"
            f"<dt>missing_evidence</dt><dd>{_safe(', '.join(selected.get('missing_evidence', [])) or 'MISSING:missing_evidence')}</dd>"
            f"<dt>validation_status</dt><dd>{_safe('COMPLETE' if validation.get('complete') else 'INCOMPLETE')}</dd>"
            f"<dt>linked_research_case_id</dt><dd>{_safe(selected.get('research_case_id') or 'MISSING:linked_research_case_id')}</dd>"
            f"<dt>integrity_status</dt><dd>{_safe(selected.get('integrity_status') or selected.get('validation_status') or 'MISSING:integrity_status')}</dd>"
            "</dl><div><h3>Rohdaten</h3><pre class='code'>" + _json_block(selected) + "</pre><h3>Evidence</h3><pre class='code'>" + _json_block(evidence) + "</pre></div></div></section>"
        )
    evidence_table = (
        "<section class='panel'><div class='panel__head'><h2>Signal Research</h2><span class='badge badge--yellow'>MANUAL RESEARCH</span></div>"
        "<p class='safety-callout'><b>Kein Trading-Signal:</b> Diese Seite zeigt ausschließlich persistierte Evidenz und historische Validierung. Sie erzeugt keine Buy-/Sell-, Long-/Short- oder Ausführungsempfehlung.</p>"
        "<div class='filters'><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. RISING_CVD_ACTIVITY'></div><div><label>Validierungsstatus</label><select id='filter-status'><option value=''>Alle</option><option value='VALIDATED_CONTEXT'>Validierter Kontext</option><option value='AWAITING_OUTCOME'>Outcome ausstehend</option></select></div><div><label>Zeitraum</label><select id='filter-period'><option value=''>Gesamt</option><option value='1'>24 Stunden</option><option value='7'>7 Tage</option></select></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Timestamp UTC</th><th>Symbol</th><th>Observation ID</th><th>Observation Type</th><th>Timeframe</th><th>Delta</th><th>CVD State</th><th>Buy/Sell Ratio</th><th>Trade Frequency</th><th>Evidence Count</th><th>Missing Evidence Count</th><th>Research Status</th><th>Validation Stage</th><th>Retrospective Outcome</th><th>Data Freshness</th><th>Integrity Status</th><th>Detail</th></tr></thead><tbody>"
        + rows
        + "</tbody></table></div></section>"
    )
    context_matrix = (
        "<section class='panel'><div class='panel__head'><h2>Multi-Timeframe Kontextmatrix</h2><span class='badge badge--green'>DETERMINISTIC</span></div>"
        "<div class='table-wrap'><table><thead><tr><th>Timeframe</th><th>candle_open_time_utc</th><th>price_change_in_window</th><th>candle_range</th><th>volume</th><th>delta_relation</th><th>cvd_relation</th><th>context_state</th></tr></thead><tbody>"
        + _signal_context_rows(data.get("candles", []))
        + "</tbody></table></div><p class='count-scope'>Kontextwerte sind rein deskriptiv. Keine Richtungsempfehlung und keine Prognose.</p></section>"
    )
    retrospective = (
        "<section class='panel'><div class='panel__head'><h2>Retrospective Outcomes</h2><span class='badge badge--yellow'>RETROSPECTIVE</span></div>"
        "<p class='count-scope'>5m-, 15m- und 30m-Outcomes tragen dauerhaft das Label RETROSPECTIVE. Keine prognostische Formulierung.</p>"
        "<div class='table-wrap'><table><thead><tr><th>Observation ID</th><th>Horizon</th><th>Label</th><th>price_change</th><th>delta_change</th><th>cvd_change</th><th>trade_frequency_change</th><th>context_change</th><th>validation_result</th><th>invalidation_reason</th></tr></thead><tbody>"
        + _retrospective_outcome_rows(validations)
        + "</tbody></table></div></section>"
    )
    exceptions_rows, exception_items = _quality_exception_rows(data)
    exceptions = (
        "<section class='panel'><div class='panel__head'><h2>Data Quality Gating</h2><span class='badge badge--red'>EXCEPTIONS</span></div>"
        f"<div class='meta-grid'><article class='card'><div class='card__label'>Current Coverage</div><div class='card__value'>{_safe(data.get('readiness', {}).get('continuous_coverage_percent'))}%</div><div class='card__note'>Continuous coverage</div></article><article class='card'><div class='card__label'>Missing Minutes</div><div class='card__value'>{_safe(data.get('readiness', {}).get('continuous_missing_1m_intervals'))}</div><div class='card__note'>Expected minutes {_safe(data.get('readiness', {}).get('continuous_expected_1m_intervals'))}</div></article><article class='card'><div class='card__label'>Gap Count</div><div class='card__value'>{_safe(data.get('readiness', {}).get('unresolved_new_gap_count'))}</div><div class='card__note'>Open blocker register</div></article><article class='card'><div class='card__label'>Missing AggTrades</div><div class='card__value'>{_safe(sum(1 for item in exception_items if 'AGG' in str(item.get('reason_code', '')).upper()))}</div><div class='card__note'>From exception register</div></article><article class='card'><div class='card__label'>Missing Validation</div><div class='card__value'>{_safe(sum(1 for item in exception_items if 'VALIDATION' in str(item.get('reason_code', '')).upper()))}</div><div class='card__note'>From exception register</div></article></div>"
        "<div class='table-wrap'><table><thead><tr><th>Component</th><th>Status</th><th>Reason Code</th><th>Reason Text</th><th>Time Window</th><th>Provenance</th><th>Linked Report</th><th>Linked Blocker</th></tr></thead><tbody>"
        + exceptions_rows
        + "</tbody></table></div></section>"
    )
    areas = (
        "<div class='queue-grid'>"
        f"<article class='card'><div class='card__label'>Live Research Queue</div><div class='card__value'>{counts['shown'] - counts['validated']}</div><div class='card__note'>Neue oder unvollständige Observations</div></article>"
        f"<article class='card'><div class='card__label'>Validation Queue</div><div class='card__value'>{counts['awaiting']}</div><div class='card__note'>5m / 15m / 30m offen</div></article>"
        f"<article class='card'><div class='card__label'>Completed Research Cases</div><div class='card__value'>{completed_cases}</div><div class='card__note'>Abgeschlossene Fälle</div></article>"
        f"<article class='card'><div class='card__label'>Data Quality Exceptions</div><div class='card__value'>{len(exception_items)}</div><div class='card__note'>Ausgelöste Gate-Events</div></article>"
        "</div>"
    )
    top = (
        "<section class='panel'><div class='signal-header'><div><h2>Globaler Forschungsstatus</h2>"
        "<div class='signal-kicker'><span class='signal-pill'>OBSERVE</span><span class='signal-pill'>READ-ONLY</span><span class='signal-pill'>RESEARCH ONLY</span></div>"
        f"<p class='count-scope'>Symbol {_safe(symbol)} · Stream {_safe(stream_status)} · letzte Erfassung UTC {_safe(last_capture)} · Datenfrische {_safe(freshness)}s</p>"
        f"</div><div class='status-note'><b>Pipeline-Version:</b> {_safe(pipeline_version)}<br><b>Aktuelle Rule-Version:</b> {_safe(latest_rule)}<br><b>Offene Validierungen:</b> {_safe(open_validations)}<br><b>Abgeschlossene Research Cases:</b> {_safe(completed_cases)}<br><span class='muted'>AggTrades · Orderflow Metrics · Signal Research · Kein Trading-Signal · keine Buy-/Sell-, Long-/Short-Entscheidung · keine Ausführung</span></div></div></section>"
    )
    return _layout(
        "Signal Research",
        "Signal Research",
        _hero("Signal Research", "Gefilterter Orderflow-Evidenzpfad für manuelle Forschung.")
        + top
        + summary_grid
        + areas
        + evidence_table
        + selected_detail
        + context_matrix
        + retrospective
        + exceptions,
        strip=_strip_states(data),
    )


def _signal_research_rows(state: DashboardState, data: dict[str, Any] | None = None) -> tuple[str, dict[str, int], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Render a read-only evidence path from already persisted orderflow records."""
    with state.lock:
        observations = [dict(item) for item in state.orderflow_observations[-ORDERFLOW_VISIBLE_LIMIT:]]
        validations = {str(item.get("observation_id")): dict(item) for item in state.orderflow_validations}
        cases = [dict(item) for item in state.research_cases]
        active = [dict(item) for item in state.active_observations]
    counts = {"shown": len(observations), "validated": 0, "awaiting": 0}
    rows: list[str] = []
    for item in reversed(observations):
        validation = validations.get(str(item.get("observation_id")), {})
        complete = bool(validation.get("complete"))
        counts["validated" if complete else "awaiting"] += 1
        evidence = item.get("evidence", [])
        evidence_names = sorted({
            str(value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key"))
            for value in evidence
            if isinstance(value, dict) and (value.get("metric") or value.get("name") or value.get("condition") or value.get("field") or value.get("key"))
        })
        state_label = "VALIDATED_CONTEXT" if complete else "AWAITING_OUTCOME"
        outcome = validation.get("outcome") if complete else None
        observation_id = str(item.get("observation_id", ""))
        delta = item.get("delta") or item.get("net_delta") or item.get("metrics", {}).get("delta")
        cvd = item.get("cvd_state") or item.get("metrics", {}).get("cvd_state")
        ratio = item.get("buy_sell_ratio") or item.get("metrics", {}).get("buy_sell_ratio")
        trade_frequency = item.get("trade_frequency") or item.get("metrics", {}).get("trade_frequency")
        freshness = item.get("freshness_seconds")
        integrity = item.get("integrity_status") or item.get("validation_status") or ("COMPLETE" if complete else "INSUFFICIENT_EVIDENCE")
        rows.append(
            f"<tr data-type='{_safe(item.get('kind'))}' data-status='{state_label}' data-time='{_safe(item.get('observed_at'))}'>"
            f"<td>{_safe(item.get('observed_at'))}</td><td>{_safe(item.get('symbol') or 'BTCUSDT')}</td><td><a class='mono' href='/signals?id={html.escape(observation_id, quote=True)}'>{_safe(_short(observation_id, 14))}</a></td>"
            f"<td><span class='tag'>{_safe(item.get('kind'))}</span></td><td>{_safe(item.get('timeframe'))}</td><td class='mono'>{_safe(_required('delta', delta))}</td><td>{_safe(_required('cvd_state', cvd))}</td><td>{_safe(_required('buy_sell_ratio', ratio))}</td>"
            f"<td>{_safe(_required('trade_frequency', trade_frequency))}</td><td>{len(evidence)}</td><td>{max(0, int(item.get('missing_evidence_count', len(item.get('missing_evidence', []))) or 0))}</td>"
            f"<td>{_safe(item.get('research_status') or item.get('research_case_status') or ('VALIDATED_CONTEXT' if complete else 'AWAITING_OUTCOME'))}</td>"
            f"<td>{_safe(state_label)}</td><td>{_safe(outcome or 'RETROSPECTIVE')}</td><td>{_safe(_required('data_freshness', freshness))}</td>"
            f"<td><span class='badge badge--{'green' if integrity == 'COMPLETE' else 'yellow'}'>{_safe(integrity)}</span></td><td><a href='/signals?id={html.escape(observation_id, quote=True)}'>Details →</a></td></tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='17' class='empty'>Noch keine persistierte Orderflow-Evidenz.</td></tr>")
    summary = {
        "shown": len(observations),
        "validated": counts["validated"],
        "awaiting": counts["awaiting"],
        "open_validations": sum(1 for item in validations.values() if not item.get("complete")),
        "closed_cases": sum(1 for item in cases if str(item.get("status", "")).upper() == "CLOSED"),
        "data_quality_summary": (data or {}).get("readiness", {}).get("validation_status") or (data or {}).get("research_quality", {}).get("validation_status") or "UNKNOWN",
    }
    return "".join(rows), counts, summary, cases, active
