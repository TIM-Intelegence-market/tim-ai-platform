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
    for stage in ("Source", "Ingest", "Queue", "Persist", "Cursor", "Candles", "Quality", "Research", "Readiness"):
        assert f"<b>{stage}</b>" in page
    assert page.count("pipeline__stage") >= 9


def test_uninstrumented_cursor_stage_stays_unknown(tmp_path: Path) -> None:
    empty = tmp_path / "empty-completion"
    empty.mkdir(parents=True, exist_ok=True)
    state = DashboardState(
        completion_artifacts_path=empty,
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


def test_grouped_navigation_has_five_labelled_groups(tmp_path: Path) -> None:
    page = render(_state(tmp_path))
    for group in ("OPERATIONS", "RESEARCH", "READINESS", "INTELLIGENCE", "SYSTEM"):
        assert f"<p class='nav__label'>{group}</p>" in page
    assert page.count("class='nav__group'") == 5
