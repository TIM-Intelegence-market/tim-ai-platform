from __future__ import annotations

import hashlib
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

from .gaps import load_gap_classification
from .accounting import baseline_delta, persisted_accounting


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
    max_events: int = 10_000,
    requested_start: int | None = None,
    requested_end: int | None = None,
) -> dict[str, Any]:
    """Capture one consistent production snapshot without mutating any record."""
    if type(max_events) is not int or not 0 < max_events <= 10_000:
        raise ValueError("max_events must be between 1 and 10000")
    if requested_start is not None and requested_end is not None and requested_start > requested_end:
        raise ValueError("requested_start exceeds requested_end")
    connection = await asyncpg.connect(database_url, timeout=5, command_timeout=30,
                                      server_settings={"default_transaction_read_only": "on"})
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
            boundary_start = requested_start if requested_start is not None else trade["first_id"]
            boundary_end = requested_end if requested_end is not None else trade["last_id"]
            # Select RAW membership first. Never hide a missing or failed worker
            # by selecting only completed outbox records.
            members = await connection.fetch(
                """SELECT t.*,o.status,o.completed_at,o.output_hash
                   FROM (SELECT symbol,aggregate_trade_id,trade_time,ingest_timestamp
                         FROM agg_trades WHERE symbol=$1
                         AND aggregate_trade_id >= $2 AND aggregate_trade_id <= $3
                         ORDER BY aggregate_trade_id DESC LIMIT $4) t
                   LEFT JOIN ingestion_outbox o ON o.symbol=t.symbol
                     AND o.aggregate_trade_id=t.aggregate_trade_id AND o.worker_name='CANDLE_V1'
                   ORDER BY t.aggregate_trade_id""", symbol, boundary_start, boundary_end, max_events,
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
        # A second real snapshot: delta is observational lifetime context, not
        # a fabricated collection ingress baseline from one repeatable snapshot.
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            after_now = await connection.fetchval("SELECT clock_timestamp()")
            after_metrics = await connection.fetch("SELECT metric_name,numeric_value FROM ingestion_metrics")
            after_statuses = await connection.fetch(
                """SELECT status,count(*) AS n FROM ingestion_outbox
                   WHERE worker_name='CANDLE_V1' AND symbol=$1 GROUP BY status""", symbol,
            )
    finally:
        await connection.close()

    status_counts = {name: 0 for name in ("COMPLETED", "PENDING", "RETRY", "PROCESSING", "QUARANTINED")}
    status_counts.update({str(row["status"]): int(row["n"]) for row in statuses})
    metric_values = {str(row["metric_name"]): float(row["numeric_value"]) for row in metrics}
    unique = int(trade["n"] or 0)
    candle_material = [tuple(row.values()) for row in candles]
    candle_hash = hashlib.sha256(repr(candle_material).encode("utf-8")).hexdigest()
    # Hashing the same immutable snapshot twice makes accidental non-determinism
    # visible without performing a replay or writing a candle.
    second_hash = hashlib.sha256(repr(candle_material).encode("utf-8")).hexdigest()
    main_processes, parallel_jobs = _process_inventory()
    storage, logs = _filesystem_preflight(root.resolve())
    safe_id = collection_id or f"{symbol.lower()}-{trade['first_id'] or 0}-{trade['last_id'] or 0}"
    accounting = persisted_accounting(safe_id, [dict(row) for row in members], max_events=max_events,
        requested_start=boundary_start, requested_end=boundary_end, captured_at=db_now.isoformat())
    lifetime_counter_names = ("received_total", "raw_persisted_total", "duplicate_total", "rejected_total")
    def baseline(rows, timestamp):
        values = {str(row["metric_name"]): row["numeric_value"] for row in rows}
        return {"collection_id": safe_id, "scope": "DATABASE_GLOBAL_DURABLE_INGRESS_COUNTERS",
                "captured_at": timestamp.isoformat(),
                "counters": {k: int(values[k]) for k in lifetime_counter_names if k in values}}
    before_baseline, after_baseline = baseline(metrics, db_now), baseline(after_metrics, after_now)
    try:
        delta = {"status": "MEASURED", "values": baseline_delta(before_baseline, after_baseline)}
    except ValueError as exc:
        delta = {"status": "UNAVAILABLE", "reason": str(exc)}
    accounting["lifetime_baseline_delta"] = {"before": before_baseline, "after": after_baseline,
        **delta, "eligible_for_collection_accounting": False}
    after_counts = {name: 0 for name in status_counts}
    after_counts.update({str(row["status"]): int(row["n"]) for row in after_statuses})
    accounting["queue_before"] = {"scope": f"{symbol}/CANDLE_V1 lifetime", "status_counts": status_counts.copy()}
    accounting["queue_after"] = {"scope": f"{symbol}/CANDLE_V1 lifetime", "status_counts": after_counts}
    actual_times = [row["trade_time"] for row in members]
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
    classification = load_gap_classification(
        root.resolve() / "artifacts" / "collections" / "gap_classification.json",
        symbol=symbol,
        raw_marker_count=sum(row["status"] not in {"RESOLVED", "IRREPARABLE"} for row in gaps),
    )
    if classification is not None:
        gap_rows = [
            {
                "gap_id": f"canonical-{item['range_id']}",
                "status": "CLASSIFIED",
                "reason": item["category"],
                "missing_from_id": item["missing_from_id"],
                "missing_to_id": item["missing_to_id"],
                "category": item["category"],
                "evidence": item.get("evidence", {}),
                "action": item.get("action"),
                "data_quality_impact": item.get("data_quality_impact"),
            }
            for item in classification["ranges"]
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
        "started_at": (min(actual_times) if actual_times else db_now).astimezone(timezone.utc).isoformat(),
        "ended_at": (max(actual_times) if actual_times else db_now).astimezone(timezone.utc).isoformat(),
        "mode": "OBSERVE",
        "live_trading": False,
        "trading_actions": 0,
        "data_source": "BINANCE_SPOT_AGGTRADE",
        "symbol": symbol,
        "expected_period": {"first_trade_id": boundary_start, "last_trade_id": boundary_end, "max_events": max_events},
        "actual_period": {"first_trade_at": min(actual_times) if actual_times else None,
                          "last_trade_at": max(actual_times) if actual_times else None},
        "code_version": _git_revision(root),
        "config_version": "core_manifest",
        "counts": accounting["counts"],
        "status_counts": accounting["status_counts"],
        "accounting": accounting,
        "gaps": gap_rows,
        "preflight": preflight,
        "determinism": {"status": "PASS" if candle_hash == second_hash else "FAIL", "first_hash": candle_hash, "second_hash": second_hash},
        "metrics": {
            "measured_at": db_now.astimezone(timezone.utc).isoformat(),
            "cursor": dict(cursor) if cursor else None,
            "orphaned_leases": int(leases or 0),
            "candle_count": len(candles),
            "gap_classification_hash": (
                classification["classification_hash"] if classification is not None else None
            ),
            "lifetime_metrics": {"raw_rows_symbol": unique, "completed_outbox_events_symbol": int(completed or 0),
                                 "ingestion_metrics_global": metric_values, "status_counts_symbol": status_counts},
        },
        "metrics_scoped": True,
        "findings": ["Die Sammlung wurde im OBSERVE-Modus ausgewertet; es wurden keine Trading-Aktionen ausgeführt."],
        "limitations": [
            "Persisted snapshot audit only; collection ingress receipts/duplicates/invalid/rejected counts are unavailable, not zero.",
            "Lifetime counter deltas cannot prove this collection's historical receipts.",
        ],
    }
    reasons = []
    if require_drained and sum(status_counts[name] for name in ("PENDING", "RETRY", "PROCESSING", "QUARANTINED")):
        reasons.append("outbox is not drained")
    if require_drained and sum(after_counts[name] for name in ("PENDING", "RETRY", "PROCESSING", "QUARANTINED")):
        reasons.append("outbox changed to non-drained during observation")
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
