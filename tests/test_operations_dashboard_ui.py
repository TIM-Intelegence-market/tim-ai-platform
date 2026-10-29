import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.dashboard.app import DashboardServer, DashboardState, render


OPERATIONS_ROUTES = {
    # Dashboard 4.1: titles are rendered with the German labels from src/dashboard/i18n.py
    "/uebersicht-alt": "Betriebsüberblick",
    "/security": "Sicherheit",
    "/runtime": "Laufzeit",
    "/data-quality": "Datenqualität",
    "/gaps": "Vorfälle &amp; Lücken",
    "/qualification": "Qualifikation",
    "/independent-cases": "Unabhängige Fälle",
    "/v2-readiness": "V2-Bereitschaft",
    "/mcp": "Graphify &amp; MCP",
    "/audit-evidence": "Audit &amp; Evidenz",
}


def _write_json(root: Path, name: str, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(value), encoding="utf-8")


def _state(tmp_path: Path) -> DashboardState:
    completion = tmp_path / "completion"
    legacy = tmp_path / "legacy"
    _write_json(completion, "implementation_state.json", {
        "security_status": "BLOCKED — POSTGRES ADMIN ACTION REQUIRED",
        "runtime_status": "PASS",
        "overall_status": "TIME GATE",
        "mcp_status": "EXTERNAL ACTION REQUIRED",
        "trading_action_count": 0,
        "manual_review_status": "PENDING HUMAN APPROVAL",
        "human_approval": False,
    })
    _write_json(completion, "postgres_listener_before.json", {
        "listen_addresses": "*", "result": "FAIL", "tested_at_utc": "2026-08-01T20:00:00Z",
    })
    _write_json(completion, "postgres_listener_after.json", {
        "listen_addresses": "localhost", "result": "PASS", "lan_test": {"status": "PASS"},
    })
    _write_json(completion, "queue_metrics.json", {
        "status": "PASS", "queue_depth": 7, "oldest_age_seconds": 2.5,
        "receive_rate_per_second": 108.2, "persist_rate_per_second": 108.2,
        "drop_count": 0, "duplicate_count": 3, "late_count": 2,
        "source_to_store_latency_seconds": {"p95": 0.22}, "event_loop_lag_seconds": 0.004,
    })
    _write_json(completion, "durable_cursor_state.json", {"status": "PASS", "cursor_age_seconds": 1.2})
    _write_json(completion, "watchdog_status.json", {
        "status": "PASS", "processes": ["tim", "watchdog"], "uptime_seconds": 3600,
        "restart_count": 1, "disk_status": "PASS", "log_rotation_status": "PASS",
    })
    _write_json(completion, "backfill_candidate_manifest.json", {
        "status": "BLOCKED", "coverage": 0.8, "valid_observations": 80, "expected_observations": 100,
        "readiness_counted": False,
    })
    _write_json(completion, "qualification_preregistration.json", {
        "campaign_id": "V2_PROSPECTIVE_QUALIFICATION_V1", "campaign_status": "TIME GATE",
        "preregistered_at_utc": "2026-08-01T20:10:00Z",
    })
    _write_json(completion, "independent_case_audit.json", {
        "status": "FAIL", "frozen_strict_independent_cases": 14,
        "strict_independent_cases": 286, "qualification_independent_cases": 0,
        "required_independent_cases": 1000, "negative_control_cases": 0,
        "regime_coverage": "INCOMPLETE",
    })
    _write_json(completion, "final_test_summary.json", {
        "overall_test_status": "PASS", "finished_at_utc": "2026-08-01T20:20:00Z",
        "full_suite": {"passed": 400, "failed": 0, "warnings": 2},
        "doctor": {"status": "PASS"}, "validate": {"status": "PASS"},
    })
    _write_json(completion, "final_protected_state.json", {"status": "PASS"})
    _write_json(legacy, "coverage_final.json", {
        "product_calculation": {
            "coverage": 0.68115, "valid_observations": 9827,
            "expected_observations": 14427, "status": "FAIL",
            "rolling": {"PT1440M": {"coverage": 0.99, "valid_observations": 1426, "expected_observations": 1440, "status": "PASS"}},
        }
    })
    _write_json(legacy, "v2_readiness_matrix_final.json", {
        "gates": [
            {"gate_id": "SECURITY", "name": "Security", "status": "BLOCKED", "open_limitation": "Admin action", "reviewer_requirement": "PostgreSQL Admin"},
            {"gate_id": "SCIENCE", "name": "Science", "status": "PENDING HUMAN APPROVAL", "reviewer_requirement": "Independent human reviewer"},
        ]
    })
    (completion / "data_gap_inventory.jsonl").write_text(
        json.dumps({
            "gap_id": "gap-1", "start_utc": "2026-08-01T00:00:00Z", "end_utc": "2026-08-01T00:01:00Z",
            "severity": "P0", "root_cause_class": "PROCESS_DOWNTIME", "repairability": "CANDIDATE_ONLY",
            "repair_status": "NOT_ATTEMPTED", "source": "BINANCE_SPOT_PUBLIC", "evidence_refs": ["manifest.json"],
        }) + "\n",
        encoding="utf-8",
    )
    return DashboardState(
        completion_artifacts_path=completion,
        legacy_readiness_artifacts_path=legacy,
        operational_watchdog_path=tmp_path / "no-watchdog.json",
        rolling_liveness_path=tmp_path / "no-rolling-liveness.json",
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )


