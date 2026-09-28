#!/usr/bin/env python3
"""Permanently fail a running coverage campaign if sealed code changes."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.verify_coverage_implementation import verify


def atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def guard(manifest: Path, status: Path) -> dict:
    result = verify(manifest)
    if result["status"] == "PASS":
        return result
    existing = json.loads(status.read_text(encoding="utf-8")) if status.exists() else {}
    if existing.get("state") != "FAILED_PERMANENT":
        existing.update(
            {
                "state": "FAILED_PERMANENT",
                "integrity_failure_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "integrity_failure": result,
                "trading_actions": 0,
            }
        )
        atomic_write(status, existing)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "artifacts/continuous_coverage/implementation_20260923T0951Z.json",
    )
    parser.add_argument(
        "--status",
        type=Path,
        default=ROOT / "artifacts/continuous_coverage/status_20260923T0951Z.json",
    )
    args = parser.parse_args()
    result = guard(args.manifest, args.status)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
