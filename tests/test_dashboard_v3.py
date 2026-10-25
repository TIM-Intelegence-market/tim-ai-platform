from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
import json
import subprocess
import sys

import pytest

from src.dashboard.app import DashboardServer, DashboardState, render
from src.orderflow.validation import VALIDATION_VERSION
from src.research.case_export import verify_case_export
from src.dashboard.helpers import _case_status
from src.dashboard.i18n import DE, translate_html
from src.dashboard.layout import NAV_GROUPS


def test_translation_touches_only_whole_text_nodes() -> None:
    page = ("<title>Research Cases · TIM</title><h2>Market Status</h2><p>Market Status is fine</p>"
            "<a title='Market Status' href='/x'>Overview</a><script>const t='Market Status';</script>"
            "<style>.a>b{}</style><th>Rule Version</th><td>Research Cases &amp; Missing Evidence</td>"
            "<dd><span>Closed</span></dd><span class='tag mono'>Outcome</span><br><p>Status</p>")
    out = translate_html(page)
    assert "<title>Research-Fälle · TIM</title>" in out
    assert "<h2>Marktstatus</h2>" in out
    assert "<p>Market Status is fine</p>" in out  # partial match stays untouched
    assert "title='Market Status'" in out  # attributes untouched
    assert "const t='Market Status';" in out  # scripts untouched
    assert ">Überblick</a>" in out
    assert "<th>Regelversion</th>" in out  # header labels are translated
    assert "<td>Research Cases &amp; Missing Evidence</td>" in out  # data cells never
    assert "<dd><span>Closed</span></dd>" in out and ">Outcome</span>" in out
    assert "<p>Status</p>" in out


def test_catalog_has_no_empty_or_identical_noise() -> None:
    assert all(key and value for key, value in DE.items())


def test_navigation_is_grouped_and_marks_current_page() -> None:
    # Dashboard 4.1: one Control Center navigation holds every live page plus the pilot view.
    assert [group for group, _ in NAV_GROUPS] == ["BETRIEB", "FORSCHUNG", "FREIGABE", "SYSTEM", "WERKZEUGE"]
    routes = [href for _, links in NAV_GROUPS for _, href in links]
    assert len(routes) == len(set(routes)) == 26 and "/prep" in routes and "/trader-journal" in routes and "/pilot" in routes and "/chart" in routes and "/journal" in routes
    page = render(DashboardState(), "Research Cases")
    assert "<p class='nav__label'>FORSCHUNG</p>" in page
    assert "<a href='/cases' class='active' aria-current='page'>Research-Fälle</a>" in page
    assert page.count("aria-current='page'") == 1 and "aria-label='Hauptnavigation'" in page
    assert ">Recherche-Werkzeug</a>" in page  # menu label of /research differs from the generic "Forschung"


def test_safety_markers_stay_visible_after_redesign() -> None:
    page = render(DashboardState())
    assert "OBSERVE • READ-ONLY" in page
    assert "NO ORDERS OR EXECUTION" in page
    assert "lang='de'" in page


def test_case_lifecycle_badges_do_not_paint_progress_as_error() -> None:
    assert _case_status("OPEN") == _case_status("COLLECTING_EVIDENCE") == _case_status("READY_FOR_REVIEW") == "yellow"
    assert _case_status("CONFIRMED") == "green"
    assert _case_status("CLOSED") == _case_status("REJECTED") == "snapshot"
    assert _case_status("QUARANTINED") == "red"
    assert _case_status("SOMETHING_UNKNOWN") == "red"
    page = render(DashboardState(research_cases=[{"case_id": "case-1", "status": "COLLECTING_EVIDENCE", "evidence": []}]), "Research Cases")
    assert "badge--yellow'>COLLECTING_EVIDENCE" in page


def test_no_page_leaks_unrendered_template_code() -> None:
    pages = ["Overview", "Observations", "Research Cases", "Orderflow", "Signal Research", "Analytics", "Insights",
             "Health Center", "Data Quality Exceptions", "Timeline", "Research"]
    for name in pages:
        page = render(DashboardState(), name)
        assert "{_safe(" not in page and "{_short(" not in page, name


def test_signal_research_shows_each_queue_card_once() -> None:
    page = render(DashboardState(), "Signal Research")
    assert page.count("Aktuelle Research-Warteschlange") == 1
    from src.dashboard.constants import DASHBOARD_VERSION
    assert f"<b>Pipeline-Version:</b> {DASHBOARD_VERSION}" in page