def test_operations_contract_never_conflates_coverage_or_invents_queue_metrics(tmp_path: Path) -> None:
    state = _state(tmp_path)
    operations = state.snapshot()["operations"]
    datasets = {item["label"]: item for item in operations["datasets"]}
    assert list(datasets) == [
        "Frozen Live Capture", "Backfill Candidate", "Approved Qualification Dataset",
        "Prospective Qualification Campaign", "Rolling Liveness",
    ]
    assert datasets["Frozen Live Capture"]["coverage"] == "68.115%"
    assert datasets["Backfill Candidate"]["coverage"] == "80.000%"
    assert datasets["Backfill Candidate"]["status"] == "BLOCKED"
    assert datasets["Approved Qualification Dataset"]["coverage"] == "UNAVAILABLE"
    assert datasets["Prospective Qualification Campaign"]["coverage"] == "UNAVAILABLE"
    assert datasets["Rolling Liveness"]["coverage"] == "99.000%"
    assert operations["runtime"]["queue_depth"]["value"] == 7
    assert operations["runtime"]["cursor_age"]["value"] == 1.2
    assert operations["gaps"]["p0"] == 1

    empty_completion = tmp_path / "empty-completion"
    empty_completion.mkdir()
    state.completion_artifacts_path = empty_completion
    uninstrumented = state.snapshot()["operations"]
    assert uninstrumented["runtime"]["queue_depth"]["value"] == "UNAVAILABLE"
    assert uninstrumented["runtime"]["queue_depth"]["status"] == "UNAVAILABLE"


def test_data_quality_coverage_rows_render_evidence_values_not_template_literals(tmp_path: Path) -> None:
    page = render(_state(tmp_path), "Data Quality")
    assert "68.115% · 9827 / 14427" in page
    assert "{_esc(percent_text)}" not in page
    assert "{_esc(item.get('observed'))}" not in page


def _current_snapshot() -> dict:
    return {
        "purpose": "CURRENT_STATE_NOT_QUALIFICATION",
        "qualification_started": False,
        "historical_artifacts_modified": False,
        "start": "2026-10-01T00:00:00Z",
        "end": "2026-10-02T00:00:00Z",
        "result": {
            "gaps": [
                {"gap_id": "october-1", "severity": "P1", "start_utc": "2026-10-01T00:00:00Z", "end_utc": "2026-10-01T00:01:00Z"},
                {"gap_id": "october-2", "severity": "P1", "start_utc": "2026-10-01T00:02:00Z", "end_utc": "2026-10-01T00:03:00Z"},
            ],
            "coverage": {
                "generated_at_utc": "2026-10-02T00:02:00Z",
                "v2_approved": False, "trading_approved": False,
                "product_calculation": {
                    "coverage": 1438 / 1440, "valid_observations": 1438,
                    "expected_observations": 1440, "status": "PASS",
                },
                "gap_summary": {"ranges": 2, "missing_minutes": 2},
            },
            "cases": {"current_cutoff_audit": {
                "strict_independent_30m_windows": 17, "gate_status": "FAIL",
            }},
        },
    }


