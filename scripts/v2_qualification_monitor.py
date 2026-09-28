#!/usr/bin/env python3
"""One-shot, scheduler-safe qualification campaign monitor."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.qualification import build_daily_manifest, write_immutable_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT / "artifacts/v2_completion/qualification_preregistration.json",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        help="Hash-bound one-day metrics JSON; required only after campaign activation",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts/v2_completion/qualification_daily_manifests",
    )
    args = parser.parse_args()
    prereg = json.loads(args.preregistration.read_text(encoding="utf-8"))
    if prereg.get("campaign_status") != "ACTIVE":
        print(json.dumps({
            "status": prereg.get("campaign_status"),
            "manifests_written": 0,
            "reason": "qualification start gate has not passed",
        }, sort_keys=True))
        return 2
    if args.metrics is None:
        parser.error("--metrics is required for an active campaign")
    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    payload = build_daily_manifest(prereg, day=now, metrics=metrics)
    output = args.output_dir / f"{now.date().isoformat()}.json"
    status = write_immutable_json(output, payload)
    print(json.dumps({"status": status, "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
