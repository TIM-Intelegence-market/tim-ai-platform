import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

import pytest

from src.dashboard.app import DashboardServer, DashboardState, _age_seconds, render


def populated_state(tmp_path: Path) -> DashboardState:
    validator=tmp_path/"state.json";validator.write_text(json.dumps({"status":"RUNNING","cycles":406,"last_cycle_at":"2026-07-20T14:00:00+00:00"}))
    return DashboardState(
        recent_candles=[{"symbol":"BTCUSDT","timeframe":"1m","open_time":"2026-07-20T14:00:00+00:00","close_time":"2026-07-20T14:01:00+00:00","open":100,"high":102,"low":99,"close":101,"volume":5,"trade_count":10,"provenance":"PUBLIC_MARKET_DATA"}],
        active_observations=[{"kind":"BOS_BEARISH","timeframe":"1m","confidence":75,"summary":"Deterministic observation"}],
        research_cases=[{"case_id":"case-1","status":"OPEN","missing_evidence":["confirmation"],"evidence":[]}],
        validator_path=validator,
    )


def test_dashboard_renders_empty_research_state_safely() -> None:
    page = render(DashboardState())
    assert "Market Status" in page
    assert "Active Observations" in page
    assert "Research Cases &amp; Missing Evidence" in page
    assert "News" in page
    assert "NO ORDERS OR EXECUTION" in page
    assert "fetch('/api/state'" in page
    assert "INTERVAL_MS = 5000" in page
    assert "observations-body" in page
    assert "OBSERVE MODE" in page
    assert "MAX_RETRIES = 3" in page
    assert "visibilitychange" in page
    assert "if (document.hidden) status('paused', 'Pausiert – Tab im Hintergrund')" in page
    assert "else { retries = 0; poll(); }" in page
    assert "automatischer Wiederherstellungsversuch" in page
    assert "paused = true" not in page
    assert "Acceptance Countdown" in page
    assert "acceptance-countdown" in page
    assert "countdown(data.validator.deadline)" in page
    assert "Research Module" in page
    assert "Scientific Data Progress &amp; V2 Readiness" in page
    assert "research-health" in page
    assert "/api/research/quick" in page and "/api/research/deep" in page
    assert "innerHTML" not in page


