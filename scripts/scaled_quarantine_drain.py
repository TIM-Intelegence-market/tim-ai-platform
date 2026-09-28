#!/usr/bin/env python3
"""Checkpointed, bounded controller for strict-order quarantine recovery."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import subprocess
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from scripts.recover_quarantined import validate_batch_runtime
from src.data_ingestion.recovery import TIMRecoveryContext


BATCH_STEPS = (100, 250, 500, 1000)
ACTIVE = ("PENDING", "PROCESSING", "RETRY", "QUARANTINED")


class RuntimeGuard:
    """Cheap liveness on every call, full launchd/process audit at a bounded cadence."""

    def __init__(self, full_check_every: int = 25) -> None:
        self.full_check_every = full_check_every
        self.calls = 0
        self.pid, self.runs = self._full_check()

    @staticmethod
    def _launchd_identity() -> tuple[int, int]:
        state = subprocess.run(
            ["/bin/launchctl", "print", f"gui/{os.getuid()}/com.tim.runtime"],
            check=True, capture_output=True, text=True,
        ).stdout
        pid = re.search(r"^\s*pid = (\d+)\s*$", state, re.MULTILINE)
        runs = re.search(r"^\s*runs = (\d+)\s*$", state, re.MULTILINE)
        if pid is None or runs is None:
            raise RuntimeError("TIM launchd identity is unavailable")
        return int(pid.group(1)), int(runs.group(1))

    def _full_check(self) -> tuple[int, int]:
        validate_batch_runtime()
        return self._launchd_identity()

    def __call__(self) -> None:
        self.calls += 1
        try:
            os.kill(self.pid, 0)
        except OSError as exc:
            raise RuntimeError("TIM runtime PID is no longer alive") from exc
        if self.calls % self.full_check_every == 0:
            current = self._full_check()
            if current != (self.pid, self.runs):
                raise RuntimeError("TIM launchd PID or restart count changed")


async def snapshot(context: TIMRecoveryContext) -> dict[str, Any]:
    started = time.perf_counter()
    async with context.database.acquire() as connection:
        rows = await connection.fetch(
            "SELECT status,count(*)::bigint AS count FROM ingestion_outbox GROUP BY status ORDER BY status"
        )
        counts = {status: 0 for status in (*ACTIVE, "COMPLETED")}
        counts.update({row["status"]: int(row["count"]) for row in rows})
        head = await connection.fetchrow(
            """SELECT outbox_id,aggregate_trade_id,status,attempts,max_attempts,last_error,created_at
               FROM ingestion_outbox WHERE worker_name='CANDLE_V1' AND status<>'COMPLETED'
               ORDER BY aggregate_trade_id,created_at,outbox_id LIMIT 1"""
        )
        cursor = await connection.fetchrow(
            """SELECT symbol,last_aggregate_trade_id,last_event_time,last_persisted_at,
                      recovery_state,cursor_hash FROM ingestion_cursors ORDER BY symbol LIMIT 1"""
        )
        gaps = int(await connection.fetchval(
            "SELECT count(*) FROM ingestion_gap_incidents WHERE status IN ('OPEN','CATCHING_UP')"
        ))
        last_completed_at = await connection.fetchval("SELECT max(completed_at) FROM ingestion_outbox")
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "status_counts": counts,
        "queue_depth": sum(counts[value] for value in ACTIVE),
        "head_of_line": dict(head) if head else None,
        "cursor": dict(cursor) if cursor else None,
        "open_gaps": gaps,
        "last_completed_at": last_completed_at,
        "db_read_seconds": time.perf_counter() - started,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def checkpoint(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_transition(before: dict[str, Any], after: dict[str, Any], completed: int) -> str | None:
    if after["status_counts"]["PROCESSING"] != 0:
        return "PROCESSING remained nonzero"
    if after["queue_depth"] != before["queue_depth"] - completed:
        return "queue delta does not equal completed records"
    if after["status_counts"]["COMPLETED"] != before["status_counts"]["COMPLETED"] + completed:
        return "COMPLETED delta mismatch"
    if after["status_counts"]["QUARANTINED"] != before["status_counts"]["QUARANTINED"] - completed:
        return "QUARANTINED delta mismatch"
    for status in ("PENDING", "RETRY"):
        if after["status_counts"][status] != before["status_counts"][status]:
            return f"unexpected {status} change"
    if after["open_gaps"] != before["open_gaps"]:
        return "open gap count changed"
    if after["cursor"] != before["cursor"]:
        return "cursor changed"
    return None


def next_batch_size(current: int, result: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> int:
    completed = int(result["completed"])
    duration = max(float(result.get("timing", {}).get("recovery_total_seconds", 0.0)), 1e-9)
    healthy = (
        result["status"] == "COMPLETED"
        and completed == int(result["selected"])
        and validate_transition(before, after, completed) is None
        and completed / duration >= 1.0
        and after["peak_rss_kib"] <= max(before["peak_rss_kib"] * 2, before["peak_rss_kib"] + 524_288)
    )
    if not healthy:
        return current
    index = BATCH_STEPS.index(current)
    return BATCH_STEPS[min(index + 1, len(BATCH_STEPS) - 1)]


async def drain(max_records: int, state_path: Path) -> dict[str, Any]:
    runtime_guard = RuntimeGuard()
    context = TIMRecoveryContext()
    context.runtime_guard = runtime_guard
    await context.connect()
    mission_started = time.perf_counter()
    state: dict[str, Any] = {
        "status": "RUNNING", "max_records": max_records, "completed": 0, "batches": []
    }
    try:
        baseline = await snapshot(context)
        state["baseline"] = baseline
        if baseline["status_counts"]["PROCESSING"] != 0:
            raise RuntimeError("PROCESSING must be zero before drain")
        batch_size = BATCH_STEPS[0]
        checkpoint(state_path, state)
        while state["completed"] < max_records:
            runtime_guard()
            before = await snapshot(context)
            remaining = max_records - int(state["completed"])
            requested = min(batch_size, remaining)
            result = await context.recover_batch(requested)
            after = await snapshot(context)
            completed = int(result.get("completed", 0))
            stop = validate_transition(before, after, completed)
            batch = {
                "index": len(state["batches"]) + 1,
                "requested": requested,
                "result_status": result.get("status"),
                "completed": completed,
                "before": before,
                "after": after,
                "timing": result.get("timing", {}),
                "batch_hash": canonical_hash(result.get("records", [])),
                "safety_stop": stop or result.get("safety_stop"),
            }
            state["batches"].append(batch)
            state["completed"] = int(state["completed"]) + completed
            state["last"] = after
            checkpoint(state_path, state)
            if batch["safety_stop"] or result.get("status") != "COMPLETED" or completed != int(result.get("selected", 0)):
                state["status"] = "STOPPED"
                break
            batch_size = next_batch_size(batch_size, result, before, after)
        else:
            state["status"] = "COMPLETED"
        state["duration_seconds"] = time.perf_counter() - mission_started
        state["records_per_second"] = int(state["completed"]) / max(float(state["duration_seconds"]), 1e-9)
        checkpoint(state_path, state)
        return state
    finally:
        await context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-records", type=int, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        parser.error("--execute is required")
    if not 1 <= args.max_records <= 1_000_000:
        parser.error("--max-records must be between 1 and 1000000")
    result = asyncio.run(drain(args.max_records, args.state))
    print(json.dumps({key: result[key] for key in ("status", "completed", "duration_seconds", "records_per_second")}, sort_keys=True))
    return 0 if result["status"] == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
