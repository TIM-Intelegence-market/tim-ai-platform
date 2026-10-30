"""Cockpit P3: "Forschung", "Betrieb" and "System & Freigabe" under /neu."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import urlopen

import pytest

from src.dashboard.cockpit.areas import build_betrieb, build_forschung, build_system
from src.dashboard.cockpit.page import AREA_BY_KEY, COCKPIT_CSP, render_sections, sections_body
from src.dashboard.cockpit.sources import BudgetedSources
from src.dashboard.server import DashboardServer
from tests.test_dashboard_cockpit import _live_state, _state

NOW = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_real_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The Mac runner has the real worker dashboard on 8767; tests must not read it.
    monkeypatch.setenv("TIM_WORKER_STATUS_URL", "http://127.0.0.1:9/api/status")
    monkeypatch.setenv("TIM_TRADING_TEAM_STATE", str(tmp_path / "no-trading-team"))


def _iso(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def _metric(value, status="MEASURED", unit=""):
    return {"value": value, "status": status, "unit": unit, "source": "runtime_metrics"}


def _gate(gid, name, status, current=None, note=""):
    return {"id": gid, "name": name, "status": status, "current_status": current, "current_note": note, "owner": "Uzi",
            "limitation": "", "evidence": []}


def _snapshot(**change) -> dict:
    """Shapes as the live /api/state delivers them on the Mac (24.10.2026)."""
    data = {
        "mode": "OBSERVE",
        "validator": {"status": "RUNNING", "cycles": 4200, "last_cycle_at": _iso(1), "acceptance": {"coverage_percent": 99.4}},
        "case_counts": {"total": 1086, "active": 40, "closed": 1046, "open": 12, "collecting_evidence": 22, "ready_for_review": 6,
                        "confirmed": 0, "rejected": 3, "quarantined": 1},
        "research_cases": [
            {"case_id": "case-abc", "status": "READY_FOR_REVIEW", "updated_at": _iso(20), "opened_at": _iso(300),
             "evidence": [{"kind": "absorption"}], "observation_ids": ["o1", "o2"], "missing_evidence": ["replay"]},
            {"case_id": "case-<script>", "status": "OPEN", "updated_at": _iso(40), "evidence": "kaputt", "observation_ids": None},
        ],
        "observations": [
            {"observation_id": "o1", "kind": "absorption", "observed_at": _iso(10), "timeframe": "1m", "confidence": 0.7,
             "summary": "Bid-Absorption <b>"},
        ],
        "timeline": [
            {"timestamp": _iso(5), "event": "VALIDATION_CYCLE", "severity": "INFO", "summary": "Zyklus"},
            {"timestamp": _iso(3), "event": "WATCHDOG_ALERT", "severity": "WARN", "summary": "Lücke im Strom"},
            {"timestamp": _iso(2), "event": "RESEARCH_CYCLE_CHECK", "severity": "INFO", "summary": "Check"},
        ],
        "operations": {
            "mode": "OBSERVE", "trading_locked": True, "execution_disabled": True,
            "runtime": {"receive_rate": _metric(12.5, unit="/s"), "queue_age": _metric(3, "PASS", "s"), "restarts": _metric(84),
                        "disk": _metric(41, "PASS", "%"), "logs": _metric("YELLOW", "YELLOW")},
            "security": {"listener_after": _metric("127.0.0.1:5432", "PASS"), "trading_actions": _metric(0, "MEASURED"),
                         "observe_only": _metric("OBSERVE", "TRUE"), "last_test": _iso(600)},
            "gaps": {"rows": [{"start": _iso(200), "end": _iso(190), "priority": "P1", "root_cause": "Netz", "repairability": "ja",
                               "status": "OPEN"}], "p0": 0, "p1": 1, "total_loaded": 1, "source": "gap_register.json"},
            "datasets": [],
            "history_recovery": {"status": "PASS", "reported_status": "PASS", "checked_at": _iso(30), "source": "history.json"},
            "qualification": {"status": "ABORTED", "campaign_id": "v2-qual-2026-10-20", "manifests_written": 2, "minimum_days": 30,
                              "source": "campaign.json"},
            "independent_cases": {"qualification": 0, "required": 30, "current": 6, "negative_controls": "0",
                                  "manual_review": "PENDING HUMAN APPROVAL", "human_approval": "PENDING HUMAN APPROVAL", "source": "ind.json"},
            "readiness": {"status": "NOT QUALIFIED — CAMPAIGN ABORTED", "current_reason": "Kampagne am 22.10. abgebrochen",
                          "source": "readiness.json", "gates": [
                              _gate("G01", "Datenstrom", "PASS", "PASS"),
                              _gate("G02", "Kampagne", "PASS", None),
                              _gate("G03", "Integrity-Freigabe", "PENDING HUMAN APPROVAL", "PENDING HUMAN APPROVAL"),
                              _gate("G04", "Lücken", "PASS", "FAIL", "P0-Lücke offen"),
                          ]},
            "audit": {"deployed_commit": "2718756abcdef", "deployed_at": _iso(120), "passed": 6207, "failed": 0, "test_status": "PASS",
                      "test_source": "deployment.json", "last_test": _iso(180), "doctor": "PASS", "validate": "PASS",
                      "protected_state": "PASS", "incidents": [{"timestamp_utc": _iso(60), "severity": "WARN", "event": "GAP",
                                                                "component_id": "stream", "reason_code": "NET"}]},
            "mcp": {"status": "BLOCKED — EXTERNAL OPENAI ACTION REQUIRED", "source": "mcp.json"},
        },
    }
    data.update(change)
    return data


class _FakeState:
    """A real state's paths with a fixed snapshot (DashboardState uses slots)."""

    def __init__(self, tmp_path: Path, snapshot) -> None:
        self.operational_watchdog_path = _state(tmp_path).operational_watchdog_path
        self.snapshot = snapshot if callable(snapshot) else (lambda: snapshot)