def test_dashboard_serves_html_and_json() -> None:
    server = DashboardServer(DashboardState(), port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
            assert response.status == 200
            assert b"TIM Research Dashboard" in response.read()
        with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as response:
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-cache, no-store, must-revalidate"
            body=response.read()
            assert b"RESEARCH ONLY" in body
            assert b'"mode": "OBSERVE"' in body
            assert b'"provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC"' in body
            assert b'"validator"' in body
        with urlopen(f"http://127.0.0.1:{port}/api/readiness", timeout=2) as response:
            assert response.status==200
        with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            health=json.loads(response.read())
            assert health["mode"]=="OBSERVE"
            assert set(health)=={"governance","historical_scientific","mode","operational","timestamp"}
    finally:
        server.stop()


def test_api_contract_uses_real_tim_field_names(tmp_path: Path) -> None:
    data=populated_state(tmp_path).snapshot()
    assert set(("timestamp","mode","provenance","candles","observations","research_cases","validator"))<=data.keys()
    assert data["mode"]=="OBSERVE"
    assert data["provenance"]=="PUBLIC_MARKET_DATA_DETERMINISTIC"
    assert {"open_time","close_time","open","high","low","close","volume","provenance"}<=data["candles"][0].keys()
    assert data["observations"][0]["kind"]=="BOS_BEARISH"
    assert data["validator"]["cycles"]==406


def test_live_health_requires_fresh_market_data(tmp_path: Path) -> None:
    state=populated_state(tmp_path)
    state.system_health={"database":"connected","stream":"running"}
    data=state.snapshot()
    assert data["operational_health"]["stream"]=="RED"
    assert data["operational_health"]["status"]!="GREEN"


def test_future_timestamp_is_not_reported_as_fresh() -> None:
    assert _age_seconds("2999-01-01T00:00:00+00:00")=="INVALID:FUTURE_TIMESTAMP"


def test_header_does_not_treat_http_success_as_healthy() -> None:
    page=render(DashboardState())
    assert "data.operational_health?.status" in page
    assert "health==='green'?'Live'" in page


def test_snapshot_caps_live_collections() -> None:
    state=DashboardState(recent_candles=[{"n":i} for i in range(70)],active_observations=[{"n":i} for i in range(70)],research_cases=[{"n":i} for i in range(70)])
    data=state.snapshot()
    assert len(data["candles"])==len(data["observations"])==len(data["research_cases"])==50
    assert data["candles"][0]["n"]==20
    assert data["count_scope"]=="VISIBLE_RECENT_WINDOW"
    assert data["visible_counts"]=={"candles":50,"observations":50,"research_cases":50}


def test_dashboard_labels_capped_counts_as_visible_not_total() -> None:
    page=render(DashboardState(recent_candles=[{"n":i} for i in range(70)],active_observations=[{"n":i} for i in range(70)]))
    assert "Zählerbereich:</b> sichtbarer letzter Ausschnitt, keine Gesamtzahlen" in page
    assert "Sichtbare Candles" in page and "Sichtbare Observations" in page and "Sichtbare Cases" in page
    assert "sichtbarer Ausschnitt:" in page


def test_invalid_validator_state_is_visible_not_fatal(tmp_path: Path) -> None:
    path=tmp_path/"invalid.json";path.write_text("not-json")
    validator=DashboardState(validator_path=path).snapshot()["validator"]
    assert validator=={"status":"UNAVAILABLE","cycles":0}


def test_dashboard_has_no_execution_controls() -> None:
    page=render(DashboardState()).lower()
    for forbidden in ("<button>buy","<button>sell","place order","execute trade"):
        assert forbidden not in page


def test_api_is_stable_under_rapid_polling(tmp_path: Path) -> None:
    server=DashboardServer(populated_state(tmp_path),port=0);server.start();port=server.server.server_address[1]
    def request(_:int):
        started=time.monotonic()
        with urlopen(f"http://127.0.0.1:{port}/api/state",timeout=2) as response:return response.status,json.loads(response.read()),time.monotonic()-started
    try:
        with ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(request,range(10)))
        assert all(status==200 and data["mode"]=="OBSERVE" for status,data,_ in results)
        assert max(duration for _,_,duration in results)<0.5
    finally:server.stop()