def test_current_server_audit_is_visible_without_promoting_qualification(tmp_path: Path) -> None:
    state = _state(tmp_path)
    before = state.snapshot()["operations"]
    legacy = state.legacy_readiness_artifacts_path
    original = {path.name: path.read_bytes() for path in legacy.iterdir()}
    _write_json(legacy, "current_state.json", _current_snapshot())
    after = state.snapshot()["operations"]
    datasets = {item["label"]: item for item in after["datasets"]}
    assert datasets["Server-Bestandsaufnahme"]["observed"] == 1438
    assert datasets["Server-Bestandsaufnahme"]["expected"] == 1440
    assert after["current_server_snapshot"]["strict_cases"] == 17
    assert after["current_server_snapshot"]["case_scope"] == "ALL_PERSISTED_HISTORY_THROUGH_CUTOFF"
    assert after["current_server_snapshot"]["missing_minutes"] == 2
    assert after["current_server_snapshot"]["qualification_counted"] is False
    source = after["sources"]["current/current_state.json"]
    assert source["scope"] == "V2_COMPLETION"
    assert source["purpose"] == "CURRENT_STATE_NOT_QUALIFICATION"
    assert source["qualification_counted"] is False
    assert after["datasets"][0] == before["datasets"][0]
    assert after["datasets"][-1] == before["datasets"][-1]
    for key in ("qualification", "readiness"):
        assert after[key] == before[key]
    assert after["gaps"]["p1"] == 2
    assert after["gaps"]["p0"] == 0
    assert after["gaps"]["source"].endswith("current_state.json")
    assert after["gaps"]["purpose"] == "CURRENT_STATE_NOT_QUALIFICATION"
    assert after["independent_cases"]["current"] == 17
    assert after["independent_cases"]["current_source"].endswith("current_state.json")
    assert after["independent_cases"]["current_cutoff"] == "2026-10-02T00:00:00Z"
    for key in before["independent_cases"]:
        if key not in {"current", "current_source", "current_cutoff"}:
            assert after["independent_cases"][key] == before["independent_cases"][key]
    assert all((legacy / name).read_bytes() == data for name, data in original.items())
    page = render(state, "Data Quality")
    assert "2026-10-01T00:00:00Z" in page
    assert "2026-10-02T00:00:00Z" in page
    assert "Nicht angerechnet" in page
    assert "keine Qualifizierung" in page
    assert "einschließlich älterer Historie" in page
    assert "october-1" in render(state, "Incidents & Gaps")


@pytest.mark.parametrize("invalid", [
    {"purpose": "QUALIFICATION"},
    {"qualification_started": True},
    {"historical_artifacts_modified": "false"},
    {"result": {"coverage": {"v2_approved": True, "trading_approved": False, "product_calculation": {}}}},
    {"result": {"coverage": []}},
])
def test_current_server_snapshot_rejects_approval_or_wrong_scope(tmp_path: Path, invalid: dict) -> None:
    state = _state(tmp_path)
    payload = {**_current_snapshot(), **invalid}
    _write_json(state.legacy_readiness_artifacts_path, "current_state.json", payload)
    operations = state.snapshot()["operations"]
    assert operations["current_server_snapshot"]["available"] is False
    assert "Server-Bestandsaufnahme" not in {item["label"] for item in operations["datasets"]}