def _state_with(tmp_path: Path, snapshot) -> _FakeState:
    return _FakeState(tmp_path, snapshot)


def _tiles(model: dict) -> dict:
    return {t["id"]: t for s in model["sections"] for t in s["tiles"]}


def _fresh() -> BudgetedSources:
    return BudgetedSources()


# --- Forschung --------------------------------------------------------------

def test_forschung_shows_cases_waiting_for_review_and_parks_human_steps(tmp_path: Path) -> None:
    model = build_forschung(_state_with(tmp_path, _snapshot()), now=NOW, sources=_fresh())
    tiles = _tiles(model)
    assert tiles["validator"]["state"] == "ok" and tiles["validator"]["value"] == "läuft, 4.200 Zyklen"
    assert tiles["cases_total"]["value"] == "1.086 gesamt"
    assert tiles["cases_review"]["state"] == "warn" and tiles["cases_review"]["reason"] == "6 Fälle warten auf deine Prüfung"
    # 29.10.2026: the aborted V2 campaign left Forschung (it lives on /archiv); the logbook leads instead.
    assert "campaign" not in tiles and "human_review" not in tiles
    assert model["sections"][0]["id"] == "logbook" and tiles["studies_confirmed"]["value"] == "S1"
    assert [t["id"] for t in model["attention"]] == ["cases_review"]
    assert model["overall"] == "warn" and model["headline"] == "Ein Punkt braucht einen Blick"


def test_forschung_tables_link_inside_and_escape_text(tmp_path: Path) -> None:
    html = render_sections(build_forschung(_state_with(tmp_path, _snapshot()), now=NOW, sources=_fresh()))
    assert "<h1>Forschung</h1>" in html
    assert "href='/cases?id=case-abc'" in html and "bereit zur Prüfung" in html
    assert "case-&lt;script&gt;" in html and "Bid-Absorption &lt;b&gt;" in html
    assert "Logbuch der Studien" in html and "nicht testbar" in html and "Wartet auf euch" not in html


def test_stale_validator_turns_yellow(tmp_path: Path) -> None:
    snap = _snapshot(validator={"status": "RUNNING", "cycles": 1, "last_cycle_at": _iso(60)})
    tile = _tiles(build_forschung(_state_with(tmp_path, snap), now=NOW, sources=_fresh()))["validator"]
    assert tile["state"] == "warn" and "veraltet" in tile["reason"]


# --- Betrieb ----------------------------------------------------------------