# --- P4: proof export, orderflow history API, retrospective on case detail ---------------------------------
ROOT = Path(__file__).resolve().parents[1]
OPENED = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _history(n: int, start: datetime):
    observations, validations = [], []
    for i in range(n):
        at = start + timedelta(hours=i)
        oid = f"ofobs_{i}"
        observations.append({"observation_id": oid, "kind": "ABSORPTION", "rule_version": "1.0.0", "observed_at": at.isoformat(), "evidence": [{"metric": "delta"}, {"condition": "x"}]})
        validations.append({"observation_id": oid, "observed_at": at.isoformat(), "complete": True, "outcome": "PRICE_INCREASED", "validation_version": VALIDATION_VERSION,
                            "validated_through": (at + timedelta(minutes=30)).isoformat(), "validation_hash": "c" * 64,
                            "horizons": [{"minutes": m, "target_at": (at + timedelta(minutes=m)).isoformat()} for m in (5, 15, 30)]})
    return observations, validations


def _orderflow_state() -> DashboardState:
    observations, validations = _history(12, OPENED - timedelta(days=2))
    # one validation whose outcome is only known after the case opened: must not be counted
    late_obs, late_val = _history(1, OPENED - timedelta(minutes=10))
    late_obs[0]["observation_id"] = late_val[0]["observation_id"] = "ofobs_late"
    case = {"case_id": "case_ofproof", "symbol": "BTCUSDT", "timeframe": "1m", "opened_at": OPENED.isoformat(), "updated_at": OPENED.isoformat(),
            "status": "COLLECTING_EVIDENCE", "observation_ids": ["ofobs_own"], "evidence": [{"observation_id": "ofobs_own", "kind": "ABSORPTION", "observed_at": OPENED.isoformat(), "input_hash": "d" * 64}],
            "missing_evidence": [], "outcome": None, "rule_versions": {"orderflow": "1.0.0"}}
    return DashboardState(research_cases=[case], orderflow_observations=observations + late_obs, orderflow_validations=validations + late_val)


