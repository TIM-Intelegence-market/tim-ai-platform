from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MissionPhase(StrEnum):
    M01_RECOVERY = "MISSION_01_OPERATIONAL_RECOVERY"
    M05_CATCHUP = "MISSION_05_FINAL_CATCHUP"
    M05_IDLE_VALIDATION = "MISSION_05_IDLE_VALIDATION"
    M05_CURSOR_CHECK = "MISSION_05_CURSOR_CHECK"
    M05_GAP_CLASSIFICATION = "MISSION_05_GAP_CLASSIFICATION"
    M04_PREFLIGHT = "MISSION_04_PREFLIGHT"
    M04_COLLECTION = "MISSION_04_BOUNDED_COLLECTION"
    M02_INTELLIGENCE = "MISSION_02_TRADING_INTELLIGENCE"
    M03_VALIDATION = "MISSION_03_VALIDATION_SHADOW_PAPER"
    SAFE_STOP = "SAFE_STOP"


CHAIN = (
    MissionPhase.M01_RECOVERY,
    MissionPhase.M05_CATCHUP,
    MissionPhase.M05_IDLE_VALIDATION,
    MissionPhase.M05_CURSOR_CHECK,
    MissionPhase.M05_GAP_CLASSIFICATION,
    MissionPhase.M04_PREFLIGHT,
    MissionPhase.M04_COLLECTION,
    MissionPhase.M02_INTELLIGENCE,
    MissionPhase.M03_VALIDATION,
)


@dataclass(frozen=True, slots=True)
class OrchestrationConfig:
    artifact_root: Path
    active_interval_seconds: float = 10.0
    idle_interval_seconds: float = 60.0
    infrastructure_backoff_base_seconds: float = 5.0
    infrastructure_backoff_max_seconds: float = 300.0
    unknown_error_cap: int = 3
    max_helper_jobs: int = 1
    helper_agents_enabled: bool = False
    cpu_budget_percent: float = 75.0
    memory_budget_percent: float = 75.0
    collection_max_events: int = 10_000
    production_database_name: str = "tim"
    mission03_release_file: Path | None = None

    def __post_init__(self) -> None:
        if self.unknown_error_cap < 1 or self.max_helper_jobs < 0:
            raise ValueError("invalid orchestration limits")
        if not (0 < self.cpu_budget_percent <= 100 and 0 < self.memory_budget_percent <= 100):
            raise ValueError("resource budgets must be in (0, 100]")


@dataclass(slots=True)
class HealthSnapshot:
    status_counts: dict[str, int]
    gaps_open: int
    gaps_unclassified: int
    cursor: int | None
    last_completed_at: str | None
    runtime_pid: int | None
    runtime_state: str
    restarts: int = 0
    memory_percent: float = 0.0
    cpu_percent: float = 0.0
    db_latency_ms: float = 0.0
    log_rate_per_minute: float = 0.0
    infrastructure_ok: bool = True
    cursor_valid: bool = True
    idle_validation_passed: bool = False
    gap_classification_passed: bool = False
    mission04_preflight_passed: bool = False
    live_trading: bool = False
    trading_actions: int = 0
    parallel_mutating_jobs: int = 0
    active_workers: int = 1
    unknown_errors: int = 0

    @property
    def pending(self) -> int:
        return int(self.status_counts.get("PENDING", 0))


@dataclass(slots=True)
class OrchestrationState:
    phase: MissionPhase = MissionPhase.M01_RECOVERY
    previous_phase: MissionPhase | None = None
    status: str = "RUNNING"
    run_id: str = ""
    revision: int = 0
    completed_jobs: dict[str, str] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    unknown_error_count: int = 0
    infrastructure_failures: int = 0
    last_health: dict[str, Any] = field(default_factory=dict)
    last_completed_at: str | None = None
    next_run_at: str | None = None
    updated_at: str = field(default_factory=utc_now)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OrchestrationState":
        payload = dict(value)
        payload["phase"] = MissionPhase(payload["phase"])
        if payload.get("previous_phase"):
            payload["previous_phase"] = MissionPhase(payload["previous_phase"])
        return cls(**payload)


class Jobs(Protocol):
    def run(self, name: str, *, idempotency_key: str, limit: int | None = None) -> Mapping[str, Any]: ...


class SafeStop(RuntimeError):
    pass


class WorkerLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any = None

    def __enter__(self) -> "WorkerLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+")
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.handle.close()
            raise SafeStop("another orchestrator worker holds the lock") from exc
        self.handle.seek(0); self.handle.truncate(); self.handle.write(str(os.getpid())); self.handle.flush()
        return self

    def __exit__(self, *_: object) -> None:
        if self.handle:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


class Orchestrator:
    """One-tick deterministic coordinator. AI output never participates in gates."""

    def __init__(self, config: OrchestrationConfig, health: Callable[[], HealthSnapshot], jobs: Jobs) -> None:
        self.config, self.health_provider, self.jobs = config, health, jobs
        self.root = config.artifact_root.resolve()
        self.state_path = self.root / "state.json"
        self.history_path = self.root / "history.jsonl"
        self.report_path = self.root / "latest_report.md"
        self.lock_path = self.root / "orchestrator.lock"

    def load(self) -> OrchestrationState:
        if not self.state_path.exists():
            return OrchestrationState(run_id=f"run-{int(time.time())}")
        return OrchestrationState.from_dict(json.loads(self.state_path.read_text(encoding="utf-8")))

    def tick(self) -> OrchestrationState:
        with WorkerLock(self.lock_path):
            state = self.load()
            snapshot = self.health_provider()
            blockers = self._safety_blockers(snapshot)
            if blockers:
                return self._stop(state, blockers, snapshot)
            if not snapshot.infrastructure_ok:
                state.infrastructure_failures += 1
                self._schedule(state, self.backoff_seconds(state.infrastructure_failures))
                state.blockers = ["infrastructure unavailable; deterministic backoff active"]
                return self._persist(state, snapshot, "BACKOFF")
            state.infrastructure_failures = 0
            if snapshot.unknown_errors:
                state.unknown_error_count += snapshot.unknown_errors
                if state.unknown_error_count >= self.config.unknown_error_cap:
                    return self._stop(state, ["unknown error retry cap reached"], snapshot)
            try:
                state = self._advance(state, snapshot)
            except SafeStop as exc:
                return self._stop(state, [str(exc)], snapshot)
            interval = self.config.active_interval_seconds if snapshot.pending else self.config.idle_interval_seconds
            self._schedule(state, interval)
            return self._persist(state, snapshot, "TICK")

    def _advance(self, state: OrchestrationState, h: HealthSnapshot) -> OrchestrationState:
        if state.phase is MissionPhase.M01_RECOVERY:
            return self._transition(state, MissionPhase.M05_CATCHUP)
        if state.phase is MissionPhase.M05_CATCHUP and h.pending == 0 and not h.status_counts.get("PROCESSING", 0) and not h.status_counts.get("RETRY", 0):
            return self._transition(state, MissionPhase.M05_IDLE_VALIDATION)
        if state.phase is MissionPhase.M05_IDLE_VALIDATION:
            if not h.idle_validation_passed: return state
            self._job_once(state, "idle_validation")
            return self._transition(state, MissionPhase.M05_CURSOR_CHECK)
        if state.phase is MissionPhase.M05_CURSOR_CHECK:
            if not h.cursor_valid or h.cursor is None: return self._stop(state, ["cursor validation failed"], h)
            self._job_once(state, "cursor_check")
            return self._transition(state, MissionPhase.M05_GAP_CLASSIFICATION)
        if state.phase is MissionPhase.M05_GAP_CLASSIFICATION:
            self._job_once(state, "gap_classification")
            if not h.gap_classification_passed or h.gaps_unclassified: return state
            return self._transition(state, MissionPhase.M04_PREFLIGHT)
        if state.phase is MissionPhase.M04_PREFLIGHT:
            self._job_once(state, "mission04_preflight")
            if not h.mission04_preflight_passed: return self._stop(state, ["Mission 04 preflight did not pass"], h)
            return self._transition(state, MissionPhase.M04_COLLECTION)
        if state.phase is MissionPhase.M04_COLLECTION:
            self._job_once(state, "bounded_collection", limit=self.config.collection_max_events)
        return state

    def _job_once(self, state: OrchestrationState, name: str, *, limit: int | None = None) -> None:
        key = f"{state.run_id}:{state.phase}:{name}"
        if key in state.completed_jobs: return
        result = dict(self.jobs.run(name, idempotency_key=key, limit=limit))
        if result.get("trading_actions", 0) != 0 or result.get("live_trading", False):
            raise SafeStop(f"job {name} violated observe-only contract")
        if result.get("status") not in {"PASS", "COMPLETED", "ALREADY_COMPLETED"}:
            raise SafeStop(f"job {name} failed closed: {result.get('status', 'UNKNOWN')}")
        state.completed_jobs[key] = utc_now()

    def _safety_blockers(self, h: HealthSnapshot) -> list[str]:
        blockers = []
        if h.live_trading or h.trading_actions != 0: blockers.append("trading is forbidden before explicit Mission 03 release")
        if h.active_workers != 1: blockers.append("exactly one TIM worker is required")
        if h.parallel_mutating_jobs: blockers.append("parallel recovery/drain/backfill job detected")
        if h.cpu_percent > self.config.cpu_budget_percent: blockers.append("CPU budget exceeded")
        if h.memory_percent > self.config.memory_budget_percent: blockers.append("memory budget exceeded")
        return blockers

    def helper_job_allowed(self, active_helpers: int, *, read_only: bool) -> bool:
        return bool(self.config.helper_agents_enabled and read_only and active_helpers < self.config.max_helper_jobs)

    def assert_database_target(self, database_name: str, *, testing: bool) -> None:
        if testing and database_name == self.config.production_database_name:
            raise SafeStop("tests may not target the production database")

    def mission03_released(self) -> bool:
        path = self.config.mission03_release_file
        if path is None or not path.is_file(): return False
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value == {"mission": "MISSION_03", "released": True, "trading_actions": 0}
        except (OSError, ValueError):
            return False

    def backoff_seconds(self, failures: int) -> float:
        return min(self.config.infrastructure_backoff_max_seconds, self.config.infrastructure_backoff_base_seconds * (2 ** max(0, failures - 1)))

    def _transition(self, state: OrchestrationState, target: MissionPhase) -> OrchestrationState:
        if state.phase not in CHAIN or target not in CHAIN or CHAIN.index(target) != CHAIN.index(state.phase) + 1:
            raise SafeStop(f"illegal mission transition {state.phase} -> {target}")
        state.previous_phase, state.phase = state.phase, target
        state.last_completed_at = utc_now()
        return state

    def _stop(self, state: OrchestrationState, blockers: list[str], h: HealthSnapshot) -> OrchestrationState:
        state.previous_phase, state.phase, state.status, state.blockers = state.phase, MissionPhase.SAFE_STOP, "SAFE_STOP", sorted(set(blockers))
        return self._persist(state, h, "SAFE_STOP")

    def _schedule(self, state: OrchestrationState, seconds: float) -> None:
        state.next_run_at = datetime.fromtimestamp(time.time() + seconds, timezone.utc).isoformat()

    def _persist(self, state: OrchestrationState, h: HealthSnapshot, event: str) -> OrchestrationState:
        self.root.mkdir(parents=True, exist_ok=True)
        state.revision += 1; state.updated_at = utc_now(); state.last_health = asdict(h)
        payload = asdict(state)
        self._atomic_json(self.state_path, payload)
        history = {"event": event, "at": state.updated_at, "revision": state.revision, "phase": state.phase, "status": state.status, "blockers": state.blockers}
        with self.history_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(history, sort_keys=True, default=str) + "\n"); stream.flush(); os.fsync(stream.fileno())
        self._atomic_text(self.report_path, self._report(state, h))
        return state

    @staticmethod
    def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
        Orchestrator._atomic_text(path, json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")

    @staticmethod
    def _atomic_text(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(value); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            if os.path.exists(name): os.unlink(name)

    @staticmethod
    def _report(state: OrchestrationState, h: HealthSnapshot) -> str:
        return "\n".join((
            "# TIM Orchestration Status", "", f"- Status: {state.status}", f"- Current phase: {state.phase}",
            f"- Previous phase: {state.previous_phase or 'NONE'}", f"- Revision: {state.revision}",
            f"- Pending/Processing/Retry/Quarantined: {h.pending}/{h.status_counts.get('PROCESSING', 0)}/{h.status_counts.get('RETRY', 0)}/{h.status_counts.get('QUARANTINED', 0)}",
            f"- Cursor: {h.cursor}", f"- Open/unclassified gaps: {h.gaps_open}/{h.gaps_unclassified}",
            f"- Runtime: PID={h.runtime_pid} state={h.runtime_state} restarts={h.restarts}",
            f"- Resources: CPU={h.cpu_percent:.1f}% memory={h.memory_percent:.1f}% DB={h.db_latency_ms:.1f}ms logs={h.log_rate_per_minute:.1f}/min",
            "- Live trading: DISABLED", "- Trading actions: 0", f"- Blockers: {', '.join(state.blockers) or 'NONE'}", ""
        ))
