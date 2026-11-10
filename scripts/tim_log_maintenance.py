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
# stdout/stderr of the long-running launchd services. launchd opens these paths with
# O_APPEND before exec() (lsof shows R,W,AP on the runtime's fd 1 and 2), so after a
# copy-and-truncate the writer continues at the new end of the same inode: no sparse
# file, no handle to reopen. A line written during the copy can be lost, which is
# acceptable: events.jsonl and watchdog.jsonl hold the durable record. Deferring these
# until a safe stop (the rule until 2026-11-09) never rotated them in production, because
# the runtime does not stop on its own; runtime_launchd.err.log grew to 14 MB.
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
    # this job's own report output (one JSON report per run, ~3 KB every 15 min)
    "data/operational/log_maintenance_launchd.log",
    "data/operational/log_maintenance_launchd.err.log",
)


# Mac only: ~/Library/Logs/TIM holds stdout/stderr of further LaunchAgents (Qwen worker,
# Ollama, KI filter, maintenance, ...). launchd opens them with O_APPEND, so they rotate in
# place like EXTERNAL_LOGS. Only top-level *.log files; archives (*.gz) are left alone.
# local-first.out.log (Qwen worker) had grown to 36 MB by 2026-11-10 without any rotation.
DEFAULT_USER_LOG_DIR = Path.home() / "Library/Logs/TIM"


def user_logs(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.log") if path.is_file() and not path.is_symlink())


def main() -> int:
    parser = argparse.ArgumentParser(description="TIM bounded log retention (OBSERVE-only)")
    parser.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--backups", type=int, default=7)
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--no-compress", action="store_true")
    parser.add_argument(
        "--service-stopped",
        action="store_true",
        help="accepted for compatibility (tim_maintenance.py); launchd logs rotate in place either way",
    )
    parser.add_argument(
        "--user-log-dir",
        type=Path,
        default=DEFAULT_USER_LOG_DIR,
        help="directory of further launchd logs rotated in place (skipped when missing)",
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
        # Keep the active inode: launchd's O_APPEND handle keeps writing to it, and
        # macOS access metadata (com.apple.macl in protected user folders) survives.
        reports.append(LogRotator(ROOT / relative, policy, preserve_inode=True).rotate_if_needed())
    for path in user_logs(arguments.user_log_dir):
        try:
            reports.append(LogRotator(path, policy, preserve_inode=True).rotate_if_needed())
        except OSError as error:  # e.g. a root-owned file; must not stop the other logs
            reports.append({"path": str(path), "rotated": False, "error": type(error).__name__})
    print(
        json.dumps(
            {
                "status": "PASS",
                "mode": "OBSERVE",
                "trading_actions": 0,
                "logs": reports,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
