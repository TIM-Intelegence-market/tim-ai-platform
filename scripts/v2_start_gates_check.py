#!/usr/bin/env python3
"""Evaluate the V2 qualification start gates from live, read-only evidence on the TIM host.

On the Debian server run as user ``tim`` with the runtime EnvironmentFile (systemd). On the
Mac mini run from the live checkout as the login user (launchd, see ops/macos/LIVE_MAC.md).
Reads runtime and timer status files, PostgreSQL state, service-manager state and git
state. Writes nothing but the report. Never starts the campaign.

Example:
  scripts/v2_start_gates_check.py --frozen-commit <sha> --suite-commit <sha> \
      --suite-run https://github.com/.../actions/runs/<id> --output /tmp/start-gates.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.mac_live import (
    interface_addresses,
    launchctl_state,
    launchd_drift,
    log_rotation_evidence,
    reachable,
)
from src.v2_completion.start_gate_checks import (
    check_durable_cursor,
    check_durable_ingestion,
    check_durable_outbox,
    check_frozen,
    check_full_suite,
    check_log_rotation,
    check_log_rotation_in_process,
    check_observe_only,
    check_postgresql_reachability,
    check_postgresql_security,
    check_safe_stop,
    check_watchdog,
    read_json,
    summarize,
)

OPERATIONAL = ROOT / "data/operational"
RUNTIME = ROOT / "data/runtime"
LOGROTATE_STATUS = Path("/var/lib/logrotate/status")
SYSTEMD_DIR = Path("/etc/systemd/system")
DARWIN = sys.platform == "darwin"


def run(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def git(*args: str) -> str | None:
    output = run(["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args])
    return None if output is None else output.strip()


def unit_drift() -> list[str] | None:
    try:
        drift = []
        for repo_unit in sorted((ROOT / "ops/systemd").glob("tim-*.*")):
            installed = SYSTEMD_DIR / repo_unit.name
            if installed.exists() and installed.read_bytes() != repo_unit.read_bytes():
                drift.append(repo_unit.name)
        return drift
    except OSError:
        return None


def database_port() -> int:
    from config.settings import settings

    return settings.database_port


def postgresql_security_gate(listen_addresses: str | None):
    """Platform-specific PostgreSQL exposure gate, shared with the daily manifest job."""
    port = database_port()
    if not DARWIN:
        return check_postgresql_security(run(["ss", "-ltnH"]), listen_addresses, port=port)
    ifconfig = run(["/sbin/ifconfig"])
    probes = None if ifconfig is None else {host: reachable(host, port) for host in interface_addresses(ifconfig)}
    return check_postgresql_reachability(listen_addresses, probes, port=port)


def service_active(name: str) -> str | None:
    if DARWIN:
        return launchctl_state(run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{name}"]))
    return (run(["systemctl", "is-active", name]) or "").strip() or None


def log_rotation_gate(now: datetime):
    if DARWIN:
        try:
            archives, oversized = log_rotation_evidence(OPERATIONAL)
        except OSError:
            archives, oversized = {}, []
        return check_log_rotation_in_process(archives, oversized, now)
    try:
        last_rotate = datetime.fromtimestamp(LOGROTATE_STATUS.stat().st_mtime, UTC)
    except OSError:
        last_rotate = None
    return check_log_rotation(service_active("logrotate.timer"), last_rotate,
                              sorted(path.name for path in OPERATIONAL.glob("*.gz")), now)


def service_drift() -> list[str] | None:
    if DARWIN:
        return launchd_drift(ROOT, Path.home() / "Library/LaunchAgents", Path.home())
    return unit_drift()


async def database_evidence(symbol: str) -> dict[str, Any]:
    from config.settings import settings
    from src.database.connection import Database

    database = Database(settings.database_url, min_size=1, max_size=1)
    await database.connect()
    try:
        async with database.acquire() as connection:
            async with connection.transaction(readonly=True, isolation="repeatable_read"):
                listen = await connection.fetchval("SHOW listen_addresses")
                cursor = await connection.fetchrow(
                    """SELECT cursor_version,cursor_hash,recovery_state,last_persisted_at
                       FROM ingestion_cursors WHERE symbol=$1 AND data_type='AGG_TRADE'""", symbol)
                outbox = await connection.fetch("SELECT status,count(*) AS n FROM ingestion_outbox GROUP BY status")
                gaps = await connection.fetchval(
                    "SELECT count(*) FROM ingestion_gap_incidents WHERE status IN ('OPEN','CATCHING_UP')")
        return {"listen_addresses": listen, "cursor": dict(cursor) if cursor else None,
                "outbox": {row["status"]: int(row["n"]) for row in outbox}, "open_gaps": int(gaps)}
    finally:
        await database.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--frozen-commit", default="")
    parser.add_argument("--suite-commit", default="")
    parser.add_argument("--suite-run", default="")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    now = datetime.now(UTC)
    try:
        db = asyncio.run(database_evidence(args.symbol.upper()))
        db_error = None
    except Exception as error:  # noqa: BLE001 - evidence collection must report, not crash
        db, db_error = {}, type(error).__name__
    liveness = read_json(OPERATIONAL / "rolling_liveness.json")
    head = git("rev-parse", "HEAD")
    porcelain = git("status", "--porcelain")
    results = [
        postgresql_security_gate(db.get("listen_addresses")),
        check_safe_stop(read_json(RUNTIME / "last_safe_stop.json"), read_json(RUNTIME / "last_safe_start.json"), now),
        check_durable_ingestion(db.get("open_gaps"), liveness, now),
        check_durable_cursor(db.get("cursor"), now),
        check_durable_outbox(db.get("outbox")),
        check_watchdog(read_json(OPERATIONAL / "watchdog_status.json"),
                       service_active("com.tim.watchdog" if DARWIN else "tim-watchdog.service"), now),
        log_rotation_gate(now),
        check_observe_only(read_json(OPERATIONAL / "server_health.json"), liveness),
        check_full_suite(head, args.suite_commit or None, args.suite_run or None),
        check_frozen(head, None if porcelain is None else porcelain.splitlines(),
                     args.frozen_commit or None, service_drift()),
    ]
    report = summarize(results, now=now, context={"head": head, "database_error": db_error, "symbol": args.symbol,
                                                  "host_platform": "macos-launchd" if DARWIN else "linux-systemd"})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"output": str(args.output), "all_start_gates_pass": report["all_start_gates_pass"],
                      "gates": {gate["name"]: gate["status"] for gate in report["gates"]},
                      "reasons": {gate["name"]: gate["reasons"] for gate in report["gates"] if gate["reasons"]}},
                     indent=2))
    return 0 if report["all_start_gates_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
