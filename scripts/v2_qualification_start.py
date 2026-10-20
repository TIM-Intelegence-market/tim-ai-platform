#!/usr/bin/env python3
"""Start the prospective V2 qualification campaign (explicit, human-approved action).

Run on the server as user ``tim`` right after ``scripts/v2_start_gates_check.py``. Refuses
unless the start-gate report is fresh, all gates PASS, and the report, the frozen commit
and the clean server checkout all name the same commit. Writes one immutable campaign
file under data/qualification/ (outside git, so the checkout stays clean). Never trades.

Example:
  scripts/v2_qualification_start.py --start-gates /tmp/start_gates.json \
      --approved-by Uzi --decision-ref <card-id> --approved-at 2026-10-20T12:59:10Z
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.campaign import campaign_start_minute, gates_from_report
from src.v2_completion.qualification import (
    activate_campaign,
    build_preregistration,
    write_immutable_json,
)

DEFAULT_DIR = ROOT / "data/qualification"


def git(*args: str) -> str:
    return subprocess.run(["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-gates", type=Path, required=True)
    parser.add_argument("--approved-by", required=True)
    parser.add_argument("--decision-ref", required=True)
    parser.add_argument("--approved-at", required=True, help="UTC time of the human approval, trailing Z")
    parser.add_argument("--baseline", type=Path, default=ROOT / "artifacts/v2_completion/baseline_manifest.json")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args(argv)
    if not args.approved_by.strip() or not args.decision_ref.strip() or not args.approved_at.endswith("Z"):
        parser.error("approval needs a name, a decision reference and a UTC time ending in Z")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    campaign_file = args.output_dir / "qualification_campaign.json"
    if campaign_file.exists():
        print(json.dumps({"status": "ALREADY_ACTIVE", "campaign": str(campaign_file)}))
        return 3
    now = datetime.now(UTC)
    head = git("rev-parse", "HEAD")
    if git("status", "--porcelain"):
        raise SystemExit("server checkout has local changes; refusing to start")
    report_bytes = args.start_gates.read_bytes()
    report = json.loads(report_bytes)
    gates = gates_from_report(report, report_ref="data/qualification/start_gates.json", head=head, now=now)
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    prereg = build_preregistration(
        gates=gates,
        software_commit=head,
        configuration_hash=hashlib.sha256((ROOT / "config/core_manifest.json").read_bytes()).hexdigest(),
        current_independent_cases=int(
            baseline["scientific_case_audit"]["current_cutoff_audit"]["strict_independent_30m_windows"]),
        observed_minutes=int(baseline["coverage"]["product_calculation"]["expected_observations"]),
        generated_at=now,
    )
    prereg["start_approval"] = {"approved_by": args.approved_by.strip(), "decision_ref": args.decision_ref.strip(),
                                "approved_at_utc": args.approved_at,
                                "scope": "START_PROSPECTIVE_OBSERVATION_WINDOW_ONLY_NOT_V2_OR_TRADING_APPROVAL"}
    prereg["start_gate_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    campaign = activate_campaign(prereg, start=campaign_start_minute(now), actual_commit=head)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    copy = args.output_dir / "start_gates.json"
    if args.start_gates.resolve() != copy.resolve():
        shutil.copyfile(args.start_gates, copy)
    status = write_immutable_json(campaign_file, campaign)
    print(json.dumps({"status": status, "campaign": str(campaign_file), "start_utc": campaign["start_utc"],
                      "expected_end_utc": campaign["expected_end_utc"],
                      "minimum_days": campaign["duration"]["pre_registered_minimum_days"],
                      "software_commit": head, "preregistration_hash": campaign["preregistration_hash"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
