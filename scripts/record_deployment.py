"""Record which commit runs in this checkout and its CI test result.

Run once after moving ~/TIM-live to a new commit. The Control Center shows the
CI full-suite run of the deployed commit as the current test evidence instead
of an old summary file. Values come from the GitHub check run of the commit
(job "test"); nothing here contacts GitHub or the database.

    python scripts/record_deployment.py --ci-conclusion success \
        --ci-completed-at 2026-10-22T21:40:00Z --ci-url https://github.com/... \
        --passed 6512 --failed 0 --skipped 41
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data/operational/deployment.json"


def head_commit() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()


def _time(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SystemExit("--ci-completed-at needs a timezone, e.g. 2026-10-22T21:40:00Z")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build(args: argparse.Namespace) -> dict:
    record = {
        "commit": args.commit or head_commit(),
        "deployed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ci_test": {
            "conclusion": args.ci_conclusion,
            "completed_at_utc": _time(args.ci_completed_at),
            "url": args.ci_url,
        },
    }
    for key in ("passed", "failed", "skipped"):
        value = getattr(args, key)
        if value is not None:
            record["ci_test"][key] = value
    return record


def write(record: dict, target: Path = TARGET) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commit", help="defaults to git HEAD of this checkout")
    parser.add_argument("--ci-conclusion", required=True, choices=("success", "failure", "cancelled", "timed_out"))
    parser.add_argument("--ci-completed-at", required=True)
    parser.add_argument("--ci-url", default="")
    parser.add_argument("--passed", type=int)
    parser.add_argument("--failed", type=int)
    parser.add_argument("--skipped", type=int)
    record = build(parser.parse_args())
    write(record)
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
