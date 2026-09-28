from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.orchestration import HealthSnapshot, MissionPhase, OrchestrationConfig, Orchestrator, SafeStop
from src.orchestration.core import WorkerLock


class Jobs:
    def __init__(self) -> None: self.calls = []
    def run(self, name, *, idempotency_key, limit=None):
        self.calls.append((name, idempotency_key, limit))
        return {"status": "PASS", "live_trading": False, "trading_actions": 0}


class UnsafeJobs(Jobs):
    def run(self, name, *, idempotency_key, limit=None):
        return {"status": "PASS", "live_trading": True, "trading_actions": 1}


def health(**updates):
    value = HealthSnapshot(
        status_counts={"PENDING": 1, "PROCESSING": 0, "RETRY": 0, "QUARANTINED": 0},
        gaps_open=0, gaps_unclassified=0, cursor=100, last_completed_at=None,
        runtime_pid=123, runtime_state="RUNNING",
    )
    return replace(value, **updates)


def make(tmp_path: Path, snapshot: HealthSnapshot | None = None):
    jobs = Jobs(); current = [snapshot or health()]
    runner = Orchestrator(OrchestrationConfig(tmp_path), lambda: current[0], jobs)
    return runner, jobs, current


def test_state_transitions_and_pending_zero_chain(tmp_path):
    runner, _, current = make(tmp_path)
    assert runner.tick().phase is MissionPhase.M05_CATCHUP
    current[0] = health(status_counts={"PENDING": 0, "PROCESSING": 0, "RETRY": 0, "QUARANTINED": 0})
    assert runner.tick().phase is MissionPhase.M05_IDLE_VALIDATION
    current[0] = replace(current[0], idle_validation_passed=True)
    assert runner.tick().phase is MissionPhase.M05_CURSOR_CHECK
    assert runner.tick().phase is MissionPhase.M05_GAP_CLASSIFICATION


def test_resume_and_duplicate_job_is_idempotent(tmp_path):
    runner, jobs, current = make(tmp_path)
    runner.tick(); current[0] = health(status_counts={"PENDING": 0, "PROCESSING": 0, "RETRY": 0, "QUARANTINED": 0})
    runner.tick(); current[0] = replace(current[0], idle_validation_passed=True)
    runner.tick()
    resumed = Orchestrator(runner.config, lambda: current[0], jobs)
    assert resumed.load().phase is MissionPhase.M05_CURSOR_CHECK
    resumed.tick(); resumed.tick()
    assert [name for name, _, _ in jobs.calls].count("cursor_check") == 1


def test_single_worker_lock(tmp_path):
    lock = tmp_path / "one.lock"
    with WorkerLock(lock):
        with pytest.raises(SafeStop, match="another orchestrator"):
            with WorkerLock(lock): pass


def test_distinct_lifetime_scheduler_lock_rejects_duplicate(tmp_path):
    lock = tmp_path / "scheduler.lock"
    first = WorkerLock(lock)
    first.__enter__()
    try:
        with pytest.raises(SafeStop): WorkerLock(lock).__enter__()
    finally:
        first.__exit__()


@pytest.mark.parametrize("update,reason", [
    ({"live_trading": True}, "trading"), ({"trading_actions": 1}, "trading"),
    ({"active_workers": 2}, "exactly one"), ({"parallel_mutating_jobs": 1}, "parallel"),
    ({"cpu_percent": 99}, "CPU"), ({"memory_percent": 99}, "memory"),
])
def test_safe_stop(update, reason, tmp_path):
    runner, _, _ = make(tmp_path, health(**update))
    state = runner.tick()
    assert state.phase is MissionPhase.SAFE_STOP
    assert reason.lower() in " ".join(state.blockers).lower()


def test_gap_and_mission04_preflight_gating(tmp_path):
    runner, jobs, current = make(tmp_path)
    state = runner.load(); state.phase = MissionPhase.M05_GAP_CLASSIFICATION; runner._persist(state, current[0], "TEST")
    current[0] = replace(current[0], gaps_unclassified=1, gap_classification_passed=False)
    assert runner.tick().phase is MissionPhase.M05_GAP_CLASSIFICATION
    current[0] = replace(current[0], gaps_unclassified=0, gap_classification_passed=True)
    assert runner.tick().phase is MissionPhase.M04_PREFLIGHT
    assert runner.tick().phase is MissionPhase.SAFE_STOP
    assert not any(call[0] == "bounded_collection" for call in jobs.calls)


def test_mission04_pass_starts_only_bounded_collection(tmp_path):
    runner, jobs, current = make(tmp_path, health(mission04_preflight_passed=True))
    state = runner.load(); state.phase = MissionPhase.M04_PREFLIGHT; runner._persist(state, current[0], "TEST")
    assert runner.tick().phase is MissionPhase.M04_COLLECTION
    runner.tick()
    assert jobs.calls[-1][0] == "bounded_collection" and jobs.calls[-1][2] == 10_000


def test_unknown_error_cap_and_scheduler_backoff(tmp_path):
    runner, _, current = make(tmp_path, health(unknown_errors=1))
    assert runner.tick().phase is not MissionPhase.SAFE_STOP
    assert runner.tick().phase is not MissionPhase.SAFE_STOP
    assert runner.tick().phase is MissionPhase.SAFE_STOP
    assert [runner.backoff_seconds(n) for n in (1, 2, 3, 20)] == [5, 10, 20, 300]


def test_helper_budget_disable_and_production_test_db_guard(tmp_path):
    runner, _, _ = make(tmp_path)
    assert runner.helper_job_allowed(0, read_only=True) is False
    enabled = Orchestrator(replace(runner.config, helper_agents_enabled=True, max_helper_jobs=1), runner.health_provider, Jobs())
    assert enabled.helper_job_allowed(0, read_only=True) is True
    assert enabled.helper_job_allowed(1, read_only=True) is False
    assert enabled.helper_job_allowed(0, read_only=False) is False
    with pytest.raises(SafeStop, match="production database"):
        runner.assert_database_target("tim", testing=True)


def test_artifacts_and_no_mission03_release_by_default(tmp_path):
    runner, _, _ = make(tmp_path); runner.tick()
    assert {"state.json", "history.jsonl", "latest_report.md"} <= {p.name for p in tmp_path.iterdir()}
    payload = json.loads((tmp_path / "state.json").read_text())
    assert payload["last_health"]["trading_actions"] == 0
    assert runner.mission03_released() is False


def test_job_contract_violation_is_persisted_safe_stop(tmp_path):
    current = health(idle_validation_passed=True)
    runner = Orchestrator(OrchestrationConfig(tmp_path), lambda: current, UnsafeJobs())
    state = runner.load(); state.phase = MissionPhase.M05_IDLE_VALIDATION
    runner._persist(state, current, "TEST")
    assert runner.tick().phase is MissionPhase.SAFE_STOP
    assert Orchestrator(runner.config, lambda: current, Jobs()).load().status == "SAFE_STOP"
