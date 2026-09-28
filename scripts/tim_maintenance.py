from __future__ import annotations

"""Bounded self-maintenance for the TIM OBSERVE runtime.

This intentionally repairs only local, reversible operational conditions.  It
never backfills historical gaps while the live collector is running and it
never changes trading or security configuration.
"""

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.data_ingestion.durable import DurableIngestionStore
from src.database.connection import Database

STATE_PATH = ROOT / "data/operational/maintenance_last_run.json"
EXTERNAL_LOGS = (
    ROOT / "data/operational/runtime_launchd.log",
    ROOT / "data/operational/runtime_launchd.err.log",
    ROOT / "data/operational/validator_launchd.log",
    ROOT / "data/operational/validator_launchd.err.log",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def oversized_logs(max_bytes: int) -> list[Path]:
    return [path for path in EXTERNAL_LOGS if path.exists() and path.stat().st_size > max_bytes]


def local(command: list[str], *, timeout: float) -> dict[str, Any]:
    """Run a fixed local maintenance command and preserve bounded evidence."""
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "command": [Path(command[0]).name, *command[1:]],
            "returncode": result.returncode,
            "stdout": result.stdout[-4_000:],
            "stderr": result.stderr[-2_000:],
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": [Path(command[0]).name, *command[1:]], "returncode": None, "error": type(error).__name__}


async def release_expired_leases() -> int:
    database = Database(settings.database_url, min_size=1, max_size=2)
    try:
        await database.connect()
        return await DurableIngestionStore(database).release_expired_leases()
    finally:
        await database.close()


async def close_verified_recent_gaps(*, maximum: int = 25, maximum_trade_ids: int = 10_000) -> dict[str, int]:
    """Close only small current incidents whose raw range is already complete.

    This is a cheap verification pass, not a historical backfill.  It lets a
    previously persisted reconnect range become live-ready immediately while
    leaving old or large evidence gaps for governed offline work.
    """
    database = Database(settings.database_url, min_size=1, max_size=2)
    try:
        await database.connect()
        store = DurableIngestionStore(database)
        candidates = await store.open_gaps(settings.symbol.upper(), limit=maximum)
        eligible = [
            gap for gap in candidates
            if isinstance(gap.get("missing_from_id"), int)
            and isinstance(gap.get("missing_to_id"), int)
            and gap["missing_to_id"] - gap["missing_from_id"] + 1 <= maximum_trade_ids
        ]
        closed = 0
        for gap in eligible:
            if await store.resolve_gap(str(gap["gap_id"])):
                closed += 1
        return {"examined": len(eligible), "closed": closed, "deferred": len(candidates) - len(eligible)}
    finally:
        await database.close()


def write_report(report: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(STATE_PATH)


def rotate_external_logs(max_bytes: int) -> dict[str, Any]:
    candidates = oversized_logs(max_bytes)
    if not candidates:
        return {"status": "NOT_NEEDED", "oversized_logs": []}
    stopped = local([str(ROOT / "scripts/timctl"), "safe-stop"], timeout=90)
    if stopped.get("returncode") != 0:
        return {"status": "SAFE_STOP_FAILED", "oversized_logs": [str(path) for path in candidates], "safe_stop": stopped}
    rotation = local(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/tim_log_maintenance.py"), "--max-bytes", str(max_bytes), "--service-stopped"],
        timeout=60,
    )
    started = local([str(ROOT / "scripts/timctl"), "start"], timeout=90)
    return {
        "status": "ROTATED_AND_RESTARTED" if rotation.get("returncode") == 0 and started.get("returncode") == 0 else "RECOVERY_REQUIRES_ATTENTION",
        "oversized_logs": [str(path) for path in candidates],
        "safe_stop": stopped,
        "rotation": rotation,
        "start": started,
    }


async def run(
    max_bytes: int,
    *,
    max_verified_gaps: int = 25,
    max_verified_gap_trade_ids: int = 10_000,
    verified_gaps_only: bool = False,
) -> tuple[int, dict[str, Any]]:
    report: dict[str, Any] = {
        "timestamp": now(),
        "mode": "OBSERVE",
        "trading_actions": 0,
        "historical_gaps": "PRESERVED_FOR_OFFLINE_REVIEW",
        "security_findings": "PRESERVED_FOR_TARGETED_REVIEW",
    }
    try:
        report["expired_leases_released"] = await release_expired_leases()
    except Exception as error:
        report["lease_recovery_error"] = type(error).__name__
    try:
        report["verified_current_gaps"] = await close_verified_recent_gaps(
            maximum=max_verified_gaps,
            maximum_trade_ids=max_verified_gap_trade_ids,
        )
    except Exception as error:
        report["gap_verification_error"] = type(error).__name__
    if verified_gaps_only:
        report["status"] = "PASS" if "gap_verification_error" not in report else "ATTENTION_REQUIRED"
        report["maintenance_scope"] = "VERIFIED_GAP_MARKERS_ONLY"
        write_report(report)
        return (0 if report["status"] == "PASS" else 2), report
    # Cooperative logs are rotated without service interruption on every run.
    report["cooperative_log_rotation"] = local(
        [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/tim_log_maintenance.py"), "--max-bytes", str(max_bytes)], timeout=60
    )
    report["external_log_recovery"] = rotate_external_logs(max_bytes)
    failed = report["cooperative_log_rotation"].get("returncode") not in {0, 2}
    failed = failed or report["external_log_recovery"]["status"] in {"SAFE_STOP_FAILED", "RECOVERY_REQUIRES_ATTENTION"}
    report["status"] = "ATTENTION_REQUIRED" if failed else "PASS"
    write_report(report)
    return (2 if failed else 0), report


def main() -> int:
    parser = argparse.ArgumentParser(description="TIM bounded self-maintenance (OBSERVE-only)")
    parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--max-verified-gaps", type=int, default=25)
    parser.add_argument("--max-verified-gap-trade-ids", type=int, default=10_000)
    parser.add_argument("--verified-gaps-only", action="store_true")
    arguments = parser.parse_args()
    if arguments.max_bytes < 1024:
        parser.error("--max-bytes must be at least 1024")
    if arguments.max_verified_gaps < 1 or arguments.max_verified_gaps > 1_000:
        parser.error("--max-verified-gaps must be between 1 and 1000")
    if arguments.max_verified_gap_trade_ids < 1:
        parser.error("--max-verified-gap-trade-ids must be positive")
    code, report = asyncio.run(
        run(
            arguments.max_bytes,
            max_verified_gaps=arguments.max_verified_gaps,
            max_verified_gap_trade_ids=arguments.max_verified_gap_trade_ids,
            verified_gaps_only=arguments.verified_gaps_only,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
