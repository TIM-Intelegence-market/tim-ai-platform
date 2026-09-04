from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg


class CollectionPreflightError(RuntimeError):
    def __init__(self, reasons: list[str], snapshot: dict[str, Any]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons
        self.snapshot = snapshot


def _process_inventory() -> tuple[int, int]:
    output = subprocess.run(
        ["ps", "-axo", "command="], check=True, capture_output=True, text=True, timeout=5
    ).stdout.splitlines()
    main_count = sum("main.py" in line and "TIM" in line for line in output)
    parallel = sum(
        any(token in line.lower() for token in ("recover_quarantined.py", "scaled_quarantine_drain.py", "backfill_gaps.py", "drain_queue.py"))
        for line in output
    )
    return main_count, parallel


def _filesystem_preflight(root: Path) -> tuple[str, str]:
    stat = os.statvfs(root)
    free = stat.f_bavail * stat.f_frsize
    storage = "PASS" if free >= 512 * 1024 * 1024 else "FAIL"
    log_root = root / "logs"
    oversized = [path for path in log_root.glob("*.log") if path.stat().st_size > 512 * 1024 * 1024] if log_root.exists() else []
    return storage, "PASS" if not oversized else "FAIL"


async def collect_read_only_facts(
    database_url: str,
    *,
    root: Path,
    symbol: str,
    collection_id: str | None = None,
    require_drained: bool = True,
) -> dict[str, Any]:
    """Capture one consistent production snapshot without mutating any record."""
    connection = await asyncpg.connect(database_url, timeout=5, command_timeout=30)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            db_now = await connection.fetchval("SELECT clock_timestamp()")
            trade = await connection.fetchrow(
                """SELECT count(*) AS n, min(trade_time) AS first_at, max(trade_time) AS last_at,
                          min(aggregate_trade_id) AS first_id, max(aggregate_trade_id) AS last_id
                   FROM agg_trades WHERE symbol=$1""", symbol,
            )
            statuses = await connection.fetch(
                """SELECT status,count(*) AS n FROM ingestion_outbox
                   WHERE worker_name='CANDLE_V1' AND symbol=$1 GROUP BY status""", symbol,
            )
            completed = await connection.fetchval(
                """SELECT count(DISTINCT aggregate_trade_id) FROM ingestion_outbox
                   WHERE worker_name='CANDLE_V1' AND symbol=$1 AND status='COMPLETED'""", symbol,
            )
            metrics = await connection.fetch(
                "SELECT metric_name,numeric_value FROM ingestion_metrics"
            )
            gaps = await connection.fetch(
                """SELECT gap_id,status,reason,missing_from_id,missing_to_id,gap_started_at,
                          gap_ended_at,last_error FROM ingestion_gap_incidents
                   WHERE symbol=$1 ORDER BY detected_at,gap_id""", symbol,
            )
            leases = await connection.fetchval(
                """SELECT count(*) FROM ingestion_outbox
                   WHERE status='PROCESSING' AND lease_expires_at < clock_timestamp()"""
            )
            cursor = await connection.fetchrow(
                """SELECT last_aggregate_trade_id,last_event_time,last_persisted_at,cursor_hash,recovery_state
                   FROM ingestion_cursors WHERE source='BINANCE' AND market='SPOT'
                   AND symbol=$1 AND data_type='AGG_TRADE'""", symbol,
            )
            candles = await connection.fetch(
                """SELECT timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed
                   FROM candles WHERE symbol=$1 ORDER BY timeframe,open_time""", symbol,
            )
    finally:
        await connection.close()

    status_counts = {name: 0 for name in ("COMPLETED", "PENDING", "RETRY", "PROCESSING", "QUARANTINED")}
    status_counts.update({str(row["status"]): int(row["n"]) for row in statuses})
    metric_values = {str(row["metric_name"]): float(row["numeric_value"]) for row in metrics}
    unique = int(trade["n"] or 0)
    duplicates = int(metric_values.get("duplicate_total", 0))
    invalid = int(metric_values.get("rejected_total", 0))
    received = int(metric_values.get("received_total", unique + duplicates + invalid))
    candle_material = [tuple(row.values()) for row in candles]
    candle_hash = hashlib.sha256(repr(candle_material).encode("utf-8")).hexdigest()
    # Hashing the same immutable snapshot twice makes accidental non-determinism
    # visible without performing a replay or writing a candle.
    second_hash = hashlib.sha256(repr(candle_material).encode("utf-8")).hexdigest()
    main_processes, parallel_jobs = _process_inventory()
    storage, logs = _filesystem_preflight(root.resolve())
    safe_id = collection_id or f"{symbol.lower()}-{trade['first_id'] or 0}-{trade['last_id'] or 0}"
    gap_rows = [
        {
            "gap_id": row["gap_id"],
            "status": "IRREPARABLE_DOCUMENTED" if row["status"] == "IRREPARABLE" else row["status"],
            "reason": row["reason"],
            "missing_from_id": row["missing_from_id"],
            "missing_to_id": row["missing_to_id"],
            "gap_started_at": row["gap_started_at"].isoformat() if row["gap_started_at"] else None,
            "gap_ended_at": row["gap_ended_at"].isoformat() if row["gap_ended_at"] else None,
            "last_error": row["last_error"],
        }
        for row in gaps
    ]
    preflight = {
        "database": "PASS",
        "main_processes": main_processes,
        "parallel_jobs": parallel_jobs,
        "logs": logs,
        "storage": storage,
        "orphaned_leases": int(leases or 0),
    }
    facts = {
        "collection_id": safe_id,
        "started_at": (trade["first_at"] or db_now).astimezone(timezone.utc).isoformat(),
        "ended_at": (trade["last_at"] or db_now).astimezone(timezone.utc).isoformat(),
        "mode": "OBSERVE",
        "live_trading": False,
        "trading_actions": 0,
        "data_source": "BINANCE_SPOT_AGGTRADE",
        "symbol": symbol,
        "expected_period": {"first_trade_id": trade["first_id"], "last_trade_id": trade["last_id"]},
        "actual_period": {"first_trade_at": trade["first_at"], "last_trade_at": trade["last_at"]},
        "code_version": _git_revision(root),
        "config_version": "core_manifest",
        "counts": {
            "events_received": received,
            "events_unique": unique,
            "events_processed": int(completed or 0),
            "duplicates": duplicates,
            "invalid_events": invalid,
        },
        "status_counts": status_counts,
        "gaps": gap_rows,
        "preflight": preflight,
        "determinism": {"status": "PASS" if candle_hash == second_hash else "FAIL", "first_hash": candle_hash, "second_hash": second_hash},
        "metrics": {
            "measured_at": db_now.astimezone(timezone.utc).isoformat(),
            "cursor": dict(cursor) if cursor else None,
            "orphaned_leases": int(leases or 0),
            "candle_count": len(candles),
        },
        "metrics_scoped": False,
        "findings": ["Die Sammlung wurde im OBSERVE-Modus ausgewertet; es wurden keine Trading-Aktionen ausgeführt."],
        "limitations": [
            "Ingress-Metriken sind historisch kumulativ und noch nicht durch eine Collection-Baseline abgegrenzt."
        ],
    }
    reasons = []
    if require_drained and sum(status_counts[name] for name in ("PENDING", "RETRY", "PROCESSING", "QUARANTINED")):
        reasons.append("outbox is not drained")
    if int(leases or 0): reasons.append("orphaned processing leases exist")
    if main_processes != 1: reasons.append("exactly one TIM main process is required")
    if parallel_jobs: reasons.append("parallel recovery/drain/backfill process detected")
    if storage != "PASS": reasons.append("insufficient free storage")
    if logs != "PASS": reasons.append("log preflight failed")
    if reasons:
        raise CollectionPreflightError(reasons, facts)
    return facts


def _git_revision(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
