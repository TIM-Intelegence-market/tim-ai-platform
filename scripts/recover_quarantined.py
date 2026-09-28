#!/usr/bin/env python3
"""Explicitly replay one ID or a bounded strict-order quarantine prefix."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_ingestion.recovery import TIMRecoveryContext


def validate_batch_runtime() -> None:
    """Fail closed unless the macOS production runtime remains recovery-safe."""
    if os.getenv("TIM_RUNTIME_ENV", "").lower() == "test":
        return
    if sys.platform != "darwin":
        raise RuntimeError("batch recovery requires the launchd runtime guard")
    label = f"gui/{os.getuid()}/com.tim.runtime"
    state = subprocess.run(
        ["/bin/launchctl", "print", label],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if not re.search(r"^\s*active count = 1\s*$", state, re.MULTILINE):
        raise RuntimeError("TIM launchd active count is not exactly one")
    if not re.search(r"^\s*state = running\s*$", state, re.MULTILINE):
        raise RuntimeError("TIM launchd process is not running")
    if "TIM_BINANCE_WS_URL => ws://127.0.0.1:1" not in state:
        raise RuntimeError("live ingestion is not pinned to the blocked endpoint")
    processes = subprocess.run(
        ["/bin/ps", "-axo", "pid=,comm=,args="],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    maintenance_names = ("recover_quarantined.py", "scaled_quarantine_drain.py", "drain_queue.py", "backfill_gaps.py")
    for line in processes.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) < 3 or int(fields[0]) == os.getpid():
            continue
        if "python" in Path(fields[1]).name.lower() and any(name in fields[2] for name in maintenance_names):
            raise RuntimeError(f"parallel maintenance process detected: pid={fields[0]}")


async def run(
    outbox_id: str | None = None,
    *,
    batch_limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    context = TIMRecoveryContext()
    if batch_limit is not None:
        context.runtime_guard = validate_batch_runtime
    await context.connect()
    try:
        if batch_limit is not None:
            return (
                await context.inspect_batch(batch_limit)
                if dry_run
                else await context.recover_batch(batch_limit)
            )
        assert outbox_id is not None
        return await context.inspect(outbox_id) if dry_run else await context.recover(outbox_id)
    finally:
        await context.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay an explicit bounded QUARANTINED selection")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--outbox-id")
    target.add_argument("--batch-limit", type=int, choices=range(1, 1001))
    parser.add_argument("--dry-run", action="store_true", help="inspect the exact ID without writes")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.batch_limit is None:
        result = asyncio.run(run(arguments.outbox_id, dry_run=arguments.dry_run))
    else:
        result = asyncio.run(run(batch_limit=arguments.batch_limit, dry_run=arguments.dry_run))
    print(json.dumps(result, indent=2, sort_keys=True))
    accepted = (
        {"RECOVERABLE", "PREVIEW"}
        if arguments.dry_run
        else {"COMPLETED", "NOT_QUARANTINED"}
    )
    return 0 if result["status"] in accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
