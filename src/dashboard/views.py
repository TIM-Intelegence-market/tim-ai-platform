from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone
from src.dashboard.operations import OPERATIONS_PAGES, render_operations_page

from src.dashboard.components import _case_for_observation, _case_proof_panel, _case_row, _observation_row
from src.dashboard.constants import DASHBOARD_VERSION, ORDERFLOW_VISIBLE_LIMIT
from src.dashboard.helpers import _duration, _json_block, _parse_time, _safe, _short, _status
from src.dashboard.layout import _hero, _layout, _strip_states
from src.dashboard.pages.operations import _data_quality_exceptions_page, _health_center_sections, _health_timeline_page
from src.dashboard.pages.setup_path import _setup_path_page
from src.dashboard.pages.signals import _signal_research_page
from src.dashboard.state import DashboardState

def render(state: DashboardState, page: str = "Overview", selected_id: str | None = None) -> str:
    data = state.snapshot()
    validator = data["validator"]
    if page == "Setup Path":
        return _setup_path_page(data)
    if page in OPERATIONS_PAGES and page != "Overview":
        return _layout(page, page, render_operations_page(page, data["operations"]), strip=_strip_states(data))
    if page == "Orderflow":
        with state.lock:
            total_orderflow=len(state.orderflow_observations)
            observations=[dict(item) for item in state.orderflow_observations[-ORDERFLOW_VISIBLE_LIMIT:]]
            validations={str(item.get("observation_id")):dict(item) for item in state.orderflow_validations}
        selected=next((item for item in observations if str(item.get("observation_id"))==str(selected_id)),None)
        rows="".join(f"<tr data-type='{_safe(item.get('kind'))}' data-rule='{_safe(item.get('rule_version'))}' data-time='{_safe(item.get('observed_at'))}'><td>{_safe(item.get('observed_at'))}</td><td><a class='mono' href='/orderflow?id={_safe(item.get('observation_id'))}'>{_safe(_short(item.get('observation_id'),18))}</a></td><td><span class='tag'>{_safe(item.get('kind'))}</span></td><td>{_safe(item.get('timeframe'))}</td><td>{len(item.get('evidence',[]))}</td><td>{len(validations.get(str(item.get('observation_id')),{}).get('horizons',[]))}/3</td><td>{_safe(validations.get(str(item.get('observation_id')),{}).get('outcome') or 'PENDING')}</td><td class='mono'>{_safe(item.get('rule_version'))}</td></tr>" for item in reversed(observations)) or "<tr><td colspan='8' class='empty'>Noch keine Orderflow-Observations.</td></tr>"
        detail=""
        if selected:
            validation=validations.get(str(selected.get("observation_id")),{})
            detail=f"<section class='panel'><div class='panel__head'><h2>Observation &amp; Outcome Detail</h2><span class='badge badge--green'>READ-ONLY</span></div><div class='detail-grid'><dl class='detail'><dt>ID</dt><dd class='mono'>{_safe(selected.get('observation_id'))}</dd><dt>Beschreibung</dt><dd>{_safe(selected.get('summary'))}</dd><dt>Rule Version</dt><dd>{_safe(selected.get('rule_version'))}</dd><dt>Input Hash</dt><dd class='mono'>{_safe(selected.get('input_hash'))}</dd><dt>Outcome</dt><dd>{_safe(validation.get('outcome') or 'PENDING')}</dd><dt>Validated Through</dt><dd>{_safe(validation.get('validated_through'))}</dd></dl><div><h3>Evidenzbedingungen</h3><pre class='code'>{_json_block(selected.get('evidence'))}</pre><h3>5/15/30-Minuten-Verlauf</h3><pre class='code'>{_json_block(validation.get('horizons',[]))}</pre></div></div></section>"
        body=_hero("Orderflow Research","Deterministische Beschreibungen und nachgelagerte 5/15/30-Minuten-Outcomes.")+f"<section class='panel'><div class='panel__head'><h2>Persistierte Orderflow-Observations</h2><span class='count-scope'>neueste {len(observations)} von {total_orderflow}</span></div><div class='filters'><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. STRONG_BUYER_ACTIVITY'></div><div><label>Rule Version</label><input id='filter-rule' placeholder='1.0.0'></div><div><label>Zeitraum</label><select id='filter-period'><option value=''>Gesamt</option><option value='1'>24 Stunden</option><option value='7'>7 Tage</option></select></div></div><div class='table-wrap'><table><thead><tr><th>Timestamp</th><th>Observation ID</th><th>Type</th><th>Timeframe</th><th>Evidence</th><th>Horizonte</th><th>Outcome</th><th>Rule Version</th></tr></thead><tbody>{rows}</tbody></table></div><p class='count-scope'>Der sichtbare Ausschnitt ist bewusst auf {ORDERFLOW_VISIBLE_LIMIT} Einträge begrenzt. Outcomes dokumentieren beobachtete Preisentwicklung; keine Prognose.</p></section>{detail}"
        return _layout("Orderflow Research",page,body,strip=_strip_states(data))
    if page == "Signal Research":
        return _signal_research_page(state, data, selected_id)
    if page == "Analytics":
        analytics = state.analytics()
        rules = "".join(f"<tr><td>{_safe(x['rule_id'])}</td><td class='mono'>{_safe(x['version'])}</td><td>{x['count']}</td><td>{_safe(x['first_occurrence'])}</td><td>{_safe(x['last_occurrence'])}</td><td>{x['average_duration_seconds']}</td><td>{x['average_timeframes_per_case']}</td><td>{_safe(', '.join(x['most_common_missing_evidence']))}</td><td>{_safe(', '.join(x['most_common_outcomes']))}</td><td>{x['confirmed_rate_percent']}%</td><td>{x['invalidation_rate_percent']}%</td><td>{x['closed_rate_percent']}%</td><td>{x['average_lifetime_seconds']}</td></tr>" for x in analytics["rules"]) or "<tr><td colspan='13' class='empty'>Keine persistierten Rule-Daten.</td></tr>"
        clusters = "".join(f"<tr><td>{_safe(x['observation_type'])}</td><td>{_safe(x['rule_version'])}</td><td>{_safe(x['outcome'])}</td><td>{_safe(', '.join(x['missing_evidence']))}</td><td>{_safe(x['stored_evidence_score'])}</td><td>{_safe(x['timeframe'])}</td><td>{x['count']}</td></tr>" for x in analytics["case_clusters"]) or "<tr><td colspan='7' class='empty'>Keine Cluster verfügbar.</td></tr>"
        days = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["research_cases_per_day"].items()) or "<tr><td colspan='2' class='empty'>Keine Timeline-Daten.</td></tr>"
        hours = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["research_cases_per_hour"].items()) or "<tr><td colspan='2' class='empty'>Keine Timeline-Daten.</td></tr>"
        obs_frequency = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["observation_frequency"].items()) or "<tr><td colspan='2' class='empty'>Keine Observations.</td></tr>"
        outcome_frequency = "".join(f"<tr><td>{_safe(label)}</td><td>{count}</td></tr>" for label, count in analytics["timeline"]["outcome_frequency"].items()) or "<tr><td colspan='2' class='empty'>Keine persistierten Outcomes.</td></tr>"
        quality = "".join(f"<article class='card'><div class='card__label'>{_safe(key.replace('_',' '))}</div><div class='card__value'>{value}</div><div class='card__note'>Persistierte Ereignisse</div></article>" for key, value in analytics["data_quality"].items())
        body = _hero("Research Analytics", "Deterministische Statistik über bereits persistierte Research-Daten.")
        body += f"<p class='observe'>OBSERVE • READ-ONLY • Dataset <span class='mono'>{_safe(_short(analytics['dataset_hash'],16))}</span></p><section class='panel'><div class='panel__head'><h2>Exporte</h2><div><a class='tag' href='/exports/analytics.csv'>CSV</a> <a class='tag' href='/exports/analytics.json'>JSON</a> <a class='tag' href='/exports/analytics.md'>Markdown</a></div></div><p class='count-scope'>{analytics['source_counts']['observations']} persistierte Observations · {analytics['source_counts']['research_cases']} Research Cases · {analytics['source_counts']['events']} Systemereignisse. Keine Prognosen, Rankings oder neu berechneten Scores.</p></section>"
        body += f"<section class='panel'><h2>Rule Analytics</h2><div class='table-wrap'><table><thead><tr><th>Rule</th><th>Version</th><th>Anzahl</th><th>Erstes Auftreten</th><th>Letztes Auftreten</th><th>Ø Dauer s</th><th>Ø Timeframes/Case</th><th>Häufigste Missing Evidence</th><th>Häufigste Outcomes</th><th>Confirmed</th><th>Invalidiert</th><th>Closed</th><th>Ø Lifetime s</th></tr></thead><tbody>{rules}</tbody></table></div></section>"
        body += f"<section class='panel'><h2>Case Cluster</h2><div class='table-wrap'><table><thead><tr><th>Observation Type</th><th>Rule Version</th><th>Outcome</th><th>Missing Evidence</th><th>Gespeicherter Evidence Score</th><th>Timeframe</th><th>Anzahl</th></tr></thead><tbody>{clusters}</tbody></table></div><p class='count-scope'>Evidence Score ist ausschließlich der persistierte Wert; Analytics berechnet keinen neuen Score.</p></section>"
        body += f"<div class='research-grid'><section class='panel'><h2>Cases pro Tag</h2><div class='table-wrap'><table><thead><tr><th>Tag (UTC)</th><th>Anzahl</th></tr></thead><tbody>{days}</tbody></table></div></section><section class='panel'><h2>Cases pro Stunde</h2><div class='table-wrap'><table><thead><tr><th>Stunde (UTC)</th><th>Anzahl</th></tr></thead><tbody>{hours}</tbody></table></div></section><section class='panel'><h2>Observation-Häufigkeit</h2><div class='table-wrap'><table><thead><tr><th>Observation Type</th><th>Anzahl</th></tr></thead><tbody>{obs_frequency}</tbody></table></div></section><section class='panel'><h2>Outcome-Häufigkeit</h2><div class='table-wrap'><table><thead><tr><th>Outcome</th><th>Anzahl</th></tr></thead><tbody>{outcome_frequency}</tbody></table></div></section></div><section class='panel'><h2>Data Quality Analytics</h2><div class='grid'>{quality}</div></section>"
        return _layout("Research Analytics", page, body, strip=_strip_states(data))
    if page == "Insights":
        insights = state.insights()
        badge = "green" if insights["eligibility_status"] == "ELIGIBLE" else "yellow"
        outcome_rows = "".join(
            f"<tr><td>{_safe(item['observation_type'])}</td><td class='mono'>{_safe(item['versions']['rule'])}</td><td>{item['fully_validated_cases']}</td><td>{item['outcomes']['PRICE_INCREASED']}</td><td>{item['outcomes']['PRICE_DECREASED']}</td><td>{item['outcomes']['PRICE_SIDEWAYS']}</td><td><span class='badge badge--yellow'>{_safe(item['sample_label'])}</span></td></tr>"
            for item in insights["outcome_distribution"]
        ) or "<tr><td colspan='7' class='empty'>Keine auswertbaren Orderflow-Observations.</td></tr>"
        followup_rows = []
        for item in insights["followup_statistics"]:
            for horizon in item["horizons"]:
                price, delta = horizon["price_change_percent"], horizon["net_delta"]
                followup_rows.append(f"<tr><td>{_safe(item['observation_type'])}</td><td>{horizon['minutes']}m</td><td>{_safe(price.get('n') if price else None)}</td><td>{_safe(price.get('median') if price else None)}</td><td>{_safe(price.get('mean') if price else None)}</td><td>{_safe(price.get('percentile_25') if price else None)} / {_safe(price.get('percentile_75') if price else None)}</td><td>{_safe(delta.get('median') if delta else None)}</td><td>{_safe(delta.get('mean') if delta else None)}</td></tr>")
        combination_rows = "".join(
            f"<tr><td>{_safe(item['observation_type'])}</td><td>{item['count']}</td><td class='mono'>{_safe(item['rule_version'])}</td><td>{_safe(' + '.join(item['evidence']))}</td><td>{item['outcomes']['PRICE_INCREASED']} / {item['outcomes']['PRICE_DECREASED']} / {item['outcomes']['PRICE_SIDEWAYS']}</td><td>{_safe(item['sample_label'])}</td></tr>"
            for item in insights["evidence_combinations"][:30]
        ) or "<tr><td colspan='6' class='empty'>Keine Evidenzkombinationen.</td></tr>"
        session_rows = "".join(f"<tr><td>{_safe(name)}</td><td>{count}</td></tr>" for name, count in insights["temporal_distribution"]["market_session"].items()) or "<tr><td colspan='2' class='empty'>Keine zeitlichen Daten.</td></tr>"
        warnings = "".join(f"<li>{_safe(item)}</li>" for item in insights["warnings"]) or "<li>Keine Warnungen.</li>"
        versions = insights["versions"]
        body = _hero("Research Insights", "Retrospektive, versionsgetrennte Statistik über vollständig persistierte Forschungsergebnisse.")
        body += f"<p class='observe'>EXTERNAL TO CORE • READ-ONLY • NO FORECASTS • Dataset <span class='mono'>{_safe(_short(insights['input_hash'],16))}</span></p><div class='grid'><article class='card'><div class='card__label'>Eligibility</div><div class='card__value'><span class='badge badge--{badge}'>{_safe(insights['eligibility_status'])}</span></div><div class='card__note'>{_safe(insights['result_status'])}</div></article><article class='card'><div class='card__label'>Fully Validated</div><div class='card__value'>{insights['eligibility']['fully_validated_cases']}</div><div class='card__note'>Minimum für Eligibility: 1.000</div></article><article class='card'><div class='card__label'>Versionen</div><div class='card__value mono'>{_safe(versions['core'])}</div><div class='card__note'>Metrics {_safe(', '.join(versions['metrics']))} · Rules {_safe(', '.join(versions['rules']))} · Validation {_safe(', '.join(versions['validations']))}</div></article><article class='card'><div class='card__label'>Integrity</div><div class='card__value'>{_safe(insights['data_quality']['integrity_status'])}</div><div class='card__note'>Replay {_safe(insights['data_quality']['replay_status'])} · Coverage {_safe(insights['data_quality']['coverage_percent'])}</div></article></div>"
        body += f"<section class='panel'><div class='panel__head'><h2>Exporte</h2><div><a class='tag' href='/exports/insights.json'>JSON</a> <a class='tag' href='/exports/insights.csv'>CSV</a> <a class='tag' href='/exports/insights.md'>Markdown</a></div></div><ul>{warnings}</ul></section>"
        body += f"<section class='panel'><h2>Outcome-Verteilungen</h2><div class='table-wrap'><table><thead><tr><th>Observation</th><th>Rule</th><th>N vollständig</th><th>Price Increased</th><th>Price Decreased</th><th>Price Sideways</th><th>Sample</th></tr></thead><tbody>{outcome_rows}</tbody></table></div></section>"
        body += f"<section class='panel'><h2>Folgeverläufe</h2><p class='count-scope'>Mittelwert wird stets zusammen mit Median und N dargestellt. Keine kausale Interpretation.</p><div class='table-wrap'><table><thead><tr><th>Observation</th><th>Horizont</th><th>N</th><th>Median Preis %</th><th>Mittel Preis %</th><th>Q25 / Q75</th><th>Median Delta</th><th>Mittel Delta</th></tr></thead><tbody>{''.join(followup_rows)}</tbody></table></div></section>"
        body += f"<section class='panel'><h2>Evidenzkombinationen</h2><div class='table-wrap'><table><thead><tr><th>Observation</th><th>Anzahl</th><th>Rule</th><th>Evidenz</th><th>Outcomes I / D / S</th><th>Sample</th></tr></thead><tbody>{combination_rows}</tbody></table></div></section><section class='panel'><h2>Market Sessions (UTC)</h2><p class='count-scope'>ASIA 00–08 · EUROPE 08–16 · USA 16–24 UTC. Feste deskriptive Einteilung.</p><div class='table-wrap'><table><thead><tr><th>Session</th><th>Observations</th></tr></thead><tbody>{session_rows}</tbody></table></div></section>"
        return _layout("Research Insights", page, body, strip=_strip_states(data))
    if page == "Observations":
        selected = next((item for item in data["observations"] if str(item.get("observation_id")) == str(selected_id)), None)
        rows = "".join(_observation_row(item, data["research_cases"]) for item in reversed(data["observations"])) or "<tr><td colspan='7' class='empty'>No observations yet</td></tr>"
        detail = ""
        if selected:
            case = _case_for_observation(selected, data["research_cases"])
            detail = f"<section class='panel'><div class='panel__head'><h2>Observation Detail</h2><span class='badge badge--green'>READ-ONLY</span></div><div class='detail-grid'><dl class='detail'><dt>Observation ID</dt><dd class='mono'>{_safe(selected.get('observation_id'))}</dd><dt>Timestamp</dt><dd>{_safe(selected.get('observed_at'))}</dd><dt>Type</dt><dd>{_safe(selected.get('kind'))}</dd><dt>Rule</dt><dd>{_safe(selected.get('rule_id'))} · {_safe(selected.get('rule_version'))}</dd><dt>Provenance</dt><dd>{_safe(selected.get('provenance'))}</dd><dt>Research Case</dt><dd>{_safe(case.get('case_id') if case else None)}</dd><dt>Hash</dt><dd class='mono'>{_safe(selected.get('input_hash'))}</dd></dl><div><h3>Evidence / Rohdaten</h3><pre class='code'>{_json_block(selected.get('evidence'))}</pre></div></div><h3>Vollständige Observation</h3><pre class='code'>{_json_block(selected)}</pre></section>"
        body = _hero("Observation Explorer", "Deterministische Beobachtungen mit Evidenz und Provenance.") + f"<section class='panel'><div class='panel__head'><h2>Active Observations</h2><span class='count-scope'>sichtbarer Ausschnitt: {len(data['observations'])}</span></div><div class='filters'><div><label>Status</label><select id='filter-status'><option value=''>Alle</option><option>OPEN</option><option>MONITORING</option><option>CONFIRMED</option><option>INVALIDATED</option><option>CLOSED</option><option>UNASSIGNED</option></select></div><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. REJECTION'></div><div><label>Rule Version</label><input id='filter-rule' placeholder='z. B. 1.0.0'></div></div><div class='table-wrap'><table><thead><tr><th>Timestamp</th><th>Observation ID</th><th>Observation Type</th><th>Rule Version</th><th>Evidence Score</th><th>Provenance</th><th>Status</th></tr></thead><tbody id='observations-body'>{rows}</tbody></table></div><p class='count-scope'>Evidence Score entspricht der gespeicherten deterministischen Confidence; keine neue Bewertung wird erzeugt.</p></section>{detail}"
        return _layout("Observation Explorer", page, body, strip=_strip_states(data))
    if page == "Research Cases":
        selected = next((item for item in data["research_cases"] if str(item.get("case_id")) == str(selected_id)), None)
        rows = "".join(_case_row(item) for item in reversed(data["research_cases"])) or "<tr><td colspan='8' class='empty'>keine materialisierten Research Cases vorhanden</td></tr>"
        counts = data.get("case_counts", {})
        confirmed = int(counts.get("confirmed", 0) or 0)
        collecting = int(counts.get("collecting_evidence", 0) or 0)
        total = int(counts.get("total", 0) or 0)
        if confirmed == 0 and collecting > 0:
            progress = f"0 confirmed, aber {collecting} collecting evidence"
        elif total == 0:
            progress = "0 confirmed, 0 collecting evidence — derzeit keine materialisierten Research Cases"
        else:
            progress = f"{confirmed} confirmed · {collecting} collecting evidence · {total} total"
        summary = (
            "<div class='grid case-status-summary'>"
            f"<article class='card'><div class='card__label'>Confirmed</div><div class='card__value'>{confirmed}</div><div class='card__note'>wissenschaftlich bestätigte Cases</div></article>"
            f"<article class='card'><div class='card__label'>Collecting Evidence</div><div class='card__value'>{collecting}</div><div class='card__note'>OPEN / MONITORING / COLLECTING_EVIDENCE</div></article>"
            f"<article class='card'><div class='card__label'>Total Cases</div><div class='card__value'>{total}</div><div class='card__note'>persistierte Research Cases</div></article>"
            "</div>"
            f"<p class='observe case-progress'>{_safe(progress)}</p>"
        )
        detail = ""
        if selected:
            timeline = "".join(f"<li><time>{_safe(item.get('observed_at'))}</time><span class='tag'>{_safe(item.get('kind'))}</span><span class='mono'>{_safe(_short(item.get('observation_id'), 14))}</span></li>" for item in selected.get("evidence", [])) or "<li class='empty'>Keine Evidenz-Timeline.</li>"
            reviews = "".join(f"<li><time>{_safe(item.get('at'))}</time><span class='tag'>{_safe(item.get('to'))}</span><span>{_safe(item.get('reason'))}</span></li>" for item in selected.get("review_history", []) or []) or "<li class='empty'>Noch kein Review.</li>"
            case_hash = hashlib.sha256(json.dumps({"case_id": selected.get("case_id"), "observation_ids": selected.get("observation_ids", []), "rule_versions": selected.get("rule_versions", {})}, sort_keys=True).encode()).hexdigest()[:16]
            rules = ", ".join(f"{key}:{value}" for key, value in sorted((selected.get("rule_versions", {}) or {}).items())) or "—"
            detail = f"<section class='panel'><div class='panel__head'><h2>Case Detail</h2><span class='badge badge--green'>READ-ONLY</span></div><div class='detail-grid'><dl class='detail'><dt>Case ID</dt><dd class='mono'>{_safe(selected.get('case_id'))}</dd><dt>Status</dt><dd>{_safe(selected.get('status'))}</dd><dt>Dauer</dt><dd>{_safe(_duration(selected.get('opened_at'),selected.get('updated_at')))}</dd><dt>Outcome</dt><dd>{_safe(selected.get('outcome'))}</dd><dt>Missing Evidence</dt><dd>{_safe(', '.join(selected.get('missing_evidence', [])))}</dd><dt>Rule Versions</dt><dd class='mono'>{_safe(rules)}</dd><dt>Case Hash</dt><dd class='mono'>casehash:{_safe(case_hash)}</dd></dl><div><h3>Timeline</h3><ul class='timeline'>{timeline}</ul><h3>Review History</h3><ul class='timeline'>{reviews}</ul></div></div></section>"
            with state.lock:
                orderflow_observations = [dict(item) for item in state.orderflow_observations]
                orderflow_validations = [dict(item) for item in state.orderflow_validations]
            detail += _case_proof_panel(selected, orderflow_observations, orderflow_validations)
        stand = f"<p class='count-scope'>Datenstand: {_safe(data.get('timestamp'))} · Builder: ResearchCaseEngine/30min-Fenster · Quelle: OBSERVE-only Laufzeit</p>"
        body = _hero("Research Case Explorer", "Case-Lifecycle, fehlende Evidenz und reproduzierbare Timeline.") + f"<section class='panel'><div class='panel__head'><h2>Research Cases &amp; Missing Evidence</h2><span class='count-scope'>sichtbarer Ausschnitt: {len(data['research_cases'])}</span></div>" + summary + f"<div class='filters'><div><label>Status</label><select id='filter-status'><option value='' selected>Alle aktiven / alle Status</option><option>OPEN</option><option>MONITORING</option><option>COLLECTING_EVIDENCE</option><option>READY_FOR_REVIEW</option><option>CONFIRMED</option><option>REJECTED</option><option>QUARANTINED</option><option>INVALIDATED</option><option>CLOSED</option></select></div><div><label>Zeitraum</label><select id='filter-period'><option value=''>Gesamt</option><option value='1'>24 Stunden</option><option value='7'>7 Tage</option><option value='30'>30 Tage</option></select></div><div><label>Observation Type</label><input id='filter-type' placeholder='z. B. BOS'></div><div><label>Rule Version</label><input id='filter-rule' placeholder='z. B. 1.0.0'></div></div><div class='table-wrap'><table><thead><tr><th>Case</th><th>Status</th><th>Dauer</th><th>Observations</th><th>Outcome</th><th>Missing Evidence</th><th>Types</th><th>Rule Version</th></tr></thead><tbody id='cases-body'>{rows}</tbody></table></div>{stand}</section>{detail}"
        return _layout("Research Case Explorer", page, body, strip=_strip_states(data))
    if page == "Health Center":
        body = _hero("Health Center", "Zentrales Diagnosezentrum für Betrieb, Wissenschaft und Governance.")
        body += "<p class='count-scope'>Karten öffnen, um Ursache, Zeitpunkt, Evidenz, Auswirkung und nächsten Schritt zu sehen. Statuswerte werden nicht synthetisch ergänzt.</p>"
        body += _health_center_sections(data)
        return _layout("Health Center", page, body, strip=_strip_states(data))
    if page == "Data Quality Exceptions":
        return _data_quality_exceptions_page(data)
    if page == "Timeline":
        return _health_timeline_page(data)
    if page == "Research":
        research = validator.get("research_health", {})
        body = _hero("Research Evidence", "Lokale, dokumentierte TIM-Evidenz ohne schreibende UI-Aktionen.") + f"<div class='grid'><article class='card'><div class='card__label'>Research Integrity</div><div class='card__value'><span class='badge badge--{_status(research.get('level')).lower()}'>{_safe(research.get('level'))}</span></div><div class='card__note'>{_safe(research.get('trigger_duplicates', 0))} Trigger-Duplikate</div></article><article class='card'><div class='card__label'>Mode</div><div class='card__value'>OBSERVE</div><div class='card__note'>Keine Multi-Agent-Ausführung</div></article></div><section class='panel'><div class='panel__head'><h2>Read-only Research Index</h2><span class='badge badge--green'>NO WRITE CONTROLS</span></div><p>Die Control-Center-Oberfläche erzeugt, verändert oder signiert keine Research-Artefakte. Persistierte Evidenz bleibt über die spezialisierten Ansichten lesbar.</p><div class='quick-links'><a href='/observations'>Observations</a><a href='/cases'>Research Cases</a><a href='/signals'>Signal Research</a><a href='/analytics'>Analytics</a><a href='/insights'>Insights</a></div></section>"
        return _layout("Research Workspace", page, body, strip=_strip_states(data))
    readiness = data["readiness"]
    audit = data.get("research_audit", {})
    quality = data.get("research_quality", {})
    health_level = str(validator.get("health_monitor", {}).get("level", "YELLOW")).upper()
    started = _parse_time(validator.get("started_at"))
    runtime = _duration(started.isoformat() if started else None, datetime.now(timezone.utc).isoformat())
    checks = validator.get("health_monitor", {}).get("checks", {})
    candle_gap_free = bool(checks.get("candle_sequence_gap_free", True))
    provenance_deterministic = bool(checks.get("provenance_deterministic", True))
    data_quality_level = "RED" if not candle_gap_free else str(
        readiness.get("scientific_health_status")
        or quality.get("status")
        or audit.get("status")
        or "UNKNOWN"
    ).upper()
    data_quality_note = (
        f"Persistierte Sequenz, Zeitstempel und Provenance. "
        f"Coverage {_safe(readiness.get('continuous_coverage_percent'))}% · "
        f"Gap {_safe(readiness.get('unresolved_new_gap_count'))} · "
        f"Audit {_safe(audit.get('status'))} · Quality {_safe(quality.get('status'))}"
    )
    validator_level = str(validator.get("status") or validator.get("health_monitor", {}).get("level") or "UNKNOWN").upper()
    # Levels come from operator JSON files and are used in class attributes and text: escape them.
    health_level, data_quality_level, validator_level = (html.escape(level, quote=True) for level in (health_level, data_quality_level, validator_level))
    validator_note = (
        f"{_safe(validator.get('cycles', 0))} persistierte Zyklen · "
        f"letzte Prüfung {_safe(validator.get('research_last_check'))}"
    )
    cards = [
        ("Acceptance Countdown", f"<span id='acceptance-state' class='badge badge--{health_level.lower()}'>{_safe(validator.get('acceptance',{}).get('status','monitoring')).upper()} • {health_level}</span>", f"<span id='acceptance-countdown'>Deadline wird geladen</span>"),
        ("Data Quality", f"<span class='badge badge--{data_quality_level.lower()}'>{data_quality_level}</span>", _safe(data_quality_note)),
        ("Stream Status", _safe(data.get("system_health", {}).get("stream")), "Öffentliche Marktdaten"),
        ("Validator Status", f"<span class='badge badge--{validator_level.lower()}'>{_safe(validator.get('status'))}</span>", f"<span id='validator-cycles'>{validator.get('cycles',0)}</span> persistierte Zyklen."),
        ("Runtime", f"<span id='runtime'>{_safe(runtime)}</span>", f"Restart Count: {validator.get('restart_count',0)}"),
        ("Active Research Cases", f"<span id='case-active'>{data['case_counts']['active']}</span>", "Persistierter Case-Status"),
        ("Closed Research Cases", f"<span id='case-closed'>{data['case_counts']['closed']}</span>", "Persistierter Case-Status"),
        ("Candles (sichtbar)", f"<span id='visible-candles'>{len(data['candles'])}</span>", "Letzter persistierter Ausschnitt"),
        ("Observations", f"<span id='memory-observations'>{data['memory_status'].get('observations',len(data['observations']))}</span>", "Persistierter Memory-Zähler"),
        ("Dashboard Version", DASHBOARD_VERSION, "Read-only Research UI"),
    ]
    card_html = "".join(f"<article class='card'><div class='card__label'>{label}</div><div class='card__value'>{value}</div><div class='card__note'>{note}</div></article>" for label, value, note in cards)
    recent_obs = "".join(_observation_row(item, data["research_cases"]) for item in reversed(data["observations"][-8:])) or "<tr><td colspan='7' class='empty'>No observations yet</td></tr>"
    case_preview = "".join(_case_row(item) for item in reversed(data["research_cases"][-5:])) or "<tr><td colspan='8' class='empty'>No research cases yet</td></tr>"
    readiness=data["readiness"];criteria_rows="".join(f"<tr><td>{_safe(name)}</td><td><span class='badge badge--{_status(status).lower()}'>{_safe(status)}</span></td></tr>" for name,status in sorted(readiness.get("criteria",{}).items())) or "<tr><td colspan='2' class='empty'>Statusdatei noch nicht verfügbar.</td></tr>"
    readiness_panel=f"<section class='panel'><div class='panel__head'><h2>Scientific Data Progress &amp; V2 Readiness</h2><span class='badge badge--{_status(readiness.get('readiness_status')).lower()}'>{_safe(readiness.get('readiness_status'))}</span></div><div class='grid'><article class='card'><div class='card__label'>Validierte Cases</div><div class='card__value'>{_safe(readiness.get('validated_case_count'))} / {_safe(readiness.get('required_case_count'))}</div><div class='card__note'>{_safe(readiness.get('validated_case_progress_percent'))}% · {_safe(readiness.get('remaining_case_count'))} verbleibend</div></article><article class='card'><div class='card__label'>Offene Cases</div><div class='card__value'>{_safe(readiness.get('open_case_count'))}</div><div class='card__note'>{_safe(readiness.get('observation_count'))} Observationen gesamt</div></article><article class='card'><div class='card__label'>Neue Continuous Coverage</div><div class='card__value'>{_safe(readiness.get('continuous_coverage_percent'))}%</div><div class='card__note'>{_safe(readiness.get('continuous_persisted_1m_intervals'))} / {_safe(readiness.get('continuous_expected_1m_intervals'))} Minuten</div></article><article class='card'><div class='card__label'>Gemessener Verlauf</div><div class='card__value'>{_safe(readiness.get('measured_validated_cases_per_hour'))}/h</div><div class='card__note'>{_safe(readiness.get('measured_validated_cases_per_day'))}/Tag · Hochrechnung unverbindlich: {_safe(readiness.get('nonbinding_projected_1000_case_time'))}</div></article></div><details class='readiness'><summary>Alle Freigabekriterien anzeigen</summary><div class='table-wrap'><table><thead><tr><th>Freigabekriterium</th><th>Status</th></tr></thead><tbody>{criteria_rows}</tbody></table></div></details><p class='count-scope'>TIM startet V2 niemals automatisch. Die endgültige Freigabe erfordert einen manuellen Evolution Review.</p></section>"
    research_overview = _hero("TIM Research Dashboard", "Research Overview · deterministischer Systemzustand und aktuelle Research-Aktivität.") + f"<p class='observe'>OBSERVE MODE • {data['safety']}</p>{readiness_panel}<section class='panel'><div class='panel__head'><h2>Market Status</h2><span class='badge badge--green'>{_safe(data['market_status'].get('status'))}</span></div><p class='count-scope'><b>Zählerbereich:</b> sichtbarer letzter Ausschnitt, keine Gesamtzahlen. Sichtbare Candles: <span id='candles-count'>{len(data['candles'])}</span> · Sichtbare Observations: <span id='obs-count'>{len(data['observations'])}</span> · Sichtbare Cases: <span id='cases-count'>{len(data['research_cases'])}</span></p></section><div class='grid'>{card_html}<article class='card'><div class='card__label'>Research Module</div><div class='card__value'><span id='research-health' class='badge badge--{_status(validator.get('research_health',{}).get('level')).lower()}'>{_safe(validator.get('research_health',{}).get('level'))}</span></div><div class='card__note'><a href='/research'>Research Workspace öffnen →</a></div></article></div><section class='panel'><div class='panel__head'><h2>Active Observations</h2><a href='/observations'>Alle öffnen →</a></div><div class='table-wrap'><table><thead><tr><th>Timestamp</th><th>Observation ID</th><th>Observation Type</th><th>Rule Version</th><th>Evidence Score</th><th>Provenance</th><th>Status</th></tr></thead><tbody id='observations-body'>{recent_obs}</tbody></table></div></section><section class='panel'><div class='panel__head'><h2>Research Cases &amp; Missing Evidence</h2><a href='/cases'>Alle öffnen →</a></div><div class='table-wrap'><table><thead><tr><th>Case</th><th>Status</th><th>Dauer</th><th>Observations</th><th>Outcome</th><th>Missing Evidence</th><th>Types</th><th>Rule Version</th></tr></thead><tbody id='cases-body'>{case_preview}</tbody></table></div></section><section class='panel'><h2>News</h2><p class='muted'>Keine autorisierte News-Ingestion aktiv. Es werden keine Nachrichten erfunden oder ergänzt.</p></section>"
    body = render_operations_page("Overview", data["operations"]) + "<details class='panel readiness'><summary>Vertiefende Research-Übersicht anzeigen</summary>" + research_overview + "</details>"
    return _layout("Research Overview", page, body, strip=_strip_states(data))