def test_betrieb_judges_only_values_with_a_limit(tmp_path: Path) -> None:
    model = build_betrieb(_state_with(tmp_path, _snapshot()), now=NOW, sources=_fresh())
    tiles = _tiles(model)
    assert tiles["restarts"]["extra"]["kind"] == "info" and tiles["restarts"]["value"] == "84"
    assert tiles["receive_rate"]["value"] == "12,50 /s"
    assert tiles["queue_age"]["state"] == "ok" and tiles["disk"]["value"] == "41 %"
    assert tiles["logs"]["state"] == "warn"
    assert tiles["gaps"]["state"] == "warn" and tiles["gaps"]["reason"] == "Eine P1-Lücke im Register"
    assert tiles["history_recovery"]["state"] == "ok"
    runtime = next(sec for sec in model["sections"] if sec["id"] == "runtime")
    assert "persist_rate" not in tiles and "Gespeichert" in runtime["note"], "missing values become one line, not grey rows"


def test_betrieb_timeline_hides_routine_cycles(tmp_path: Path) -> None:
    model = build_betrieb(_state_with(tmp_path, _snapshot()), now=NOW, sources=_fresh())
    timeline = next(s for s in model["sections"] if s["id"] == "timeline")
    assert [row[1]["text"] for row in timeline["table"]["rows"]] == ["WATCHDOG_ALERT"]
    assert "2 von 3" in timeline["note"]


def test_p0_gap_is_red(tmp_path: Path) -> None:
    snap = _snapshot()
    snap["operations"]["gaps"] = {"rows": [], "p0": 2, "p1": 0, "source": "g"}
    model = build_betrieb(_state_with(tmp_path, snap), now=NOW, sources=_fresh())
    assert _tiles(model)["gaps"]["state"] == "fail" and model["overall"] == "fail"


# --- System & Freigabe ------------------------------------------------------

def test_system_trading_lock_and_gates(tmp_path: Path) -> None:
    model = build_system(_state_with(tmp_path, _snapshot()), now=NOW, sources=_fresh())
    tiles = _tiles(model)
    assert tiles["mode"]["state"] == "ok" and tiles["trading"]["value"] == "gesperrt"
    assert tiles["v2"]["value"] == "nicht qualifiziert" and tiles["v2"]["extra"]["kind"] == "parked"
    assert "gate_G01" not in tiles and tiles["gates_summary"]["value"] == "1 von 4 Gates"
    assert tiles["gate_G02"]["extra"]["state_label"] == "Nur Archiv" and "Archivwert" in tiles["gate_G02"]["reason"]
    assert tiles["gate_G03"]["extra"]["kind"] == "parked"
    assert tiles["gate_G04"]["state"] == "fail" and "P0" in tiles["gate_G04"]["reason"]
    assert tiles["sec_trading_actions"]["state"] == "ok" and tiles["sec_observe_only"]["state"] == "ok"
    assert tiles["mcp"]["extra"]["kind"] == "parked"
    assert tiles["deploy"]["value"] == "2718756"
    html = sections_body(model)
    assert "<h1>Freigabe &amp; Sicherheit</h1>" in html


def test_unlocked_trading_is_red(tmp_path: Path) -> None:
    snap = _snapshot(mode="LIVE")
    snap["operations"]["execution_disabled"] = False
    model = build_system(_state_with(tmp_path, snap), now=NOW, sources=_fresh())
    tiles = _tiles(model)
    assert tiles["mode"]["state"] == "fail" and tiles["trading"]["state"] == "fail"
    assert model["overall"] == "fail"


def test_trading_lock_needs_real_true_not_truthy_text(tmp_path: Path) -> None:
    snap = _snapshot()
    snap["operations"]["trading_locked"] = "false"
    assert _tiles(build_system(_state_with(tmp_path, snap), now=NOW, sources=_fresh()))["trading"]["state"] == "fail"


# --- odd data and failing sources -------------------------------------------

@pytest.mark.parametrize("build", [build_forschung, build_betrieb, build_system])
def test_odd_data_types_give_grey_sections_not_errors(tmp_path: Path, build) -> None:
    snap = _snapshot(validator="kaputt", case_counts=[1], research_cases={"x": 1}, observations="?", timeline=None)
    snap["operations"] = {"runtime": [], "gaps": "x", "readiness": {"gates": "x"}, "security": None, "audit": 5,
                          "qualification": [], "independent_cases": "x", "datasets": {"a": 1}}
    model = build(_state_with(tmp_path, snap), now=NOW, sources=_fresh())
    html = sections_body(model)
    assert model["sections"] and "<h1>" in html
    for tile in _tiles(model).values():
        assert tile["state"] == "ok" or tile["reason"], tile