def test_current_empty_gap_inventory_does_not_reuse_an_old_gap(tmp_path: Path) -> None:
    state = _state(tmp_path)
    payload = _current_snapshot()
    payload["result"]["gaps"] = []
    payload["result"]["coverage"]["gap_summary"] = {"ranges": 0, "missing_minutes": 0}
    payload["result"]["coverage"]["product_calculation"].update(coverage=1.0, valid_observations=1440)
    _write_json(state.legacy_readiness_artifacts_path, "current_state.json", payload)
    operations = state.snapshot()["operations"]
    assert operations["gaps"]["total_loaded"] == 0
    assert operations["gaps"]["p0"] == 0
    assert operations["gaps"]["source"].endswith("current_state.json")
    assert operations["qualification"]["status"] == "TIME GATE"


def test_control_center_has_exact_ten_primary_pages_and_explicit_safety_boundary(tmp_path: Path) -> None:
    page = render(_state(tmp_path))
    # The old overview now lives in "Archiv V2"; the page carries the one five-area navigation.
    assert OPERATIONS_ROUTES["/uebersicht-alt"] in page
    for route in ("/", "/chart", "/journal", "/neu/forschung", "/neu/betrieb", "/archiv"):
        assert f"href='{route}'" in page
    assert page.count("aria-current='page'") == 1
    for invariant in ("OBSERVE-ONLY", "TRADING LOCKED", "EXECUTION DISABLED", "NO SHELL", "NO GIT", "NO SECRETS"):
        assert invariant in page
    assert "PostgreSQL security gate" in page
    assert "Freshness" in page
    assert "Open P0 data gaps" in page
    assert "PENDING HUMAN APPROVAL" in page
    assert "TRADING</span><b data-sev='fail'>LOCKED</b>" in page
    assert "Needs attention" in page
    assert "Source to readiness" in page
    assert "No directional signal" in page


@pytest.mark.parametrize("page,title", [
    ("Security", "Credential rotation"),
    ("Runtime", "source to store latency"),
    ("Data Quality", "Aktuelle Evidenzräume"),
    ("Incidents & Gaps", "Root cause"),
    ("Qualification", "Latest immutable daily manifest"),
    ("Independent Cases", "Manual review"),
    ("V2 Readiness", "PENDING HUMAN APPROVAL"),
    ("Graphify & MCP", "Tunnel permissions"),
    ("Audit & Evidence", "Protected state"),
])
def test_each_operations_page_renders_required_real_or_unavailable_state(tmp_path: Path, page: str, title: str) -> None:
    markup = render(_state(tmp_path), page)
    assert title in markup
    assert "OBSERVE-ONLY" in markup and "TRADING LOCKED" in markup
    assert "Demo" not in markup and "Lorem ipsum" not in markup


def test_security_evidence_is_escaped_and_secret_values_are_never_serialized(tmp_path: Path) -> None:
    state = _state(tmp_path)
    _write_json(state.completion_artifacts_path, "postgres_listener_after.json", {
        "listen_addresses": "<script>alert(1)</script>", "result": "FAIL",
    })
    _write_json(state.completion_artifacts_path, "credential_migration_evidence.json", {
        "status": "BLOCKED", "password": "never-render-this", "secret_provider": {"status": "PASS"},
    })
    page = render(state, "Security")
    api = json.dumps(state.snapshot()["operations"])
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "never-render-this" not in page and "never-render-this" not in api


def test_visible_research_workspace_has_no_artifact_write_controls(tmp_path: Path) -> None:
    page = render(_state(tmp_path), "Research")
    assert "NO WRITE CONTROLS" in page
    assert "id='quick-run'" not in page
    assert "id='deep-run'" not in page
    assert "<textarea" not in page


class _AccessibilityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.main_ids: list[str] = []
        self.nav_labels: list[str] = []
        self.buttons: list[dict[str, str]] = []
        self.h1 = 0
        self.inline_handlers: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "main":
            self.main_ids.append(values.get("id", ""))
        if tag == "nav":
            self.nav_labels.append(values.get("aria-label", ""))
        if tag == "button":
            self.buttons.append(values)
        if tag == "h1":
            self.h1 += 1
        self.inline_handlers.extend(key for key in values if key.startswith("on"))


