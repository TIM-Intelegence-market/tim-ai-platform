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
            "<style>.a>b{}</style><td>Research Cases &amp; Missing Evidence</td>")
    out = translate_html(page)
    assert "<title>Research-Fälle · TIM</title>" in out
    assert "<h2>Marktstatus</h2>" in out
    assert "<p>Market Status is fine</p>" in out  # partial match stays untouched
    assert "title='Market Status'" in out  # attributes untouched
    assert "const t='Market Status';" in out  # scripts untouched
    assert ">Überblick</a>" in out
    assert "<td>Research-Fälle und fehlende Belege</td>" in out


def test_catalog_has_no_empty_or_identical_noise() -> None:
    assert all(key and value for key, value in DE.items())


def test_navigation_is_grouped_and_marks_current_page() -> None:
    assert [group for group, _ in NAV_GROUPS] == ["Overview", "Forschung", "Betrieb", "Werkzeuge"]
    routes = [href for _, links in NAV_GROUPS for _, href in links]
    assert len(routes) == len(set(routes)) == 11
    page = render(DashboardState(), "Research Cases")
    assert "<details class='navgroup active'><summary>Forschung</summary>" in page
    assert "<a href='/cases' class='active' aria-current='page'>Research-Fälle</a>" in page
    assert "class='menu-toggle'" in page and "aria-label='Hauptnavigation'" in page


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
    assert "<b>Pipeline-Version:</b> 3.0.0" in page


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
