from __future__ import annotations

import asyncio
import json
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.database.connection import Database


@dataclass(frozen=True, slots=True)
class WatchdogThresholds:
    collector_freshness_seconds: float = 180.0
    data_age_seconds: float = 180.0
    queue_age_seconds: float = 300.0
    cursor_age_seconds: float = 180.0
    gap_age_seconds: float = 300.0
    disk_warning_percent: float = 80.0
    disk_critical_percent: float = 90.0
    log_warning_bytes: int = 8 * 1024 * 1024


# Only failures that a clean TIM restart can plausibly resolve are eligible for
# automatic recovery. Governance, security, historical-data and capacity
# findings remain visible but must never cause a restart loop.
RESTARTABLE_CHECKS = frozenset({
    "runtime_process",
    "dashboard",
    "collector_freshness",
    "data_age",
    "cursor_age",
})


def _check(status: str, value: Any, reason: str) -> dict[str, Any]:
    return {"status": status, "value": value, "reason": reason}


def evaluate_watchdog(observed: dict[str, Any], thresholds: WatchdogThresholds) -> dict[str, Any]:
    """Pure fail-closed policy evaluation over independently collected facts."""
    checks: dict[str, dict[str, Any]] = {}
    checks["runtime_process"] = _check(
        "GREEN" if observed.get("runtime_running") is True else "RED",
        observed.get("runtime_running"),
        "launchd reports the canonical TIM service running",
    )
    collector_count = observed.get("collector_process_count")
    collector_pids = observed.get("collector_pids")
    runtime_pid = observed.get("runtime_pid")
    checks["single_collector"] = _check(
        "GREEN" if collector_count == 1 and collector_pids == [runtime_pid] else "RED",
        {"count": collector_count, "pids": collector_pids},
        "exactly one canonical TIM collector process must be active",
    )
    checks["dashboard"] = _check(
        "GREEN" if observed.get("dashboard_healthy") is True else "RED",
        observed.get("dashboard_status"),
        "loopback /api/health must return OBSERVE-only health",
    )
    collector_age = observed.get("collector_age_seconds")
    checks["collector_freshness"] = _check(
        "GREEN" if isinstance(collector_age, (int, float)) and collector_age <= thresholds.collector_freshness_seconds else "RED",
        collector_age,
        f"latest raw persistence must be <= {thresholds.collector_freshness_seconds:.0f}s old",
    )
    checks["postgres_listener"] = _check(
        "GREEN" if observed.get("postgres_loopback_only") is True else "RED",
        observed.get("postgres_listen_addresses"),
        "PostgreSQL listen_addresses must be socket/loopback only",
    )
    data_age = observed.get("data_age_seconds")
    checks["data_age"] = _check(
        "GREEN" if isinstance(data_age, (int, float)) and data_age <= thresholds.data_age_seconds else "RED",
        data_age,
        f"latest public market event must be <= {thresholds.data_age_seconds:.0f}s old",
    )
    queue_age = observed.get("queue_oldest_age_seconds")
    checks["queue_age"] = _check(
        "GREEN" if queue_age is None or (isinstance(queue_age, (int, float)) and queue_age <= thresholds.queue_age_seconds) else "RED",
        queue_age,
        f"oldest durable work must be <= {thresholds.queue_age_seconds:.0f}s old; None means empty",
    )
    cursor_age = observed.get("cursor_age_seconds")
    checks["cursor_age"] = _check(
        "GREEN" if isinstance(cursor_age, (int, float)) and cursor_age <= thresholds.cursor_age_seconds else "RED",
        cursor_age,
        f"durable cursor commit must be <= {thresholds.cursor_age_seconds:.0f}s old",
    )
    gap_count = observed.get("open_gap_count")
    gap_age = observed.get("oldest_gap_age_seconds")
    if gap_count == 0:
        gap_status = "GREEN"
    elif isinstance(gap_age, (int, float)) and gap_age <= thresholds.gap_age_seconds:
        gap_status = "YELLOW"
    else:
        gap_status = "RED"
    checks["gap_incidents"] = _check(
        gap_status,
        {"open": gap_count, "oldest_age_seconds": gap_age},
        "new gaps warn immediately and become critical after the bounded recovery window",
    )
    disk = observed.get("disk_used_percent")
    disk_status = (
        "RED" if not isinstance(disk, (int, float)) or disk >= thresholds.disk_critical_percent
        else "YELLOW" if disk >= thresholds.disk_warning_percent
        else "GREEN"
    )
    checks["disk_space"] = _check(
        disk_status,
        disk,
        f"disk warning/critical thresholds are {thresholds.disk_warning_percent:.0f}/{thresholds.disk_critical_percent:.0f}%",
    )
    largest_log = observed.get("largest_log_bytes")
    checks["log_growth"] = _check(
        "GREEN" if isinstance(largest_log, int) and largest_log <= thresholds.log_warning_bytes else "YELLOW",
        {"largest_bytes": largest_log, "path": observed.get("largest_log_path")},
        f"largest managed log should remain <= {thresholds.log_warning_bytes} bytes",
    )
    checks["observe_only"] = _check(
        "GREEN" if observed.get("observe_only") is True else "RED",
        observed.get("observe_only"),
        "runtime and frozen manifest must both prove OBSERVE-only",
    )
    actions = observed.get("trading_action_count")
    checks["trading_action_count"] = _check(
        "GREEN" if actions == 0 else "RED",
        actions,
        "unexpected execution tables or any trading action fail closed",
    )
    states = [item["status"] for item in checks.values()]
    status = "RED" if "RED" in states else "YELLOW" if "YELLOW" in states else "GREEN"
    return {
        "status": status,
        "mode": "OBSERVE",
        "trading_actions": actions,
        "checks": checks,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def restartable_failures(report: dict[str, Any]) -> tuple[str, ...]:
    """Return only runtime failures that a controlled restart may repair."""
    checks = report.get("checks")
    if not isinstance(checks, dict):
        return ()
    return tuple(
        name for name in sorted(RESTARTABLE_CHECKS)
        if isinstance(checks.get(name), dict) and checks[name].get("status") == "RED"
    )


class IndependentWatchdog:
    """Read-only collector independent from the TIM collector process."""

    def __init__(
        self,
        root: Path,
        database_url: str,
        *,
        symbol: str = "BTCUSDT",
        dashboard_url: str = "http://127.0.0.1:8765/api/health",
        thresholds: WatchdogThresholds | None = None,
    ) -> None:
        if not dashboard_url.startswith(("http://127.0.0.1:", "http://[::1]:", "http://localhost:")):
            raise ValueError("watchdog dashboard probe must remain loopback-only")
        self.root = root
        self.database_url = database_url
        self.symbol = symbol
        self.dashboard_url = dashboard_url
        self.thresholds = thresholds or WatchdogThresholds()

    async def _runtime(self) -> dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                str(self.root / "scripts/timctl"),
                "status",
                cwd=self.root,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            payload = json.loads(stdout) if process.returncode == 0 else {}
        except (OSError, ValueError, asyncio.TimeoutError):
            payload = {}
        service = payload.get("service", {}) if isinstance(payload, dict) else {}
        runtime_pid = service.get("pid")
        collector_pids: list[int] = []
        try:
            process = await asyncio.create_subprocess_exec(
                "/bin/ps", "-axo", "pid=,command=", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            canonical_main = str(self.root / "main.py")
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                if canonical_main not in line:
                    continue
                try:
                    collector_pids.append(int(line.strip().split(maxsplit=1)[0]))
                except (ValueError, IndexError):
                    continue
        except (OSError, asyncio.TimeoutError):
            collector_pids = []
        return {
            "runtime_running": service.get("loaded") is True and service.get("state") == "RUNNING",
            "runtime_pid": runtime_pid,
            "collector_process_count": len(collector_pids),
            "collector_pids": sorted(collector_pids),
        }

    async def _dashboard(self) -> dict[str, Any]:
        def request() -> dict[str, Any]:
            with urllib.request.urlopen(self.dashboard_url, timeout=3) as response:
                if int(response.status) != 200:
                    return {"dashboard_healthy": False, "dashboard_status": response.status}
                payload = json.loads(response.read(1_000_001))
                healthy = (
                    payload.get("mode") == "OBSERVE"
                    and payload.get("governance", {}).get("observe_only") is True
                )
                return {
                    "dashboard_healthy": healthy,
                    "dashboard_status": response.status,
                    "dashboard_observe_only": healthy,
                }

        try:
            return await asyncio.to_thread(request)
        except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
            return {"dashboard_healthy": False, "dashboard_status": "UNAVAILABLE", "dashboard_observe_only": False}

    async def _database(self) -> dict[str, Any]:
        database = Database(self.database_url, min_size=1, max_size=1)
        try:
            await database.connect()
            async with database.acquire() as connection:
                listener = str(await connection.fetchval("SELECT current_setting('listen_addresses')"))
                latest = await connection.fetchval(
                    "SELECT max(ingest_timestamp) FROM agg_trades WHERE symbol=$1", self.symbol
                )
                queue = await connection.fetchrow(
                    """SELECT count(*) FILTER (WHERE status IN ('PENDING','PROCESSING','RETRY','QUARANTINED')) AS depth,
                       EXTRACT(EPOCH FROM (clock_timestamp()-(min(created_at) FILTER (WHERE status IN ('PENDING','PROCESSING','RETRY','QUARANTINED'))))) AS oldest_age
                       FROM ingestion_outbox"""
                )
                cursor = await connection.fetchrow(
                    """SELECT last_persisted_at,recovery_state FROM ingestion_cursors
                       WHERE source='BINANCE' AND market='SPOT' AND symbol=$1 AND data_type='AGG_TRADE'""",
                    self.symbol,
                )
                gaps = await connection.fetchrow(
                    """SELECT count(*) AS count,
                       EXTRACT(EPOCH FROM (clock_timestamp()-min(detected_at))) AS oldest_age
                       FROM ingestion_gap_incidents WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')""",
                    self.symbol,
                )
                unexpected_execution = int(
                    await connection.fetchval(
                        """SELECT count(*) FROM information_schema.tables
                           WHERE table_schema NOT IN ('pg_catalog','information_schema')
                           AND lower(table_name) IN ('orders','executions','trades_executed','positions')"""
                    )
                )
            now = datetime.now(timezone.utc)
            listener_tokens = {item.strip() for item in listener.split(",") if item.strip()}
            listener_safe = listener_tokens <= {"localhost", "127.0.0.1", "::1"}
            latest_age = max(0.0, (now - latest).total_seconds()) if latest else None
            cursor_age = (
                max(0.0, (now - cursor["last_persisted_at"]).total_seconds())
                if cursor and cursor["last_persisted_at"] else None
            )
            return {
                "database_healthy": True,
                "postgres_listen_addresses": listener,
                "postgres_loopback_only": listener_safe,
                "collector_age_seconds": latest_age,
                "data_age_seconds": latest_age,
                "queue_depth": int(queue["depth"] or 0),
                "queue_oldest_age_seconds": float(queue["oldest_age"]) if queue["oldest_age"] is not None else None,
                "cursor_age_seconds": cursor_age,
                "cursor_recovery_state": cursor["recovery_state"] if cursor else "NO_CURSOR",
                "open_gap_count": int(gaps["count"] or 0),
                "oldest_gap_age_seconds": float(gaps["oldest_age"]) if gaps["oldest_age"] is not None else None,
                "trading_action_count": 0 if unexpected_execution == 0 else None,
                "unexpected_execution_table_count": unexpected_execution,
            }
        except Exception as error:
            return {
                "database_healthy": False,
                "database_error_type": type(error).__name__,
                "postgres_loopback_only": False,
                "trading_action_count": None,
            }
        finally:
            await database.close()

    def _filesystem(self) -> dict[str, Any]:
        usage = shutil.disk_usage(self.root)
        base = self.root / "data/operational"
        log_files = [
            path for path in base.iterdir()
            if path.is_file() and path.suffix in {".log", ".jsonl", ".out"}
        ] if base.exists() else []
        largest = max(log_files, key=lambda path: path.stat().st_size, default=None)
        return {
            "disk_used_percent": (usage.used / usage.total * 100) if usage.total else 100.0,
            "largest_log_bytes": largest.stat().st_size if largest else 0,
            "largest_log_path": str(largest) if largest else None,
        }

    def _manifest(self) -> dict[str, Any]:
        try:
            manifest = json.loads((self.root / "config/core_manifest.json").read_text(encoding="utf-8"))
            observe = manifest.get("status") == "FROZEN" and manifest.get("operating_mode") == "OBSERVE"
        except (OSError, ValueError):
            observe = False
        return {"manifest_observe_only": observe}

    async def collect(self) -> dict[str, Any]:
        runtime, dashboard, database = await asyncio.gather(
            self._runtime(), self._dashboard(), self._database()
        )
        manifest = self._manifest()
        observed = {
            **runtime,
            **dashboard,
            **database,
            **self._filesystem(),
            **manifest,
        }
        observed["observe_only"] = (
            observed.get("manifest_observe_only") is True
            and observed.get("dashboard_observe_only") is True
        )
        report = evaluate_watchdog(observed, self.thresholds)
        report["observed"] = observed
        report["watchdog_process"] = "INDEPENDENT_READ_ONLY"
        report["restart_requested"] = False
        return report