@pytest.fixture()
def server():
    srv = DashboardServer(_orderflow_state(), port=0)
    srv.start()
    yield f"http://127.0.0.1:{srv.server.server_address[1]}"
    srv.stop()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urlopen(url, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def test_orderflow_history_api_returns_full_lists(server) -> None:
    status, body = _get(server + "/api/orderflow/history")
    data = json.loads(body)
    assert status == 200 and set(data) == {"observations", "validations"}
    assert len(data["observations"]) == len(data["validations"]) == 13


def test_case_export_routes_are_verifiable_and_include_retrospective(server) -> None:
    status, body = _get(server + "/exports/case/case_ofproof.json")
    export = json.loads(body)
    assert status == 200 and verify_case_export(export)
    block = export["retrospective"][0]
    assert block["label"] == "RETROSPECTIVE" and block["sample_size"] == 12  # late outcome excluded
    status, body = _get(server + "/exports/case/case_ofproof.html")
    assert status == 200 and b"Research-Beleg" in body
    assert _get(server + "/exports/case/case_missing.json")[0] == 404
    assert _get(server + "/exports/case/case_ofproof.csv")[0] == 404


def test_case_list_and_detail_link_the_proof_and_show_retrospective(server) -> None:
    listing = _get(server + "/cases")[1].decode()
    assert "href='/exports/case/case_ofproof.html'" in listing
    detail = _get(server + "/cases?id=case_ofproof")[1].decode()
    assert "Prüfbarer Beleg" in detail and "RETROSPECTIVE" in detail and "n=12" in detail
    assert "Keine Prognose" in detail


def test_export_script_fetches_history_from_dashboard(server, tmp_path: Path) -> None:
    run = [sys.executable, str(ROOT / "scripts/export_case.py"), "case_ofproof", "--dashboard", server, "--out", str(tmp_path)]
    subprocess.run(run, check=True, capture_output=True)
    export = json.loads((tmp_path / "case_ofproof.json").read_text())
    assert verify_case_export(export) and export["retrospective"][0]["sample_size"] == 12
    subprocess.run(run + ["--no-history"], check=True, capture_output=True)
    assert "retrospective" not in json.loads((tmp_path / "case_ofproof.json").read_text())


# --- P5: pilot view shows only allowlisted data ------------------------------------------------------------
SECRET = "INTERNAL_MARKER_X9"


def _pilot_state(tmp_path: Path) -> DashboardState:
    state = _orderflow_state()
    case = state.research_cases[0]
    case.update({"documentation": f"{SECRET} doc", "review_history": [{"at": OPENED.isoformat(), "to": "OPEN", "reason": f"{SECRET} reason"}],
                 "missing_evidence": [f"{SECRET}_missing"]})
    case["evidence"][0]["provenance"] = f"{SECRET}_provenance"
    case["evidence"][0]["input_hash"] = "e" * 64
    validator = tmp_path / "state.json"
    validator.write_text(json.dumps({"status": "RUNNING", "cycles": 7, "started_at": f"{SECRET}"}))
    state.validator_path = validator
    state.system_health = {"database": f"{SECRET}_db", "stream": f"{SECRET}_stream"}
    state.market_status = {"status": f"{SECRET}_market"}
    return state


def test_pilot_view_renders_only_allowlisted_fields(tmp_path: Path) -> None:
    from src.dashboard.pages.pilot import PILOT_CASE_FIELDS, render_pilot
    assert PILOT_CASE_FIELDS == ("case_id", "symbol", "timeframe", "opened_at", "status", "outcome")
    page = render_pilot(_pilot_state(tmp_path))
    assert SECRET not in page
    assert "e" * 64 not in page  # no input hashes
    for internal in ("/api/", "tim-status", "Systemzustand", "validator", "Validator", "config/", "data/", "events", "Hauptnavigation", "fetch("):
        assert internal not in page, internal
    assert "case_ofproof" in page and "sammelt Belege" in page and "RETROSPECTIVE" in page
    assert "href='/exports/case/case_ofproof.html'" in page
    assert "keine Empfehlung, keine Prognose" in page


def test_pilot_view_is_bounded_to_newest_cases() -> None:
    # Regression: rendering every stored case (4,500 on the Mac) took >100 s and hit the 413 limit.
    from datetime import timedelta
    from src.dashboard.pages.pilot import PILOT_CASE_LIMIT, render_pilot
    state = DashboardState(research_cases=[
        {"case_id": f"case_{i:05d}", "symbol": "BTCUSDT", "timeframe": "1m", "status": "OPEN",
         "opened_at": (OPENED + timedelta(minutes=i)).isoformat(), "evidence": []}
        for i in range(PILOT_CASE_LIMIT + 25)
    ])
    page = render_pilot(state)
    assert page.count("class='card pilot-case'") == PILOT_CASE_LIMIT
    assert f"case_{PILOT_CASE_LIMIT + 24:05d}" in page and "case_00000" not in page
    assert f"Die neuesten {PILOT_CASE_LIMIT} von {PILOT_CASE_LIMIT + 25}" in page


def test_pilot_route_is_served(server) -> None:
    status, body = _get(server + "/pilot")
    assert status == 200 and b"TIM Research-Belege" in body and b"<script" not in body



# --- review findings -----------------------------------------------------------------------------------------
def test_stored_values_equal_to_labels_are_not_translated() -> None:
    case = {"case_id": "case-x", "status": "OPEN", "outcome": "Outcome", "missing_evidence": ["Evidence"],
            "rule_versions": {"bos": "Closed"}, "evidence": [{"observation_id": "o1", "kind": "Research"}]}
    page = render(DashboardState(research_cases=[case]), "Research Cases", "case-x")
    assert "Recherche-Werkzeug</span>" not in page.split("Falldetails", 1)[1]
    assert "bos:Closed" in page and ">Evidence<" in page


def test_malformed_case_does_not_break_pilot_or_export(server) -> None:
    state = _orderflow_state()
    state.research_cases.append({"case_id": "case_bad", "status": "OPEN", "opened_at": OPENED.isoformat(), "rule_versions": None,
                                 "evidence": ["not-a-dict"], "observation_ids": []})
    srv = DashboardServer(state, port=0)
    srv.start()
    base = f"http://127.0.0.1:{srv.server.server_address[1]}"
    try:
        status, body = _get(base + "/pilot")
        assert status == 200 and b"case_bad" in body and b"case_ofproof" in body
        status, body = _get(base + "/exports/case/case_bad.json")
        assert status == 200 and verify_case_export(json.loads(body))
        assert _get(base + "/cases")[0] == 200
    finally:
        srv.stop()


def test_retrospective_states_its_basis(server) -> None:
    export = json.loads(_get(server + "/exports/case/case_ofproof.json")[1])
    assert export["retrospective"][0]["basis"].startswith("Grundlage: 13 Orderflow-Beobachtungen im geladenen Verlauf")
    assert "im geladenen Verlauf" in _get(server + "/pilot")[1].decode()


def test_export_script_survives_dashboard_without_history_api(tmp_path: Path) -> None:
    import http.server
    import threading

    case = {"case_id": "case_old", "symbol": "BTCUSDT", "opened_at": OPENED.isoformat(), "rule_versions": {"orderflow": "1.0.0"}, "evidence": []}

    class OldDashboard(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body, code = (json.dumps(case).encode(), 200) if self.path == "/api/cases/case_old" else (b'{"error":"not found"}', 404)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OldDashboard)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        result = subprocess.run([sys.executable, str(ROOT / "scripts/export_case.py"), "case_old", "--dashboard", f"http://127.0.0.1:{httpd.server_address[1]}", "--out", str(tmp_path)],
                                capture_output=True, text=True)
    finally:
        httpd.shutdown()
    assert result.returncode == 0 and "Warnung" in result.stderr
    export = json.loads((tmp_path / "case_old.json").read_text())
    assert verify_case_export(export) and "retrospective" not in export


# --- 4.1 security review: CSP is fixed per route, stored data never becomes allowed code ---------


def _fetch(port: int, path: str):
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
    response = connection.getresponse()
    return response.status, response.getheader("Content-Security-Policy"), response.read().decode()


def test_stored_markup_is_escaped_and_never_whitelisted_by_the_csp(tmp_path) -> None:
    from src.dashboard.app import _content_security_policy

    validator = tmp_path / "state.json"
    validator.write_text(json.dumps({"status": "x'><script>alert(1)</script>", "health_monitor": {"level": "y'><style>*{}</style>"}}))
    server = DashboardServer(DashboardState(validator_path=validator), port=0)
    server.start()
    try:
        status, csp, page = _fetch(server.server.server_address[1], "/")
    finally:
        server.stop()
    assert status == 200
    assert "<script>alert(1)</script>" not in page and "<style>*{}</style>" not in page
    assert csp == _content_security_policy()


def test_pilot_and_proof_pages_get_their_fixed_policies() -> None:
    from src.dashboard.pages.pilot import PILOT_CSP

    server = DashboardServer(_orderflow_state(), port=0)
    server.start()
    try:
        port = server.server.server_address[1]
        status, csp, _ = _fetch(port, "/pilot")
        assert status == 200 and csp == PILOT_CSP and "script-src 'none'" in csp
        status, csp, page = _fetch(port, "/exports/case/case_ofproof.html")
        assert status == 200 and "unsafe-inline" not in csp and "script-src 'sha256-" in csp
        assert page.count("<script>") == 1  # the verifier; the payload block is type='text/plain'
    finally:
        server.stop()


def test_proof_policy_fails_closed_when_blocks_were_injected() -> None:
    from src.dashboard.layout import _content_security_policy_for

    page = "<style>a{}</style><script>ok()</script><script type='text/plain'>data</script>"
    assert "script-src 'sha256-" in _content_security_policy_for(page)
    injected = page + "<script>evil()</script>"
    assert "style-src 'none'; script-src 'none'" in _content_security_policy_for(injected)


def test_orderflow_history_is_bounded() -> None:
    from src.dashboard.constants import HISTORY_LIMIT

    items = [{"observation_id": f"o{i}"} for i in range(HISTORY_LIMIT + 5)]
    server = DashboardServer(DashboardState(orderflow_observations=list(items), orderflow_validations=list(items)), port=0)
    server.start()
    try:
        status, _, body = _fetch(server.server.server_address[1], "/api/orderflow/history")
    finally:
        server.stop()
    history = json.loads(body)
    assert status == 200 and len(history["observations"]) == len(history["validations"]) == HISTORY_LIMIT
    assert history["validations"][-1]["observation_id"] == f"o{HISTORY_LIMIT + 4}"
