from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.operational.logging import LogRotator, RotationPolicy


COOPERATIVE_LOGS = (
    "data/operational/events.jsonl",
    "data/operational/watchdog.jsonl",
    "data/operational/queue.jsonl",
    "data/operational/gap_incidents.jsonl",
)
EXTERNAL_LOGS = (
    "data/operational/runtime_launchd.log",
    "data/operational/runtime_launchd.err.log",
    "data/operational/validator_launchd.log",
    "data/operational/validator_launchd.err.log",
)

# stdout/stderr of short interval jobs (com.tim.server-health runs a few seconds every 60 s).
# No process keeps them open between runs, so they are rotated in place without a safe stop;
# preserve_inode keeps the file launchd opens. A line written during the copy can be lost,
# which is acceptable: server_health.json holds the current status.
SHORT_JOB_LOGS = (
    "data/operational/server_health_launchd.log",
    "data/operational/server_health_launchd.err.log",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="TIM bounded log retention (OBSERVE-only)")
    parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--backups", type=int, default=7)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--no-compress", action="store_true")
    parser.add_argument(
        "--service-stopped",
        action="store_true",
        help="permit rotation of launchd stdout/stderr after the owning service stopped",
    )
    arguments = parser.parse_args()
    policy = RotationPolicy(
        max_bytes=arguments.max_bytes,
        backup_count=arguments.backups,
        retention_days=arguments.retention_days,
        compress=not arguments.no_compress,
    )
    reports = []
    for relative in COOPERATIVE_LOGS:
        reports.append(LogRotator(ROOT / relative, policy).rotate_if_needed())
    for relative in SHORT_JOB_LOGS:
        reports.append(LogRotator(ROOT / relative, policy, preserve_inode=True).rotate_if_needed())
    for relative in EXTERNAL_LOGS:
        path = ROOT / relative
        if not arguments.service_stopped and path.exists() and path.stat().st_size > policy.max_bytes:
            reports.append(
                {
                    "path": str(path),
                    "rotated": None,
                    "status": "DEFERRED_UNTIL_SAFE_STOP",
                    "reason": "launchd stdout/stderr writer does not participate in the rotation lock",
                }
            )
        else:
            # launchd opens these paths before exec(). Keep the active inode so
            # macOS access metadata (notably com.apple.macl in protected user
            # folders) survives a safe-stop rotation.
            reports.append(LogRotator(path, policy, preserve_inode=True).rotate_if_needed())
    blocked = any(report.get("status") == "DEFERRED_UNTIL_SAFE_STOP" for report in reports)
    print(
        json.dumps(
            {
                "status": "BLOCKED_SAFE_STOP_REQUIRED" if blocked else "PASS",
                "mode": "OBSERVE",
                "trading_actions": 0,
                "logs": reports,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
