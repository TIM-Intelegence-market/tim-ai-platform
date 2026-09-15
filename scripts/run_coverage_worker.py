#!/usr/bin/env python3
"""Run one safe, offline-only historical coverage check/backfill slice.

This worker never opens TIM's live outbox, never writes the live cursor, and
never enables an LLM.  It only reconstructs immutable V2 candidate files from
the approved gap ledger when their recorded coverage is incomplete.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "artifacts/v2_readiness/data_gap_ledger.jsonl"
MANIFEST = ROOT / "artifacts/v2_completion/backfill_candidate_manifest.json"
RECEIPT = ROOT / "artifacts/operations/coverage_worker/latest.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_receipt(value: dict[str, object]) -> None:
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    temporary = RECEIPT.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, RECEIPT)


def main() -> int:
    receipt: dict[str, object] = {
        "worker": "TIM_OFFLINE_COVERAGE_V1",
        "started_at_utc": utc_now(),
        "mode": "OFFLINE_ONLY",
        "live_outbox_mutations": 0,
        "live_cursor_mutations": 0,
        "llm_calls": 0,
        "trading_actions": 0,
    }
    if not LEDGER.exists():
        receipt.update({"status": "REFUSED", "reason": "gap ledger is missing"})
        write_receipt(receipt)
        return 2

    ledger_hash = digest(LEDGER)
    receipt["gap_ledger_sha256"] = ledger_hash
    manifest: dict[str, object] = {}
    if MANIFEST.exists():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    gap_minutes = int(manifest.get("gap_minutes", -1)) if manifest else -1
    candidate_minutes = int(manifest.get("candidate_minutes", -1)) if manifest else -1
    remaining_minutes = int(manifest.get("remaining_gap_minutes", -1)) if manifest else -1
    candidate_complete = (
        gap_minutes >= 0
        and candidate_minutes == gap_minutes
        and remaining_minutes == 0
        and manifest.get("readiness_counted") is False
    )
    receipt["coverage_before"] = {
        "gap_minutes": gap_minutes,
        "candidate_minutes": candidate_minutes,
        "remaining_gap_minutes": remaining_minutes,
        "manifest_hash": manifest.get("manifest_hash"),
    }
    if candidate_complete:
        receipt.update({
            "status": "NO_OFFLINE_COVERAGE_WORK",
            "reason": "immutable candidate already covers every approved ledger minute",
            "completed_at_utc": utc_now(),
        })
        write_receipt(receipt)
        return 0

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/v2_backfill_candidate.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=3600,
        check=False,
    )
    receipt.update({
        "backfill_exit_code": result.returncode,
        "backfill_stdout": result.stdout.strip()[-4000:],
        "backfill_stderr": result.stderr.strip()[-4000:],
        "completed_at_utc": utc_now(),
    })
    receipt["status"] = "BACKFILL_COMPLETED" if result.returncode == 0 else "BACKFILL_FAILED"
    write_receipt(receipt)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