@pytest.mark.parametrize("build", [build_forschung, build_betrieb, build_system])
def test_failing_snapshot_is_grey_with_reason(tmp_path: Path, build) -> None:
    def broken():
        raise RuntimeError("DB weg")

    model = build(_state_with(tmp_path, broken), now=NOW, sources=_fresh())
    tile = _tiles(model)["snapshot"]
    assert tile["state"] == "unknown" and "DB weg" in tile["reason"]


def test_foreign_links_in_cells_are_dropped() -> None:
    model = {"area": "forschung", "generated_at": NOW.isoformat(), "sections": [
        {"id": "x", "title": "X", "tiles": [], "table": {"head": ["A"], "rows": [[{"text": "böse", "href": "//evil.example"}],
                                                                                [{"text": "js", "href": "javascript:alert(1)"}]]}}]}
    html = sections_body(model)
    assert "evil.example" not in html and "javascript:" not in html and "böse" in html


# --- server -----------------------------------------------------------------

@pytest.fixture()
def server(tmp_path: Path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    srv = DashboardServer(_live_state(tmp_path, now), port=0)
    srv.start()
    try:
        yield f"http://127.0.0.1:{srv.server.server_address[1]}"
    finally:
        srv.stop()


@pytest.mark.parametrize("key", ["forschung", "betrieb", "system"])
def test_area_routes_fast_with_csp_fragment_and_api(server: str, key: str) -> None:
    began = time.monotonic()
    with urlopen(server + f"/neu/{key}", timeout=10) as response:
        body = response.read().decode()
        assert response.status == 200 and response.headers["Content-Security-Policy"] == COCKPIT_CSP
    assert time.monotonic() - began < 2.0
    assert "Im Aufbau" not in body and f"data-fragment='/neu/{key}?fragment=1'" in body
    assert "Weitere Seiten" in body and AREA_BY_KEY[key]["pages"][0][1] in body
    with urlopen(server + f"/neu/{key}?fragment=1", timeout=10) as response:
        assert "<h1>" in json.loads(response.read())["html"]
    with urlopen(server + f"/api/cockpit?area={key}", timeout=10) as response:
        model = json.loads(response.read())
    assert model["schema"] == "tim_cockpit_area/1" and model["area"] == key and model["mode"] == "OBSERVE"


# --- findings of the adversarial review -------------------------------------

def _system_tiles_of(tmp_path: Path, change) -> dict:
    snap = _snapshot()
    change(snap)
    return _tiles(build_system(_state_with(tmp_path, snap), now=NOW, sources=_fresh()))


@pytest.mark.parametrize("status", ["FAIL - HUMAN ACTION REQUIRED", "NOT APPLICABLE — FAIL"])
def test_fault_with_human_word_stays_a_fault(tmp_path: Path, status: str) -> None:
    def change(snap):
        snap["operations"]["readiness"]["gates"] = [_gate("G9", "X", "PASS", status)]
    tile = _system_tiles_of(tmp_path, change)["gate_G9"]
    assert tile["state"] == "fail" and tile["extra"].get("kind") != "parked"


def test_archived_fail_gate_is_yellow_not_parked(tmp_path: Path) -> None:
    def change(snap):
        snap["operations"]["readiness"]["gates"] = [_gate(None, "X", "FAIL", None), _gate(None, "Y", "PASS", None)]
    tiles = _system_tiles_of(tmp_path, change)
    assert tiles["gate_nr1"]["state"] == "warn" and tiles["gate_nr2"]["extra"]["kind"] == "parked"


def test_v2_failure_is_not_parked(tmp_path: Path) -> None:
    def change(snap):
        snap["operations"]["readiness"]["status"] = "NOT QUALIFIED - GATE FAIL"
    tile = _system_tiles_of(tmp_path, change)["v2"]
    assert tile["state"] == "fail" and tile["extra"].get("kind") != "parked"


@pytest.mark.parametrize("metric,state", [({"value": "3", "status": "PASS"}, "fail"), ({"value": 2.0, "status": "PASS"}, "fail"),
                                          ({"value": "0", "status": "FAIL"}, "ok"), ({"value": "viele", "status": "PASS"}, "unknown")])
def test_trading_actions_judged_by_the_number_only(tmp_path: Path, metric: dict, state: str) -> None:
    def change(snap):
        snap["operations"]["security"]["trading_actions"] = {**metric, "source": "s"}
    assert _system_tiles_of(tmp_path, change)["sec_trading_actions"]["state"] == state


def test_observe_only_needs_observe_value_and_measured_is_not_neutral(tmp_path: Path) -> None:
    def change(snap):
        snap["operations"]["security"]["observe_only"] = {"value": False, "status": "TRUE", "source": "s"}
        snap["operations"]["security"]["lan_exposure"] = {"value": "0.0.0.0", "status": "MEASURED", "source": "s"}
    tiles = _system_tiles_of(tmp_path, change)
    assert tiles["sec_observe_only"]["state"] == "fail"
    assert tiles["sec_lan_exposure"]["state"] == "unknown" and tiles["sec_lan_exposure"]["extra"].get("kind") != "info"


def test_mcp_failure_is_red_and_mode_conflict_is_red(tmp_path: Path) -> None:
    def change(snap):
        snap["operations"]["mcp"] = {"status": "FAIL", "source": "m"}
        snap["operations"]["mode"] = "PAPER"
    tiles = _system_tiles_of(tmp_path, change)
    assert tiles["mcp"]["state"] == "fail"
    assert tiles["mode"]["state"] == "fail" and "widersprechen" in tiles["mode"]["reason"]


@pytest.mark.parametrize("p0", [2.0, "3"])
def test_p0_count_as_float_or_text_is_still_red(tmp_path: Path, p0) -> None:
    snap = _snapshot()
    snap["operations"]["gaps"] = {"rows": [], "p0": p0, "p1": 0, "source": "g"}
    assert _tiles(build_betrieb(_state_with(tmp_path, snap), now=NOW, sources=_fresh()))["gaps"]["state"] == "fail"


def test_failing_room_is_never_cut_off(tmp_path: Path) -> None:
    snap = _snapshot()
    room = {"coverage": "100 %", "status": "PASS", "observed": 1, "expected": 1, "source": "q"}
    snap["operations"]["datasets"] = [{**room, "label": f"R{i}"} for i in range(5)] + [{**room, "label": "Kaputt", "status": "FAIL"}]
    model = build_betrieb(_state_with(tmp_path, snap), now=NOW, sources=_fresh())
    labels = [t["label"] for t in _tiles(model).values()]
    quality = next(sec for sec in model["sections"] if sec["id"] == "quality")
    assert "Kaputt" in labels and "weitere 2 grüne" in quality["note"]


def test_missing_timestamps_are_not_green(tmp_path: Path) -> None:
    snap = _snapshot(validator={"status": "RUNNING", "cycles": 1})
    snap["observations"] = [{"observation_id": "o", "kind": "x"}]
    tiles = _tiles(build_forschung(_state_with(tmp_path, snap), now=NOW, sources=_fresh()))
    assert tiles["validator"]["state"] == "unknown" and tiles["observations"]["state"] == "unknown"


@pytest.mark.parametrize("build", [build_forschung, build_betrieb, build_system])
@pytest.mark.parametrize("value", [[1, 2], "kaputt"])
def test_snapshot_that_is_not_an_object_is_grey(tmp_path: Path, build, value) -> None:
    model = build(_state_with(tmp_path, value), now=NOW, sources=_fresh())
    assert "Unerwartetes Format" in _tiles(model)["snapshot"]["reason"]
    sections_body({**model, "sections": model["sections"] + ["x"]})


def test_texts_for_odd_values(tmp_path: Path) -> None:
    snap = _snapshot()
    snap["case_counts"]["ready_for_review"] = "0"
    snap["operations"]["independent_cases"].update(human_approval="REJECTED", manual_review="REJECTED")
    snap["operations"]["audit"]["test_status"] = None
    tiles = _tiles(build_forschung(_state_with(tmp_path, snap), now=NOW, sources=_fresh()))
    assert tiles["cases_review"]["state"] == "ok"
    system = _tiles(build_system(_state_with(tmp_path, snap), now=NOW, sources=_fresh()))
    assert "None" not in system["tests"]["reason"]


def test_not_applicable_gate_says_so_instead_of_waiting(tmp_path: Path) -> None:
    def change(snap):
        snap["operations"]["readiness"]["gates"] = [_gate("MCP", "Integration", "NOT_APPLICABLE", "NOT_APPLICABLE", "Externer Weg")]
    tile = _system_tiles_of(tmp_path, change)["gate_MCP"]
    assert tile["extra"]["state_label"] == "Entfällt" and tile["reason"] == "Externer Weg"
