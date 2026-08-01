#!/usr/bin/env python3
"""Write the locked prospective qualification pre-registration and status."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.qualification import (
    REQUIRED_START_GATES,
    StartGate,
    build_preregistration,
)


def sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "artifacts/v2_completion/baseline_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/v2_completion/qualification_preregistration.json",
    )
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    current = baseline["scientific_case_audit"]["current_cutoff_audit"]
    coverage = baseline["coverage"]["product_calculation"]
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    statuses = {
        "postgresql_security": ("FAIL", "artifacts/v2_completion/postgres_listener_before.json"),
        "safe_stop": ("PENDING", "artifacts/v2_completion/safe_stop_test.json"),
        "durable_ingestion": ("PENDING", "final runtime acceptance not yet complete"),
        "durable_cursor": ("PENDING", "artifacts/v2_completion/durable_cursor_state.json"),
        "durable_outbox": ("PENDING", "artifacts/v2_completion/queue_metrics.json"),
        "watchdog": ("PENDING", "artifacts/v2_completion/watchdog_status.json"),
        "log_rotation": ("PENDING", "final log-retention acceptance not yet complete"),
        "observe_only": ("PASS", "artifacts/v2_completion/baseline_manifest.json"),
        "full_suite": ("PENDING", "artifacts/v2_completion/final_test_summary.json"),
        "configuration_and_commit_frozen": ("PENDING", f"candidate implementation commit {head}"),
    }
    gates = [StartGate(name, *statuses[name]) for name in REQUIRED_START_GATES]
    payload = build_preregistration(
        gates=gates,
        software_commit=head,
        configuration_hash=sha256(ROOT / "config/core_manifest.json"),
        current_independent_cases=int(current["strict_independent_30m_windows"]),
        observed_minutes=int(coverage["expected_observations"]),
    )
    atomic_json(args.output, payload)
    daily_dir = args.output.parent / "qualification_daily_manifests"
    daily_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps({
        "output": str(args.output),
        "campaign_status": payload["campaign_status"],
        "blocking_start_gates": payload["blocking_start_gates"],
        "minimum_days": payload["duration"]["pre_registered_minimum_days"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