def test_research_apis_use_current_observations_and_safe_download(tmp_path: Path) -> None:
    from src.research.config import ResearchConfig
    from src.research.router import ResearchRouter
    state=populated_state(tmp_path);state.active_observations[0].update({"source":"TIM_DATABASE","provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC","observed_at":"2026-07-20T14:00:00Z"})
    router=ResearchRouter(ResearchConfig(cache_path=tmp_path/"cache.jsonl",report_root=tmp_path/"reports"));server=DashboardServer(state,port=0,research_router=router);server.start();port=server.server.server_address[1]
    def post(path,payload):
        request=Request(f"http://127.0.0.1:{port}{path}",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json"},method="POST")
        with urlopen(request,timeout=3) as response:return response.status,json.loads(response.read())
    try:
        status,quick=post("/api/research/quick",{"query":"Review pattern"});assert status==200 and quick["module"]=="A"
        status,deep=post("/api/research/deep",{"query":"Create cited report","type":"research_report"});assert status==200 and deep["module"]=="B"
        with urlopen(f"http://127.0.0.1:{port}{deep['result']['download_url']}",timeout=3) as response:assert response.status==200 and b"TIM Research Report" in response.read()
        with pytest.raises(HTTPError) as error:urlopen(f"http://127.0.0.1:{port}/reports/../state.json",timeout=3)
        assert error.value.code==404
    finally:server.stop()


def test_research_api_rejects_invalid_input(tmp_path: Path) -> None:
    server=DashboardServer(populated_state(tmp_path),port=0);server.start();port=server.server.server_address[1]
    try:
        request=Request(f"http://127.0.0.1:{port}/api/research/deep",data=json.dumps({"query":"","type":"web"}).encode(),headers={"Content-Type":"application/json"},method="POST")
        with pytest.raises(HTTPError) as error:urlopen(request,timeout=3)
        assert error.value.code==400
    finally:server.stop()


def test_professional_research_navigation_and_overview_cards(tmp_path: Path) -> None:
    page=render(populated_state(tmp_path))
    for label in ("Research Overview","Data Quality","Stream Status","Validator Status","Runtime","Active Research Cases","Closed Research Cases","Dashboard Version"):
        assert label in page
    for route in ("/observations","/cases","/signals","/health","/timeline","/research"):
        assert f"href='{route}'" in page
    assert "<article class='card'" in page
    assert '"symbol":"BTCUSDT"' not in page


def test_observation_explorer_is_read_only_and_complete(tmp_path: Path) -> None:
    state=populated_state(tmp_path)
    state.active_observations[0].update({"observation_id":"obs-1234567890","observed_at":"2026-07-20T14:00:00+00:00","rule_id":"bos","rule_version":"1.0.0","evidence":{"swing":100},"input_hash":"a"*64,"provenance":"PUBLIC_MARKET_DATA_DETERMINISTIC"})
    state.research_cases[0]["observation_ids"]=["obs-1234567890"]
    page=render(state,"Observations","obs-1234567890")
    for label in ("Timestamp","Observation ID","Observation Type","Rule Version","Evidence Score","Provenance","Status","Observation Detail","Evidence / Rohdaten","Research Case","Hash"):
        assert label in page
    assert "obs-1234567890" in page and "case-1" in page and "a"*64 in page
    assert "READ-ONLY" in page
    assert "save" not in page.lower() and "delete" not in page.lower()


def test_case_explorer_filters_and_timeline(tmp_path: Path) -> None:
    state=populated_state(tmp_path)
    state.research_cases[0].update({"opened_at":"2026-07-20T13:00:00+00:00","updated_at":"2026-07-20T14:00:00+00:00","observation_ids":["obs-1"],"evidence":[{"observation_id":"obs-1","kind":"BOS_BEARISH","observed_at":"2026-07-20T13:30:00+00:00"}],"rule_versions":{"bos":"1.0.0"}})
    page=render(state,"Research Cases","case-1")
    for label in ("OPEN","MONITORING","CONFIRMED","INVALIDATED","CLOSED","Zeitraum","Observation Type","Rule Version","Dauer","Outcome","Missing Evidence","Timeline"):
        assert label in page
    assert "obs-1" in page and "BOS_BEARISH" in page


def test_health_center_and_timeline_use_persisted_state(tmp_path: Path) -> None:
    validator=tmp_path/"state.json"
    validator.write_text(json.dumps({"status":"RUNNING","cycles":9,"started_at":"2026-07-20T12:00:00+00:00","health_monitor":{"level":"RED","critical":["DATA_GAP"],"checks":{"candle_sequence_gap_free":False,"provenance_deterministic":True,"no_execution_events":True,"candle_stream_active":True}},"latest_health":{"database":{"status":"HEALTHY"},"dashboard":{"status":"HEALTHY","http_status":200},"benchmark":"PASS","research":{"level":"GREEN","trigger_duplicates":0}}}))
    events=tmp_path/"events.jsonl"
    events.write_text(json.dumps({"timestamp":"2026-07-20T13:00:00+00:00","event":"DATA_GAP","severity":"CRITICAL"})+"\n"+json.dumps({"timestamp":"2026-07-20T13:01:00+00:00","event":"TRADE_EXECUTED","severity":"INFO"})+"\n")
    state=DashboardState(validator_path=validator,events_path=events,system_health={"database":"connected","stream":"running"})
    health=render(state,"Health Center")
    for component in ("Database","Stream","Validator","Dashboard","Replay","Acceptance","Data Quality","Research Integrity","Governance"):
        assert component in health
    timeline=render(state,"Timeline")
    assert "RUNTIME_START" in timeline and "DATA_GAP" in timeline
    assert "TRADE_EXECUTED" not in timeline


def test_health_center_explains_persisted_failures(tmp_path: Path) -> None:
    validator=tmp_path/"state.json"
    readiness=tmp_path/"readiness.json"
    audit=tmp_path/"audit.json"
    quality=tmp_path/"quality.json"
    manifest=tmp_path/"manifest.json"
    validator.write_text(json.dumps({"status":"COMPLETED","cycles":1825,"last_cycle_at":"2026-07-23T15:12:42+00:00","acceptance":{"score":0.85,"status":"complete"}}))
    readiness.write_text(json.dumps({"mode":"OBSERVE","readiness_status":"NOT_READY_FOR_V2","continuous_coverage_percent":"60.659","continuous_missing_1m_intervals":430,"unresolved_new_gap_count":63,"blocking_criteria":["continuous_coverage"],"criteria":{"replay":"PASS","hash_consistency":"PASS","manual_scientific_review":"WAITING","new_artifact_provenance":"PASS"}}))
    audit.write_text(json.dumps({"status":"FAIL","artifacts_failed":2,"artifacts_checked":15,"issues":[{"code":"OUTPUT_HASH_MISMATCH"}]}))
    quality.write_text(json.dumps({"validation_status":"FAIL","checks":{"deterministic":False},"issues":[{"code":"PROVENANCE_INCOMPLETE"}]}))
    manifest.write_text(json.dumps({"status":"FROZEN","core_version":"1.0.0"}))
    state=DashboardState(validator_path=validator,readiness_path=readiness,audit_path=audit,quality_path=quality,core_manifest_path=manifest,system_health={"stream":"running"})
    page=render(state,"Health Center")
    for section in ("Live Operational Health","Historical Scientific Baseline","V2 Governance &amp; Readiness"):
        assert section in page
    assert "Berichtszeit:" in page
    assert "bedeuten nicht automatisch einen aktuellen Systemausfall" in page
    assert "PASS · Replay und Hash-Konsistenz" in page
    assert "Neue Artefakte PASS · Historisch unvollständig" in page
    for field in ("Reason","Seit","Auswirkung","Empfohlener nächster Schritt","Evidenz"):
        assert field in page
    assert "60.659%" in page and "430 Minuten fehlen" in page and "63 ungeklärte Gaps" in page
    assert "OUTPUT_HASH_MISMATCH" in page and "PROVENANCE_INCOMPLETE" in page
    assert "details class='card health-card" in page
    assert "ARCHIV · RED" in page
    assert "ARCHIV · YELLOW" in page
    assert "badge--snapshot" in page
    historical = page.split("2 · Historical Scientific Baseline", 1)[1].split("3 · V2 Governance &amp; Readiness", 1)[0]
    governance = page.split("3 · V2 Governance &amp; Readiness", 1)[1].split("Health Timeline", 1)[0]
    for archived_section in (historical, governance):
        assert "health--red" not in archived_section
        assert "health--yellow" not in archived_section
        assert "badge--red" not in archived_section
        assert "badge--yellow" not in archived_section
        assert "health--snapshot" in archived_section
    assert "Archivierte Evidenz, kein Live-Health-Status" in historical
    assert "Archivierte Governance-Evidenz, kein aktueller Systemfehler" in governance
    evidence_register = page.split("Data Quality Evidence Register", 1)[1]
    assert "badge--red" not in evidence_register
    assert "badge--yellow" not in evidence_register
    assert "ARCHIV · RED" in evidence_register


def test_live_health_has_explicit_queue_and_optional_ollama_state() -> None:
    state=DashboardState(system_health={"database":"connected","stream":"running","queue_depth":0,"queue_model":"DIRECT_AWAIT_NO_APPLICATION_QUEUE","ollama_enabled":False,"ollama_availability":"DISABLED_BY_POLICY"})
    state.recent_candles=[{"close_time":datetime.now(timezone.utc).isoformat()}]
    snapshot=state.snapshot()
    assert snapshot["operational_health"]["queue_depth"] == 0
    assert snapshot["operational_health"]["queue_model"] == "DIRECT_AWAIT_NO_APPLICATION_QUEUE"
    assert snapshot["operational_health"]["ollama_availability"] == "DISABLED_BY_POLICY"
    page=render(state,"Health Center")
    assert "0 wartende Nachrichten" in page
    assert "Optional deaktiviert" in page
    assert "MISSING:queue_depth" not in page
    assert "MISSING:ollama_availability" not in page


def test_timeline_normalizes_legacy_events_without_inventing_hashes() -> None:
    state=DashboardState()
    state._timeline_cache=[
        {"timestamp":"2026-07-27T09:18:06+00:00","event":"DATA_GAP","severity":"ERROR","summary":"ERROR"},
        {"timestamp":"2026-07-20T15:13:03+00:00","event":"RUNTIME_START","severity":"INFO","summary":"Persistierte TIM-Laufzeit gestartet."},
    ]
    state._timeline_mtime_ns=-1
    page=render(state,"Timeline")
    assert "MISSING:component_id" not in page
    assert "MISSING:previous_status" not in page
    assert "MISSING:new_status" not in page
    assert "MISSING:source_hash" not in page
    assert "data_quality" in page and "GAP_DETECTED" in page
    assert "N/A:LEGACY_EVENT_NOT_HASHED" in page


def test_governance_role_is_read_from_explicit_contract(tmp_path: Path) -> None:
    roles=tmp_path/"roles.json"
    roles.write_text(json.dumps({"scientific_release_authority":"Independent Scientific Reviewer (human)","core_owner":"TIM Project Owner (human)","effective_from":"2026-07-27T00:00:00+00:00","provenance":"TIM_GOVERNANCE_DOCUMENT"}))
    state=DashboardState(governance_roles_path=roles)
    page=render(state,"Health Center")
    assert "Independent Scientific Reviewer (human)" in page
    assert "MISSING:responsible_role" not in page


def test_dashboard_restart_renders_identical_persisted_content(tmp_path: Path) -> None:
    state=populated_state(tmp_path)
    before=render(state,"Observations")
    restarted=DashboardState(recent_candles=list(state.recent_candles),active_observations=list(state.active_observations),research_cases=list(state.research_cases),validator_path=state.validator_path)
    after=render(restarted,"Observations")
    stable=lambda value:value.replace("TIM Dashboard startet…","TIM Dashboard startet…")
    assert stable(before)==stable(after)


def test_all_research_ui_routes_respond_quickly(tmp_path: Path) -> None:
    server=DashboardServer(populated_state(tmp_path),port=0);server.start();port=server.server.server_address[1]
    try:
        durations=[]
        for path in ("/","/observations","/cases","/orderflow","/signals","/analytics","/insights","/health","/timeline","/research"):
            started=time.monotonic()
            with urlopen(f"http://127.0.0.1:{port}{path}",timeout=2) as response:
                assert response.status==200 and b"OBSERVE" in response.read()
            durations.append(time.monotonic()-started)
        assert max(durations)<0.5
    finally:server.stop()


def test_signal_research_is_read_only_evidence_path() -> None:
    state=DashboardState(
        orderflow_observations=[{
            "observation_id":"ofobs-1",
            "kind":"RISING_CVD_ACTIVITY",
            "timeframe":"1m",
            "observed_at":"2026-07-20T14:00:00+00:00",
            "evidence":[{"metric":"cumulative_delta"},{"metric":"trades_per_second"}],
            "rule_version":"1.0.0",
        }],
        orderflow_validations=[{
            "observation_id":"ofobs-1",
            "complete":True,
            "outcome":"PRICE_INCREASED",
        }],
    )
    page=render(state,"Signal Research")
    assert "AggTrades" in page and "Orderflow Metrics" in page
    assert "RISING_CVD_ACTIVITY" in page and "VALIDATED_CONTEXT" in page
    assert "cumulative_delta" in page and "trades_per_second" in page
    assert "Kein Trading-Signal" in page
    assert "keine Buy-/Sell-, Long-/Short-" in page
    assert "OBSERVE" in page and "keine Ausführung" in page


def test_orderflow_page_limits_visible_rows() -> None:
    state=DashboardState(orderflow_observations=[
        {"observation_id":f"ofobs-{index}","kind":"RISING_CVD_ACTIVITY","observed_at":f"2026-07-20T14:{index % 60:02d}:00+00:00"}
        for index in range(140)
    ])
    page=render(state,"Orderflow")
    assert "neueste 100 von 140" in page
    assert "ofobs-139" in page
    assert "ofobs-0" not in page


def test_overview_uses_same_health_status_sources(tmp_path: Path) -> None:
    validator=tmp_path/"state.json"
    validator.write_text(json.dumps({
        "status":"COMPLETED",
        "cycles":9,
        "health_monitor":{"checks":{"candle_sequence_gap_free":False,"provenance_deterministic":True}},
        "latest_health":{},
    }))
    page=render(DashboardState(validator_path=validator))
    assert "Data Quality" in page and "badge--red'>RED" in page
    assert "Persistierte Sequenz, Zeitstempel und Provenance." in page
    assert "Alle Freigabekriterien anzeigen" in page


def test_insights_page_and_exports_are_read_only(tmp_path: Path) -> None:
    state=populated_state(tmp_path)
    state.validator_path.write_text(json.dumps({"status":"RUNNING","cycles":406,"health_monitor":{"critical":["DATA_GAP"]},"latest_health":{"benchmark":"PASS"}}))
    state.orderflow_observations=[{"observation_id":"ofobs-1","kind":"RISING_CVD_ACTIVITY","symbol":"BTCUSDT","timeframe":"1m","observed_at":"2026-07-20T14:00:00+00:00","evidence":[{"metric":"net_delta"},{"metric":"trades_per_second"}],"rule_version":"1.0.0","input_hash":"a"*64,"provenance":"BINANCE_SPOT_AGGTRADE_DETERMINISTIC","mode":"OBSERVE"}]
    state.orderflow_validations=[{"observation_id":"ofobs-1","symbol":"BTCUSDT","observed_at":"2026-07-20T14:00:00+00:00","validated_through":"2026-07-20T14:30:00+00:00","horizons":[{"minutes":5,"price_change_percent":"0.1","net_delta":"1"},{"minutes":15,"price_change_percent":"0.2","net_delta":"2"},{"minutes":30,"price_change_percent":"0.3","net_delta":"3"}],"complete":True,"outcome":"PRICE_INCREASED","validation_hash":"b"*64,"validation_version":"1.0.0","mode":"OBSERVE"}]
    server=DashboardServer(state,port=0);server.start();port=server.server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/insights",timeout=2) as response:
            page=response.read().decode()
            assert response.status==200 and "Research Insights" in page and "NOT_YET_ELIGIBLE" in page
            assert "EXTERNAL TO CORE" in page and "NO FORECASTS" in page and "Save" not in page
        with urlopen(f"http://127.0.0.1:{port}/api/insights",timeout=2) as response:
            payload=json.loads(response.read()); assert payload["read_only"] is True and payload["mode"]=="OBSERVE"
        for extension,content_type in (("json","application/json"),("csv","text/csv"),("md","text/markdown")):
            with urlopen(f"http://127.0.0.1:{port}/exports/insights.{extension}",timeout=2) as response:
                assert response.status==200 and response.headers["Content-Type"].startswith(content_type) and response.read()
    finally:server.stop()


def test_research_analytics_page_and_exports_are_read_only(tmp_path: Path) -> None:
    state=populated_state(tmp_path)
    state.active_observations[0].update({"observation_id":"obs-1","observed_at":"2026-07-20T14:00:00Z","rule_id":"bos","rule_version":"1.0.0","timeframe":"1m"})
    state.research_cases[0].update({"opened_at":"2026-07-20T14:00:00Z","updated_at":"2026-07-20T14:05:00Z","observation_ids":["obs-1"],"outcome":"UNRESOLVED"})
    server=DashboardServer(state,port=0);server.start();port=server.server.server_address[1]
    try:
        with urlopen(f"http://127.0.0.1:{port}/analytics",timeout=2) as response:
            page=response.read().decode(); assert response.status==200 and "Research Analytics" in page and "READ-ONLY" in page and "Case Cluster" in page
            assert "Cases pro Stunde" in page and "Observation-Häufigkeit" in page and "Outcome-Häufigkeit" in page
        for extension,content_type in (("json","application/json"),("csv","text/csv"),("md","text/markdown")):
            with urlopen(f"http://127.0.0.1:{port}/exports/analytics.{extension}",timeout=2) as response:
                assert response.status==200 and response.headers["Content-Type"].startswith(content_type) and response.read()
    finally:server.stop()
