import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.agents.contract import ReplayMismatch, RunRecord, replay, run_task
from src.agents.monitoring import (
    BUILD_REPORT,
    SPEC,
    assess,
    collect_snapshot,
    render_report,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = "2026-09-29T20:00:00+00:00"


class FakeRegistry:
    def __init__(self, statuses):
        self.statuses = statuses

    def refresh(self):
        return {name: {"state": state, "evidence": f"{name} probe", "observed_at": NOW}
                for name, state in self.statuses.items()}


def state(**overrides):
    value = {"phase": "MISSION_04_BOUNDED_COLLECTION", "status": "RUNNING", "blockers": [],
             "revision": 7, "updated_at": "2026-09-29T19:58:00+00:00",
             "last_health": {"live_trading": False, "trading_actions": 0,
                             "infrastructure_ok": True, "unknown_errors": 0}}
    value.update(overrides)
    return value


def write_state(tmp_path, value):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


def snapshot(tmp_path, *, tools=None, orchestration=None, readiness_result=None, manifest=True):
    return collect_snapshot(
        orchestration_state=None if orchestration is None else write_state(tmp_path, orchestration),
        readiness_manifest=(tmp_path / "manifest.json") if manifest else None,
        readiness=lambda *_args, **_kwargs: readiness_result or {
            "LIVE_DATA_READINESS": "PASS", "blockers": [], "live_trading": False,
            "execution": False, "checked_at": NOW},
        tool_registry=FakeRegistry(tools or {"Ollama": "AVAILABLE", "Qwen": "AVAILABLE",
                                             "Serena": "AVAILABLE", "pytest": "AVAILABLE"}),
        clock=lambda: NOW)


def test_spec_forbids_restart_repair_and_release():
    assert {"tim_runtime_restart", "release_approval", "repair_execution",
            "trading_actions"} <= set(SPEC.forbidden_actions)
    assert set(SPEC.allowed_actions) == {"read_health_sources", "build_health_report",
                                         "write_health_report"}


def test_healthy_sources_are_green(tmp_path):
    report = assess(snapshot(tmp_path, orchestration=state()))
    assert report["overall"] == "GREEN"
    assert {k: v["status"] for k, v in report["sources"].items()} == {
        "tools": "GREEN", "orchestration": "GREEN", "readiness": "GREEN"}


def test_missing_sources_are_unknown_never_green(tmp_path):
    report = assess(collect_snapshot(probe_tools=False, clock=lambda: NOW))
    assert report["overall"] == "UNKNOWN"
    assert all(entry["status"] == "UNKNOWN" for entry in report["sources"].values())


def test_unreadable_or_missing_state_file_is_unknown(tmp_path):
    broken = assess(snapshot(tmp_path, orchestration="{not json"))
    assert broken["sources"]["orchestration"]["status"] == "UNKNOWN"
    missing = assess(collect_snapshot(orchestration_state=tmp_path / "nope.json",
                                      probe_tools=False, clock=lambda: NOW))
    assert missing["sources"]["orchestration"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("overrides,reason", [
    ({"status": "SAFE_STOP", "phase": "SAFE_STOP"}, "SAFE_STOP"),
    ({"blockers": ["cursor_invalid"]}, "Blocker: cursor_invalid"),
    ({"last_health": {"live_trading": True}}, "Live-Trading"),
    ({"last_health": {"trading_actions": 2}}, "Live-Trading"),
    ({"last_health": {"infrastructure_ok": False}}, "Infrastruktur"),
])
def test_orchestration_problems_are_red(tmp_path, overrides, reason):
    entry = assess(snapshot(tmp_path, orchestration=state(**overrides)))["sources"]["orchestration"]
    assert entry["status"] == "RED"
    assert any(reason in r for r in entry["reasons"])


def test_stale_state_and_unknown_errors_are_yellow(tmp_path):
    stale = state(updated_at="2026-09-29T19:00:00+00:00")
    entry = assess(snapshot(tmp_path, orchestration=stale))["sources"]["orchestration"]
    assert entry["status"] == "YELLOW" and "3600 s alt" in entry["reasons"][0]
    errors = state(last_health={"unknown_errors": 3})
    assert assess(snapshot(tmp_path, orchestration=errors))["sources"]["orchestration"]["status"] == "YELLOW"


@pytest.mark.parametrize("value", [state(last_health={"trading_actions": "many"}),
                                   state(last_health=["not", "a", "dict"])])
def test_malformed_state_is_unknown_not_a_crash(tmp_path, value):
    entry = assess(snapshot(tmp_path, orchestration=value))["sources"]["orchestration"]
    assert entry["status"] == "UNKNOWN"


def test_naive_state_timestamp_is_unknown(tmp_path):
    entry = assess(snapshot(tmp_path, orchestration=state(updated_at="2026-09-29T19:58:00")))
    assert entry["sources"]["orchestration"]["status"] == "UNKNOWN"


def test_tool_states_map_to_statuses(tmp_path):
    report = assess(snapshot(tmp_path, orchestration=state(),
                             tools={"Serena": "AVAILABLE", "Graphify": "DEGRADED", "Qwen": "WEIRD"}))
    items = report["sources"]["tools"]["items"]
    assert [items[n]["status"] for n in ("Graphify", "Qwen", "Serena")] == ["YELLOW", "UNKNOWN", "GREEN"]
    assert report["sources"]["tools"]["status"] == "UNKNOWN"


def test_readiness_safe_stop_is_yellow_and_trading_is_red(tmp_path):
    safe_stop = {"LIVE_DATA_READINESS": "SAFE_STOP", "blockers": ["queue_evidence_missing"],
                 "live_trading": False, "execution": False}
    entry = assess(snapshot(tmp_path, orchestration=state(), readiness_result=safe_stop))
    assert entry["sources"]["readiness"]["status"] == "YELLOW"
    assert "queue_evidence_missing" in entry["sources"]["readiness"]["reasons"][0]
    trading = {**safe_stop, "live_trading": True}
    assert assess(snapshot(tmp_path, orchestration=state(),
                           readiness_result=trading))["overall"] == "RED"


def test_real_readiness_gate_without_evidence_is_not_green(tmp_path):
    report = assess(collect_snapshot(readiness_manifest=tmp_path / "missing.json", repo_root=ROOT,
                                     probe_tools=False, clock=lambda: NOW))
    assert report["sources"]["readiness"]["status"] == "YELLOW"


def test_report_is_replayable_and_tamper_evident(tmp_path):
    record = run_task(SPEC, assess, snapshot(tmp_path, orchestration=state()), action=BUILD_REPORT)
    restored = RunRecord.from_dict(json.loads(json.dumps(record.to_dict())))
    assert replay(SPEC, assess, restored) == record
    with pytest.raises(ReplayMismatch):
        replay(SPEC, lambda s: {**assess(s), "overall": "GREEN", "x": 1}, restored)


def test_render_says_green_is_not_a_release(tmp_path):
    text = render_report(assess(snapshot(tmp_path, orchestration=state())))
    assert "keine Freigabe" in text and "## orchestration: `GREEN`" in text


def test_cli_writes_record_and_replays(tmp_path):
    path = write_state(tmp_path, state())
    record = tmp_path / "health.json"
    done = subprocess.run([sys.executable, "scripts/tim_monitoring_agent.py", "--no-tool-probes",
                           "--orchestration-state", str(path), "--max-state-age", "999999999",
                           "--record-path", str(record)],
                          cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert "## orchestration: `GREEN`" in done.stdout
    again = subprocess.run([sys.executable, "scripts/tim_monitoring_agent.py", "--replay", str(record)],
                           cwd=ROOT, capture_output=True, text=True)
    assert again.returncode == 0 and "Replay OK" in again.stdout


def test_required_tool_unavailable_is_red_optional_is_yellow(tmp_path):
    report = assess(snapshot(tmp_path, orchestration=state(),
                             tools={"Ollama": "AVAILABLE", "Qwen": "UNAVAILABLE", "Serena": "UNAVAILABLE"}))
    tools = report["sources"]["tools"]
    assert tools["items"]["Qwen"]["status"] == "RED" and tools["items"]["Qwen"]["required"] is True
    assert tools["items"]["Serena"]["status"] == "YELLOW" and tools["items"]["Serena"]["required"] is False
    assert tools["status"] == "RED" and report["overall"] == "RED"
    assert "Qwen (Pflicht): UNAVAILABLE" in tools["reasons"]
    assert "Qwen: RED · Pflicht" in render_report(report)


def test_required_tool_not_probed_is_unknown_never_green(tmp_path):
    report = assess(snapshot(tmp_path, orchestration=state(), tools={"Ollama": "AVAILABLE"}))
    item = report["sources"]["tools"]["items"]["Qwen"]
    assert item["status"] == "UNKNOWN" and item["evidence"] == "Pflicht-Werkzeug nicht geprüft"
    assert report["sources"]["tools"]["status"] == "UNKNOWN"


def test_only_optional_tools_missing_stays_yellow(tmp_path):
    report = assess(snapshot(tmp_path, orchestration=state(),
                             tools={"Ollama": "AVAILABLE", "Qwen": "AVAILABLE", "Graphify": "UNAVAILABLE"}))
    assert report["sources"]["tools"]["status"] == "YELLOW"


def test_snapshot_without_required_list_keeps_the_old_behaviour(tmp_path):
    snap = snapshot(tmp_path, orchestration=state(), tools={"Qwen": "UNAVAILABLE"})
    del snap["sources"]["tools"]["required"]
    items = assess(snap)["sources"]["tools"]["items"]
    assert items == {"Qwen": {"status": "YELLOW", "state": "UNAVAILABLE", "evidence": "Qwen probe",
                              "observed_at": NOW}}
