#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.orchestration import OrchestrationConfig, Orchestrator, SafeStop
from src.orchestration.core import WorkerLock
from src.orchestration.runtime import HeadlessJobs, ProductionHealthProvider


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed TIM mission orchestrator")
    parser.add_argument("command", choices=("run", "tick", "status"))
    args = parser.parse_args()
    artifact_root = ROOT / "artifacts" / "orchestration"
    config = OrchestrationConfig(
        artifact_root=artifact_root,
        active_interval_seconds=float(os.getenv("TIM_ORCHESTRATOR_ACTIVE_SECONDS", "10")),
        idle_interval_seconds=float(os.getenv("TIM_ORCHESTRATOR_IDLE_SECONDS", "60")),
        max_helper_jobs=int(os.getenv("TIM_ORCHESTRATOR_MAX_HELPERS", "1")),
        helper_agents_enabled=os.getenv("TIM_ORCHESTRATOR_HELPERS_ENABLED", "false").lower() == "true",
        cpu_budget_percent=float(os.getenv("TIM_ORCHESTRATOR_CPU_BUDGET_PERCENT", "75")),
        memory_budget_percent=float(os.getenv("TIM_ORCHESTRATOR_MEMORY_BUDGET_PERCENT", "75")),
    )
    if args.command == "status":
        state_path = artifact_root / "state.json"
        print(state_path.read_text(encoding="utf-8") if state_path.exists() else json.dumps({"status": "NOT_STARTED", "phase": "MISSION_01_OPERATIONAL_RECOVERY"}, indent=2))
        return 0
    database_url = settings.database_url
    orchestrator = Orchestrator(config, ProductionHealthProvider(database_url, symbol=settings.symbol, root=ROOT), HeadlessJobs(root=ROOT, database_url=database_url, symbol=settings.symbol))
    try:
        if args.command == "run":
            with WorkerLock(artifact_root / "scheduler.lock"):
                while True:
                    state = orchestrator.tick()
                    print(json.dumps({"status": state.status, "phase": state.phase, "revision": state.revision, "blockers": state.blockers}, default=str), flush=True)
                    if state.status == "SAFE_STOP": return 2
                    next_at = datetime.fromisoformat(state.next_run_at) if state.next_run_at else datetime.now(timezone.utc)
                    time.sleep(max(0.25, min(300.0, (next_at - datetime.now(timezone.utc)).total_seconds())))
        state = orchestrator.tick()
    except SafeStop as exc:
        print(json.dumps({"status": "SAFE_STOP", "reason": str(exc)})); return 2
    print(json.dumps({"status": state.status, "phase": state.phase, "revision": state.revision, "blockers": state.blockers}, indent=2, default=str))
    return 0 if state.status != "SAFE_STOP" else 2


if __name__ == "__main__": raise SystemExit(main())
