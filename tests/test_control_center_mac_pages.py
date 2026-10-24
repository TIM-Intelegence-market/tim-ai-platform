"""Control Center pages on the Mac live setup (review of 22.10.2026).

The Mac runs the V2 qualification campaign from data/qualification, has no V1
validator and no tim_maintenance.py timer. These tests pin that the pages read
the Mac's real evidence instead of showing NOT STARTED, 0 events or MISSING.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard.operations import build_operations_snapshot, render_operations_page
from src.dashboard.state import DashboardState
from src.dashboard.views import render

NOW = datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _campaign(root: Path) -> Path:
    qualification = root / "data/qualification"
    _write(qualification / "qualification_campaign.json", {
        "campaign_status": "ACTIVE", "dataset_id": "V2_PROSPECTIVE_QUALIFICATION_V1",
        "start_utc": "2026-10-20T20:34:00Z", "activated_at_utc": "2026-10-20T20:33:42Z",
        "case_target": 1000, "coverage_target": 0.95,
        "duration": {"pre_registered_minimum_days": 34},
    })
    for day, generated, observed, cases in (("2026-10-20", "2026-10-21T00:31:41Z", 206, 6), ("2026-10-21", "2026-10-22T00:32:08Z", 1440, 54)):
        _write(qualification / "daily" / f"{day}.json", {
            "generated_at_utc": generated,
            "metrics": {"coverage": 1.0, "cumulative_coverage": 1.0, "observed_minutes": observed, "expected_minutes": observed,
                        "gap_count": 0, "independent_case_count": cases, "independent_case_target": 1000},
        })
    return qualification


def _operational(root: Path) -> Path:
    operational = root / "data/operational"
    _write(operational / "watchdog_status.json", {"status": "GREEN", "checked_at": _iso(NOW), "checks": {}})
    _write(operational / "history_recovery.json", {"status": "PASS", "checked_at": _iso(NOW), "errors": [], "candles_rebuilt": 0})
    _write(operational / "backup_last_run.json", {"status": "PASS", "completed_at": _iso(NOW - timedelta(hours=14)), "bytes": 7_280_104_192})
    lines = []
    for minutes, status, failing in ((30, "YELLOW", "log_growth"), (20, "YELLOW", "log_growth"), (10, "RED", "dashboard"), (9, "YELLOW", "log_growth")):
        lines.append(json.dumps({"timestamp": _iso(NOW - timedelta(minutes=minutes)), "event": "WATCHDOG_CHECK", "status": status,
                                 "checks": {failing: {"status": "RED" if status == "RED" else "YELLOW"}}}))
    (operational / "watchdog.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return operational


def _snapshot(root: Path) -> dict:
    operational = _operational(root)
    qualification = _campaign(root)
    return build_operations_snapshot(
        {"timestamp": _iso(NOW), "operational_health": {}},
        root / "missing_completion", root / "missing_legacy",
        operational / "watchdog_status.json", operational / "rolling_liveness.json", qualification,
    )


def test_running_campaign_replaces_not_started_and_zero_cases(tmp_path: Path) -> None:
    data = _snapshot(tmp_path)
    assert data["qualification"]["status"] == "ACTIVE"
    assert data["qualification"]["started_at"] == "2026-10-20T20:34:00Z"
    assert data["qualification"]["manifests_written"] == 2
    cases = data["independent_cases"]
    assert (cases["qualification"], cases["required"], cases["status"]) == (54, 1000, "TIME GATE")
    campaign_room = next(item for item in data["datasets"] if item["label"] == "Prospective Qualification Campaign")
    assert (campaign_room["observed"], campaign_room["expected"], campaign_room["status"]) == (1646, 1646, "ACTIVE")
    page = render_operations_page("Qualification", data)
    assert "ACTIVE" in page and "NOT STARTED" not in page


def test_campaign_reaching_target_waits_for_human_approval(tmp_path: Path) -> None:
    qualification = _campaign(tmp_path)
    _write(qualification / "daily" / "2026-11-24.json", {"generated_at_utc": "2026-11-25T00:30:00Z",
                                                         "metrics": {"independent_case_count": 1000, "independent_case_target": 1000}})
    data = build_operations_snapshot({"timestamp": _iso(NOW)}, tmp_path / "x", tmp_path / "y",
                                     tmp_path / "w.json", tmp_path / "r.json", qualification)
    assert data["independent_cases"]["status"] == "PENDING HUMAN APPROVAL"


def test_without_campaign_files_old_sources_still_apply(tmp_path: Path) -> None:
    data = build_operations_snapshot({"timestamp": _iso(NOW)}, tmp_path / "x", tmp_path / "y",
                                     tmp_path / "w.json", tmp_path / "r.json", tmp_path / "no_campaign")
    assert data["qualification"]["manifests_written"] == "UNAVAILABLE"
    assert data["independent_cases"]["qualification"] == "UNAVAILABLE"


def test_history_recovery_stands_in_for_missing_maintenance_report(tmp_path: Path) -> None:
    data = _snapshot(tmp_path)
    maintenance = data["current_status"]["maintenance"]
    assert maintenance["status"] == "PASS"
    assert maintenance["source"].endswith("history_recovery.json")


def test_timeline_uses_mac_operational_sources(tmp_path: Path) -> None:
    operational = _operational(tmp_path)
    state = DashboardState(
        events_path=operational / "events.jsonl", validator_path=operational / "state.json",
        operational_watchdog_path=operational / "watchdog_status.json",
        qualification_root_path=_campaign(tmp_path),
    )
    events = state.snapshot()["timeline"]
    kinds = [item["event"] for item in events]
    assert kinds.count("QUALIFICATION_DAY") == 2 and "QUALIFICATION_START" in kinds and "DB_BACKUP" in kinds
    transitions = [(item["previous_status"], item["new_status"]) for item in events if item["event"] == "WATCHDOG_STATUS"]
    assert transitions == [("YELLOW", "RED"), ("RED", "YELLOW")]
    assert [item["timestamp"] for item in events] == sorted((item["timestamp"] for item in events), key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")))
    page = render(state, "Timeline")
    assert "Keine Systemereignisse verfügbar" not in page and "QUALIFICATION_DAY" in page
    # The red watchdog cycle is a real incident and shows up with its time and cause.
    incidents = render(state, "Incidents & Gaps")
    assert "WATCHDOG_STATUS" in incidents and "Prüfungen: dashboard" in incidents


def test_health_center_explains_missing_v1_archive(tmp_path: Path) -> None:
    state = DashboardState(validator_path=tmp_path / "state.json", readiness_path=tmp_path / "r.json",
                           audit_path=tmp_path / "a.json", quality_path=tmp_path / "q.json", events_path=tmp_path / "e.jsonl")
    page = render(state, "Health Center")
    assert "kein V1-Archiv" in page
    assert "None%" not in page


def test_log_growth_finding_is_readable(tmp_path: Path) -> None:
    operational = tmp_path / "data/operational"
    _write(operational / "watchdog_status.json", {"status": "YELLOW", "checked_at": _iso(NOW), "checks": {
        "log_growth": {"status": "YELLOW", "value": {"largest_bytes": 12_582_912, "path": "/x/data/operational/watchdog_launchd.log"}}}})
    data = build_operations_snapshot({"timestamp": _iso(NOW)}, tmp_path / "x", tmp_path / "y",
                                     operational / "watchdog_status.json", tmp_path / "r.json", tmp_path / "q")
    assert data["runtime"]["logs"]["value"] == "größte Logdatei 12.0 MB · watchdog_launchd.log"


def test_server_health_checks_the_mac_backup_folder(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import tim_server_health
    monkeypatch.setattr(tim_server_health.sys, "platform", "darwin")
    assert tim_server_health.default_backup_dir() == Path.home() / "Library/Application Support/TIM/backups/live"
    monkeypatch.setattr(tim_server_health.sys, "platform", "linux")
    assert tim_server_health.default_backup_dir() == Path("/var/backups/tim")


def test_watchdog_loop_prints_only_status_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import tim_watchdog

    statuses = iter(["YELLOW", "YELLOW", "YELLOW", "GREEN"])

    class FakeWatchdog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def collect(self) -> dict:
            status = next(statuses)
            if status == "GREEN":
                stop_event.set()
            return {"status": status, "mode": "OBSERVE", "trading_actions": 0, "checks": {}, "checked_at": _iso(NOW)}

    async def no_wait(awaitable, timeout):  # skip the 30 s pause between cycles
        awaitable.close()
        raise TimeoutError

    stop_event = asyncio.Event()
    monkeypatch.setattr(tim_watchdog, "ROOT", tmp_path)
    monkeypatch.setattr(tim_watchdog, "IndependentWatchdog", FakeWatchdog)
    monkeypatch.setattr(tim_watchdog, "settings", type("S", (), {"database_url": "postgresql://test", "symbol": "BTCUSDT"})())
    monkeypatch.setattr(tim_watchdog.asyncio, "Event", lambda: stop_event)
    monkeypatch.setattr(tim_watchdog.asyncio, "wait_for", no_wait)
    (tmp_path / "data/operational").mkdir(parents=True)
    code = asyncio.run(tim_watchdog.run(once=False, interval=0.0, required_red_cycles=3, cooldown_seconds=300, restart_timeout=1))
    out = capsys.readouterr().out
    lines = [json.loads(line) for line in out.splitlines() if line.strip()]
    assert [line["status"] for line in lines] == ["YELLOW", "GREEN"]
    assert code == 0


def test_signal_research_counts_unvalidated_observations_as_open() -> None:
    # Before, only incomplete validation records counted, so the page said
    # "0 open validations" next to a validation queue of 61.
    observations = [{"observation_id": f"o{i}", "kind": "LARGE_INDIVIDUAL_TRADE_ACTIVITY", "observed_at": _iso(NOW - timedelta(minutes=i)),
                     "rule_version": "1.0.0", "timeframe": "60s", "evidence": []} for i in range(3)]
    state = DashboardState(orderflow_observations=observations,
                           orderflow_validations=[{"observation_id": "o2", "complete": True, "outcome": "PRICE_FLAT"}])
    page = render(state, "Signal Research")
    assert "Offene Validierungen:</b> 2" in page


def test_observation_status_in_progress_is_not_red() -> None:
    # Regression: the Observations page used the generic health mapping, so
    # COLLECTING_EVIDENCE and OPEN showed as red error badges.
    observation = {"observation_id": "obs-1", "kind": "FAILED_CONTINUATION", "observed_at": _iso(NOW), "rule_version": "1.0.0",
                   "evidence_score": 70, "provenance": "PUBLIC_MARKET_DATA_DETERMINISTIC",
                   "research_case_id": "case-1", "research_case_status": "COLLECTING_EVIDENCE"}
    state = DashboardState(active_observations=[observation],
                           research_cases=[{"case_id": "case-1", "status": "COLLECTING_EVIDENCE", "observation_ids": ["obs-1"]}])
    page = render(state, "Observations")
    row = page.split("data-status='COLLECTING_EVIDENCE'", 1)[1].split("</tr>", 1)[0]
    assert "badge--yellow" in row and "badge--red" not in row
