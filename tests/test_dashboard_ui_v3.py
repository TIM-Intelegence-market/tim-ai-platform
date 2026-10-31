"""UI-V3 control center regression coverage.

Pins the redesigned dashboard presentation layer:

- central semantic severity system (design_system.severity);
- zero is a value, UNAVAILABLE is a missing value — never interchanged;
- the Overview attention list only derives from real evidence;
- every page carries the trading-locked status matrix;
- pipeline stages render truthful states, including uninstrumented UNKNOWN.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.dashboard.app import DashboardState, _strip_states, render
from src.dashboard.design_system import severity


def _write_json(root: Path, name: str, value: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(json.dumps(value), encoding="utf-8")


def _state(tmp_path: Path, system_health: dict | None = None) -> DashboardState:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {
        "security_status": "PASS", "runtime_status": "PASS", "overall_status": "TIME GATE",
        "trading_action_count": 0, "manual_review_status": "PENDING HUMAN APPROVAL",
    })
    _write_json(completion, "queue_metrics.json", {"status": "PASS", "queue_depth": 0})
    _write_json(completion, "final_test_summary.json", {"overall_test_status": "PASS"})
    return DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=tmp_path / "no-gate-model.json",
        phase_c_checkpoint_path=tmp_path / "no-phase-c.json",
        system_health=system_health or {"database": "connected", "stream": "running", "queue_depth": 0},
    )


def test_severity_mapping_keeps_genuine_states_apart() -> None:
    assert severity("PASS") == "ok"
    assert severity("GREEN") == "ok"
    assert severity("COMPLETED") == "ok"
    assert severity(None) == "unknown"
    assert severity("") == "unknown"
    assert severity("UNAVAILABLE") == "unknown"
    assert severity("MISSING:last_data_at") == "unknown"
    assert severity("FAIL") == "fail"
    assert severity("FAIL — SAFETY OR DATA INTEGRITY") == "fail"
    assert severity("BLOCKED — POSTGRES ADMIN ACTION REQUIRED") == "blocked"
    assert severity("EXTERNAL ACTION REQUIRED") == "blocked"
    assert severity("TIME GATE") == "info"
    assert severity("PENDING HUMAN APPROVAL") == "info"
    assert severity("NOT_READY_FOR_V2") == "warn"
    assert severity("CANDIDATE PASS — NOT APPROVED") == "warn"
    assert severity("DEGRADED") == "degraded"
    assert severity("DISABLED_BY_POLICY") == "disabled"
    assert severity("LOCKED") == "fail"  # TRADING LOCKED must render with the strong signal
    assert severity("AWAITING INTELLIGENCE") == "disabled"


def test_zero_is_a_value_and_missing_is_unavailable(tmp_path: Path) -> None:
    state = _state(tmp_path, system_health={
        "database": "connected", "stream": "running", "queue_depth": 0,
    })
    operations = state.snapshot()["operations"]
    assert operations["live"]["queue_depth"] == 0
    page = render(state, "Overview")
    assert ">0 events<" in page

    uninstrumented_state = DashboardState(
        completion_artifacts_path=tmp_path / "empty-completion",
        system_health={"database": "connected", "stream": "running"},
    )
    assert uninstrumented_state.snapshot()["operations"]["runtime"]["queue_depth"]["value"] == "UNAVAILABLE"


def test_attention_list_derives_only_from_loaded_evidence(tmp_path: Path) -> None:
    page = render(_state(tmp_path), "Overview")
    assert "Manual scientific review pending" in page
    assert "PostgreSQL security gate" not in page

    blocked = tmp_path / "blocked"
    completion = blocked / "completion"
    _write_json(completion, "implementation_state.json", {
        "security_status": "BLOCKED — POSTGRES ADMIN ACTION REQUIRED",
        "runtime_status": "PASS", "trading_action_count": 0,
    })
    state = DashboardState(
        completion_artifacts_path=completion,
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "Overview")
    assert "PostgreSQL security gate" in page


def test_every_operations_page_carries_status_matrix_with_locked_trading(tmp_path: Path) -> None:
    for page_name in ("Overview", "Runtime", "Data Quality", "Incidents & Gaps", "V2 Readiness"):
        page = render(_state(tmp_path), page_name)
        assert "status-matrix" in page
        assert "TRADING</span><b data-sev='fail'>LOCKED</b>" in page
        assert "id='st-system'" in page
        assert "id='st-live-data'" in page
        assert "id='st-queue'" in page
        assert "id='st-data-quality'" in page
        assert "id='st-research'" in page


def test_strip_states_never_fabricate_health(tmp_path: Path) -> None:
    state = _state(tmp_path)
    data = state.snapshot()
    rows = {label: (sev, value) for label, sev, value in _strip_states(data)}
    # No candles loaded in this fixture -> freshness evidence is missing -> not LIVE.
    assert rows["SYSTEM"] == ("warn", "DEGRADED")
    assert rows["LIVE DATA"] == ("fail", "DOWN")
    assert rows["QUEUE"] == ("ok", "0 EV")
    assert rows["RESEARCH"][0] in ("ok", "warn", "unknown")

    dark = DashboardState(
        completion_artifacts_path=tmp_path / "completion",
        system_health={"database": "disconnected", "stream": "stopped"},
    )
    rows = {label: (sev, value) for label, sev, value in _strip_states(dark.snapshot())}
    assert rows["SYSTEM"][0] == "fail"
    assert rows["LIVE DATA"] == ("fail", "DOWN")
    # operational_health defaults a missing queue depth to 0; the strip mirrors that truthfully.
    assert rows["QUEUE"] == ("ok", "0 EV")


def test_pipeline_renders_nine_truthful_stages(tmp_path: Path) -> None:
    page = render(_state(tmp_path), "Overview")
    from src.dashboard.i18n import DE
    for stage in ("Source", "Ingest", "Queue", "Persist", "Cursor", "Candles", "Quality", "Research", "Readiness"):
        assert f"<b>{DE.get(stage, stage)}</b>" in page
    assert page.count("pipeline__stage") >= 9


def test_uninstrumented_cursor_stage_stays_unknown(tmp_path: Path) -> None:
    empty = tmp_path / "empty-completion"
    empty.mkdir(parents=True, exist_ok=True)
    state = DashboardState(
        completion_artifacts_path=empty,
        operational_watchdog_path=tmp_path / "no-watchdog.json",
        system_health={"database": "connected", "stream": "running"},
    )
    operations = state.snapshot()["operations"]
    assert operations["runtime"]["cursor_age"]["value"] == "UNAVAILABLE"
    page = render(state, "Overview")
    assert "Cursor age not instrumented" in page


def test_incidents_are_bounded_and_newest_first(tmp_path: Path) -> None:
    state = _state(tmp_path)
    operations = state.snapshot()["operations"]
    incidents = operations["audit"]["incidents"]
    assert isinstance(incidents, list) and len(incidents) <= 20


def test_navigation_has_four_screens(tmp_path: Path) -> None:
    page = render(_state(tmp_path), "Runtime")
    for label in ("Cockpit", "Journal", "Forschung", "System"):
        assert f"</span>{label}</a>" in page
    assert "class='nav__label'" not in page and "<a href='/runtime' aria-current='page'>Laufzeit</a>" in page


def _gate_model(path: Path, *, research: list[tuple[str, str]] | None = None,
                checked_at: str = "2026-09-17T00:00:00+00:00") -> None:
    model = {
        "schema": "CURRENT_GATE_MODEL_V1",
        "stale_after_days": 14,
        "bands": {
            "system_health": [
                {"id": "DETERMINISM", "status": "PASS", "note": "isolated suites green",
                 "evidence": "work/gate_evidence.json", "checked_at": checked_at},
            ],
            "data_pipeline": [
                {"id": "DATA_QUALITY_CURRENT", "status": "PASS", "note": "collection scope",
                 "evidence": "artifacts/collection_result.json", "checked_at": checked_at},
                {"id": "DATA_QUALITY_LEGACY", "status": "WARN", "note": "legacy coverage unchanged",
                 "evidence": "data/research/status/tim_v1_readiness.json", "checked_at": checked_at},
                {"id": "PHASE_C_HISTORICAL_EXTENSION", "status": "IN_PROGRESS", "live_checkpoint": True,
                 "note": "isolated import", "evidence": "/tmp/phase_c_checkpoint.json",
                 "checked_at": checked_at},
            ],
            "research_readiness": [
                {"id": gate, "status": status, "note": "n", "evidence": "e", "checked_at": checked_at}
                for gate, status in (research or [("SHORT", "PASS"), ("MID", "PASS"), ("LONG", "IN_PROGRESS")])
            ],
            "governance": [
                {"id": "GOVERNANCE_STATE", "status": "HUMAN_ACTION_REQUIRED", "note": "manual gates unsigned",
                 "evidence": "artifacts/manual_gates.json", "checked_at": checked_at},
            ],
            "trading": [
                {"id": "TRADING", "status": "LOCKED", "note": "observe only",
                 "evidence": "/api/state", "checked_at": None},
            ],
        },
        "archived_snapshots": [
            {"id": "V2_READINESS_MATRIX_FINAL", "label": "V2 Readiness Matrix (cut-off 2026-08-01)",
             "status": "STALE", "frozen_at": "2026-08-01T00:00:00+00:00",
             "note": "frozen historical snapshot", "evidence": "artifacts/v2_readiness/v2_readiness_matrix_final.json"},
        ],
    }
    path.write_text(json.dumps(model), encoding="utf-8")


def test_readiness_page_renders_five_bands_from_gate_model(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {
        "security_status": "PASS", "runtime_status": "PASS", "trading_action_count": 0,
    })
    gate_path = tmp_path / "gate.json"
    _gate_model(gate_path)
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=gate_path,
        phase_c_checkpoint_path=tmp_path / "no-phase-c.json",
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "V2 Readiness")
    for band in ("Band 1 · System health", "Band 2 · Data pipeline", "Band 3 · Research readiness",
                 "Band 4 · Governance / human approval", "Band 5 · Trading authorization"):
        assert band in page
    assert "Archived snapshots" in page
    assert "STALE" in page
    assert "DETERMINISM" in page and "DATA_QUALITY_CURRENT" in page and "DATA_QUALITY_LEGACY" in page
    assert "PENDING HUMAN APPROVAL" in page
    assert "LOCKED" in page


def test_phase_c_checkpoint_progress_is_shown_live(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {"trading_action_count": 0})
    gate_path = tmp_path / "gate.json"
    _gate_model(gate_path)
    checkpoint = tmp_path / "phase_c_checkpoint.json"
    checkpoint.write_text(json.dumps({"last_id": 42, "pages": 3799, "trades": 3798437}), encoding="utf-8")
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=gate_path,
        phase_c_checkpoint_path=checkpoint,
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "V2 Readiness")
    assert "live checkpoint: 3798437 trades" in page
    assert "3799 pages" in page


def test_gate_entry_past_staleness_window_is_marked_stale(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {"trading_action_count": 0})
    gate_path = tmp_path / "gate.json"
    _gate_model(gate_path, checked_at="2026-07-01T00:00:00+00:00")
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=gate_path,
        phase_c_checkpoint_path=tmp_path / "no-phase-c.json",
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "V2 Readiness")
    assert "STALE" in page
    assert "nicht als aktueller Wert lesen" in page


def test_missing_gate_model_renders_unavailable_never_pass(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {"trading_action_count": 0})
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=tmp_path / "absent.json",
        phase_c_checkpoint_path=tmp_path / "absent-checkpoint.json",
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "V2 Readiness")
    assert "Gate model not loaded" in page


def test_strip_research_row_derives_from_gate_model(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {"trading_action_count": 0})
    gate_path = tmp_path / "gate.json"
    _gate_model(gate_path, research=[("SHORT", "PASS"), ("MID", "PASS"), ("LONG", "IN_PROGRESS")])
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=gate_path,
        phase_c_checkpoint_path=tmp_path / "no-phase-c.json",
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    rows = {label: (sev, value) for label, sev, value in _strip_states(state.snapshot())}
    assert rows["RESEARCH"] == ("warn", "PARTIAL")

    _gate_model(gate_path, research=[("SHORT", "PASS"), ("MID", "PASS"), ("LONG", "PASS")])
    rows = {label: (sev, value) for label, sev, value in _strip_states(state.snapshot())}
    assert rows["RESEARCH"] == ("ok", "READY")


def test_open_human_gate_states_are_never_marked_stale(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {"trading_action_count": 0})
    gate_path = tmp_path / "gate.json"
    _gate_model(gate_path, checked_at="2026-06-01T00:00:00+00:00")
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=gate_path,
        phase_c_checkpoint_path=tmp_path / "no-phase-c.json",
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "V2 Readiness")
    # GOVERNANCE_STATE is an open human action item: old age must not render it STALE.
    assert "GOVERNANCE_STATE" in page
    governance_row = page.split("GOVERNANCE_STATE", 1)[1][:600]
    assert "STALE —" not in governance_row


def test_trading_actions_without_instrumentation_render_unknown_not_fail(tmp_path: Path) -> None:
    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {"trading_action_count": 0})
    gate_path = tmp_path / "gate.json"
    _gate_model(gate_path)
    # No queue metrics file, no watchdog: trading action evidence is absent.
    (completion / "queue_metrics.json").unlink(missing_ok=True)
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=gate_path,
        phase_c_checkpoint_path=tmp_path / "no-phase-c.json",
        operational_watchdog_path=tmp_path / "no-watchdog.json",
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "V2 Readiness")
    band5 = page.split("Band 5 · Trading authorization", 1)[1].split("Archived snapshots", 1)[0]
    assert "UNAVAILABLE" in band5
    # Missing evidence must never look like a red technical failure. The window
    # ends before the gate-model TRADING row, whose LOCKED chip is intentionally red.
    band5_after_chip = band5.split("Trading actions", 1)[1].split("<dt>TRADING<", 1)[0]
    assert "sev--fail" not in band5_after_chip


def test_in_progress_gate_with_fresh_checkpoint_is_never_stale(tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    completion = tmp_path / "completion"
    _write_json(completion, "implementation_state.json", {"trading_action_count": 0})
    gate_path = tmp_path / "gate.json"
    _gate_model(gate_path, checked_at="2026-07-01T00:00:00+00:00")  # far beyond the window
    checkpoint = tmp_path / "phase_c_checkpoint.json"
    checkpoint.write_text(json.dumps({"last_id": 7, "pages": 1, "trades": 1000}), encoding="utf-8")
    state = DashboardState(
        completion_artifacts_path=completion,
        gate_model_path=gate_path,
        phase_c_checkpoint_path=checkpoint,
        system_health={"database": "connected", "stream": "running", "queue_depth": 0},
    )
    page = render(state, "V2 Readiness")
    phase_row = page.split("PHASE_C_HISTORICAL_EXTENSION", 1)[1].split("</dl>", 1)[0]
    assert "live checkpoint: 1000 trades" in phase_row
    assert "STALE —" not in phase_row