def test_accessibility_and_responsive_contract_is_built_into_every_page(tmp_path: Path) -> None:
    page = render(_state(tmp_path), "Security")
    parser = _AccessibilityParser()
    parser.feed(page)
    assert parser.main_ids == ["main-content"]
    assert "Hauptnavigation" in parser.nav_labels
    assert parser.h1 == 1
    assert any(button.get("aria-live") == "polite" and button.get("aria-label") for button in parser.buttons)
    assert parser.inline_handlers == []
    assert "Zum Hauptinhalt springen" in page
    assert ":focus-visible" in page
    assert "@media(max-width:1180px)" in page
    assert "@media(max-width:820px)" in page
    assert "@media(max-width:520px)" in page
    assert "prefers-reduced-motion" in page
    assert "forced-colors" in page


def test_browser_e2e_all_operations_routes_and_security_headers(tmp_path: Path) -> None:
    server = DashboardServer(_state(tmp_path), port=0)
    server.start()
    port = server.server.server_address[1]
    try:
        for route, title in OPERATIONS_ROUTES.items():
            with urlopen(f"http://127.0.0.1:{port}{route}", timeout=2) as response:
                page = response.read().decode()
                assert response.status == 200
                assert title in page
                csp = response.headers["Content-Security-Policy"]
                assert "default-src 'none'" in csp
                assert "unsafe-inline" not in csp
                assert response.headers["X-Frame-Options"] == "DENY"
                assert response.headers["X-Content-Type-Options"] == "nosniff"
        with urlopen(f"http://127.0.0.1:{port}/api/operations", timeout=2) as response:
            payload = json.loads(response.read())
            assert payload["read_only"] is True
            assert payload["execution_disabled"] is True
            assert payload["trading_locked"] is True
        request = Request(f"http://127.0.0.1:{port}/", headers={"Host": "evil.example"})
        with pytest.raises(HTTPError) as error:
            urlopen(request, timeout=2)
        assert error.value.code == 421
    finally:
        server.stop()


def test_frozen_capture_is_shown_as_historical_not_as_live_alarm(tmp_path: Path) -> None:
    from src.dashboard.design_system import severity

    frozen = _state(tmp_path).snapshot()["operations"]["datasets"][0]
    assert frozen["label"] == "Frozen Live Capture"
    assert frozen["status"].startswith("HISTORICAL — ")
    assert frozen["recorded_status"] in frozen["status"]
    assert severity(frozen["status"]) == "disabled"
    assert severity("FAIL") == "fail"


def test_data_quality_moves_finished_rooms_into_collapsed_old_stock(tmp_path: Path) -> None:
    from src.dashboard.operations import _split_rooms

    rooms = [
        {"label": "Frozen Live Capture", "status": "HISTORICAL — FAIL", "coverage": "68.1%"},
        {"label": "Server-Bestandsaufnahme", "status": "FAIL", "coverage": "72.3%"},
        {"label": "Backfill Candidate", "status": "CANDIDATE PASS — NOT APPROVED", "coverage": "100%"},
        {"label": "Approved Qualification Dataset", "status": "UNAVAILABLE", "coverage": "UNAVAILABLE"},
        {"label": "Prospective Qualification Campaign", "status": "ABORTED", "coverage": "100%"},
        {"label": "Rolling Liveness", "status": "PASS", "coverage": "100%"},
    ]
    current, archived = _split_rooms(rooms, "2026-10-20T11:22:00+00:00")
    assert [r["label"] for r in current] == ["Rolling Liveness"]
    assert len(archived) == 5 and all(r["disposition"].startswith("Altbestand · ") for r in archived)
    from datetime import datetime, timezone
    fresh = datetime.now(timezone.utc).isoformat()
    current, _ = _split_rooms(rooms, fresh)
    assert "Server-Bestandsaufnahme" in [r["label"] for r in current]
    page = render(_state(tmp_path), "Data Quality")
    assert "<details class='panel readiness'><summary>Altbestand anzeigen" in page
    assert page.index("Aktuelle Evidenzräume") < page.index("Altbestand anzeigen")
