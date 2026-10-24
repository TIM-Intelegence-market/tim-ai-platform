#!/usr/bin/env python3
"""Read-only health and gap check for the host running TIM: Debian server or Mac mini (OBSERVE only).

Each check is GREEN, AMBER or RED; the overall status is the worst of them. The
report goes to stdout (journal) and data/operational/server_health.json. Exit code
0 means no RED check, 2 means at least one RED check.

Alerts (Telegram, mail) are not sent from here until a channel is approved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc
REPORT_PATH = ROOT / "data/operational/server_health.json"
ORDER = {"GREEN": 0, "AMBER": 1, "RED": 2}

# Thresholds from the step 1 task package (P6).
CANDLE_MAX_AGE_SECONDS = 180
GAP_WINDOW_MINUTES = 60
# The newest minutes may still be closing or finalizing; they are not counted as gaps yet.
GAP_SETTLE_MINUTES = 2
DISK_AMBER_PERCENT = 85.0
DISK_RED_PERCENT = 95.0
BACKUP_MAX_AGE_HOURS = 26.0


def check(status: str, **details: Any) -> dict[str, Any]:
    return {"status": status, **details}


def runtime_check(systemctl_output: str | None) -> dict[str, Any]:
    if systemctl_output is None:
        return check("RED", reason="systemctl unavailable")
    fields = dict(line.split("=", 1) for line in systemctl_output.splitlines() if "=" in line)
    active, sub = fields.get("ActiveState"), fields.get("SubState")
    if active == "active" and sub == "running":
        return check("GREEN", active=active, sub=sub)
    if active in {"activating", "reloading"}:
        return check("AMBER", active=active, sub=sub)
    return check("RED", active=active, sub=sub)


def candle_freshness_check(newest_open_time: datetime | None, now: datetime) -> dict[str, Any]:
    if newest_open_time is None:
        return check("RED", reason="no closed 1m candle")
    # A 1m candle closes 60 s after it opens.
    age = (now - newest_open_time).total_seconds() - 60
    status = "GREEN" if age <= CANDLE_MAX_AGE_SECONDS else "RED"
    return check(status, newest_open_time=newest_open_time.isoformat(), age_seconds=round(age, 1),
                 max_age_seconds=CANDLE_MAX_AGE_SECONDS)


def gap_window(now: datetime) -> tuple[datetime, datetime]:
    end = now.astimezone(UTC).replace(second=0, microsecond=0) - timedelta(minutes=GAP_SETTLE_MINUTES)
    return end - timedelta(minutes=GAP_WINDOW_MINUTES), end


def gap_check(present: set[datetime], start: datetime, end: datetime) -> dict[str, Any]:
    expected = []
    cursor = start
    while cursor < end:
        expected.append(cursor)
        cursor += timedelta(minutes=1)
    missing = [minute for minute in expected if minute not in present]
    status = "GREEN" if not missing else "RED"
    return check(status, window_start=start.isoformat(), window_end=end.isoformat(), expected=len(expected),
                 missing=len(missing), first_missing=[minute.isoformat() for minute in missing[:10]])


def disk_check(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return check("RED", path=str(path), reason="disk usage unavailable")
    used = 100.0 * usage.used / usage.total if usage.total else 100.0
    status = "RED" if used >= DISK_RED_PERCENT else "AMBER" if used >= DISK_AMBER_PERCENT else "GREEN"
    return check(status, path=str(path), used_percent=round(used, 1), free_bytes=usage.free)


def time_sync_check(timedatectl_output: str | None) -> dict[str, Any]:
    if timedatectl_output is None:
        return check("RED", reason="timedatectl unavailable")
    synced = timedatectl_output.strip().lower() == "yes"
    return check("GREEN" if synced else "RED", ntp_synchronized=synced)


def backup_check(directory: Path, now: datetime) -> dict[str, Any]:
    from scripts.tim_db_backup import dump_time, dumps

    try:
        existing = dumps(directory)
    except OSError as exc:
        return check("RED", directory=str(directory), reason=f"backup directory unreadable ({type(exc).__name__})")
    if not existing:
        return check("RED", directory=str(directory), reason="no backup yet")
    newest = existing[-1]
    age_hours = (now - dump_time(newest)).total_seconds() / 3600
    status = "GREEN" if age_hours <= BACKUP_MAX_AGE_HOURS else "RED"
    return check(status, newest=newest.name, age_hours=round(age_hours, 2), max_age_hours=BACKUP_MAX_AGE_HOURS)


def overall(checks: dict[str, dict[str, Any]]) -> str:
    return max((entry["status"] for entry in checks.values()), key=ORDER.__getitem__, default="RED")


def command_output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


async def candle_facts(database_url: str, symbol: str, start: datetime, end: datetime) -> tuple[datetime | None, set[datetime]]:
    import asyncpg

    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=30)
    try:
        newest = await connection.fetchval(
            "SELECT max(open_time) FROM candles WHERE symbol=$1 AND timeframe='1m' AND closed=true", symbol
        )
        rows = await connection.fetch(
            """SELECT DISTINCT open_time FROM candles
               WHERE symbol=$1 AND timeframe='1m' AND closed=true AND open_time >= $2 AND open_time < $3""",
            symbol, start, end,
        )
    finally:
        await connection.close()
    return newest, {row["open_time"].astimezone(UTC) for row in rows}


def launchd_runtime_output() -> str | None:
    """macOS: launchd state of com.tim.runtime in the systemctl-show shape runtime_check reads."""
    import os

    output = command_output(["/bin/launchctl", "print", f"gui/{os.getuid()}/com.tim.runtime"])
    if output is None:
        return "ActiveState=inactive\nSubState=dead\n"
    running = any(line.strip() == "state = running" for line in output.splitlines())
    return "ActiveState=active\nSubState=running\n" if running else "ActiveState=inactive\nSubState=dead\n"


def collect(backup_dir: Path, disk_path: Path) -> dict[str, Any]:
    now = datetime.now(UTC)
    start, end = gap_window(now)
    darwin = sys.platform == "darwin"
    checks: dict[str, dict[str, Any]] = {
        "runtime": runtime_check(launchd_runtime_output() if darwin else command_output(
            ["systemctl", "show", "tim-runtime.service", "--property=ActiveState,SubState"])),
    }
    try:
        from config.settings import settings

        newest, present = asyncio.run(candle_facts(settings.database_url, settings.symbol, start, end))
        checks["candle_freshness"] = candle_freshness_check(newest, now)
        checks["gap_last_60m"] = gap_check(present, start, end)
    except Exception as exc:  # the database itself being unreachable is a RED finding
        reason = f"database unavailable ({type(exc).__name__})"
        checks["candle_freshness"] = check("RED", reason=reason)
        checks["gap_last_60m"] = check("RED", reason=reason)
    checks["disk"] = disk_check(disk_path)
    if darwin:
        # macOS keeps time via timed; its sync state is not readable without admin rights.
        checks["time_sync"] = check("AMBER", reason="time sync not measurable on macOS without admin rights")
    else:
        checks["time_sync"] = time_sync_check(
            command_output(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]))
    checks["backup"] = backup_check(backup_dir, now)
    return {"timestamp": now.isoformat(), "status": overall(checks), "checks": checks,
            "mode": "OBSERVE", "trading_actions": 0}


def default_backup_dir() -> Path:
    """Where tim_db_backup.py writes on this host.

    The Mac mini's com.tim.db-backup agent writes to the user's Application
    Support folder; /var/backups/tim only exists on the Linux server. Checking
    the Linux path on the Mac made every report RED ("backup directory unreadable").
    The rule lives in tim_db_backup so backup and health always pick the same folder.
    """
    from scripts.tim_db_backup import default_backup_directory

    return default_backup_directory()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TIM server health and gap check (read-only)")
    parser.add_argument("--backup-dir", type=Path, default=default_backup_dir())
    parser.add_argument("--disk-path", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    report = collect(args.backup_dir, args.disk_path)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(REPORT_PATH)
    print(json.dumps(report, sort_keys=True))
    return 2 if report["status"] == "RED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
