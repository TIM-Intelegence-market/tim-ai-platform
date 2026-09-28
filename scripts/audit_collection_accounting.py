"""Independent Mission-04 audit. SELECT-only database access; new artifacts only.

Never invokes the runtime, ingress, recovery, backfill or orchestrator ticks.
The old collection and persisted orchestration state are immutable inputs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg

from config.settings import settings
from src.collection_reporting import CollectionReportBuilder, collect_read_only_facts


def hashes(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(directory.iterdir()) if p.is_file()}


async def snapshot(start, end):
    connection = await asyncpg.connect(settings.database_url, timeout=5, command_timeout=30,
        server_settings={"default_transaction_read_only": "on"})
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            assert await connection.fetchval("SHOW transaction_read_only") == "on"
            metrics = {r["metric_name"]: r["numeric_value"] for r in await connection.fetch(
                "SELECT metric_name,numeric_value FROM ingestion_metrics")}
            coverage = [dict(r) for r in await connection.fetch(
                """SELECT (o.outbox_id IS NOT NULL) AS has_outbox,count(*) AS n,
                          min(t.aggregate_trade_id) AS first_id,max(t.aggregate_trade_id) AS last_id,
                          min(t.ingest_timestamp) AS first_ingested,max(t.ingest_timestamp) AS last_ingested,
                          count(*) FILTER(WHERE o.status='COMPLETED' AND o.completed_at IS NOT NULL
                                          AND o.output_hash IS NOT NULL) AS completed
                   FROM agg_trades t LEFT JOIN ingestion_outbox o ON o.symbol=t.symbol
                     AND o.aggregate_trade_id=t.aggregate_trade_id AND o.worker_name='CANDLE_V1'
                   WHERE t.symbol=$1 AND t.aggregate_trade_id >= $2 AND t.aggregate_trade_id <= $3
                   GROUP BY 1 ORDER BY 1""", settings.symbol, start, end)]
            cursors = [dict(r) for r in await connection.fetch("SELECT * FROM ingestion_cursors ORDER BY symbol")]
            gaps = [dict(r) for r in await connection.fetch(
                "SELECT status,count(*) AS n,max(updated_at) AS updated_at FROM ingestion_gap_incidents GROUP BY status ORDER BY status")]
            statuses = [dict(r) for r in await connection.fetch(
                "SELECT worker_name,status,count(*) AS n,max(updated_at) AS updated_at FROM ingestion_outbox GROUP BY 1,2 ORDER BY 1,2")]
            stats = [dict(r) for r in await connection.fetch(
                """SELECT relname,n_tup_ins,n_tup_upd,n_tup_del FROM pg_stat_user_tables
                   WHERE relname = ANY($1::text[]) ORDER BY relname""",
                ["agg_trades", "ingestion_outbox", "ingestion_cursors", "ingestion_gap_incidents", "candles"])]
            return {"captured_at": str(await connection.fetchval("SELECT clock_timestamp()")),
                    "transaction_read_only": True, "metrics": metrics, "coverage": coverage,
                    "cursors": cursors, "gaps": gaps, "outbox": statuses, "table_write_statistics": stats}
    finally:
        await connection.close()


async def main():
    old_dir = ROOT / "artifacts/collections/orchestrated-d45357132c0ef6037a77"
    old = json.loads((old_dir / "collection_result.json").read_text())
    old_hashes = hashes(old_dir)
    state = ROOT / "artifacts/orchestration/state.json"
    state_before = state.read_bytes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    audit_dir = ROOT / "artifacts/accounting_audit" / stamp
    # Fail before any work if the output name already exists; never overwrite.
    if audit_dir.exists():
        raise FileExistsError(audit_dir)
    first, last = (old["expected_period"][k] for k in ("first_trade_id", "last_trade_id"))
    before = await snapshot(first, last)
    collection_id = f"accounting-bounded-{stamp}"
    facts = await collect_read_only_facts(settings.database_url, root=ROOT, symbol=settings.symbol,
        collection_id=collection_id, max_events=10_000, requested_start=first, requested_end=last)
    # Evaluate first, then write a new independent report. This is the bounded
    # acceptance check, not a state transition and not a recollection of data.
    result = CollectionReportBuilder().write(ROOT, facts)
    after = await snapshot(first, last)
    assert hashes(old_dir) == old_hashes, "old report changed"
    assert state.read_bytes() == state_before, "orchestrator state changed"
    stable_fields = ("coverage", "cursors", "gaps", "outbox", "table_write_statistics")
    stable = all(before[k] == after[k] for k in stable_fields)
    m = before["metrics"]
    raw = int(m["raw_persisted_total"])
    duplicates = int(m["duplicate_total"])
    capacity = int(m["reject_reason:OUTBOX_CAPACITY"])
    received = int(m["received_total"])
    total = sum(r["n"] for r in before["coverage"])
    completed = sum(r["completed"] for r in before["coverage"])
    comparison = {
        "OLD_ACCOUNTING": {"collection_id": old["collection_id"], "counts": old["counts"], "checks": old["checks"],
            "requested_start": None, "requested_end": None, "collection_baseline": None,
            "reported_observed_bounds": old["expected_period"], "reported_limit": 10_000,
            "limit_enforced": False, "artifact_hashes": old_hashes},
        "CORRECTED_ACCOUNTING": {
            "durable_lifetime_reconciliation": {"received": received, "newly_persisted": raw,
                "duplicates": duplicates, "capacity_rejected": capacity,
                "formula": "received_total = raw_persisted_total + duplicate_total + reject_reason:OUTBOX_CAPACITY",
                "arithmetic_status": "PASS" if received == raw + duplicates + capacity else "FAIL",
                "scope": "global durable-ingress committed counters; not collection metrics"},
            "same_old_persisted_dataset": {"unique": total, "worker_completed": completed,
                "without_worker_completion_evidence": total - completed,
                "all_unique_events_processed": "PASS" if total == completed else "FAIL",
                "counts_accounted": "FAIL", "reason": "historical collection ingress evidence unavailable",
                "raw_count_matches_old_artifact": total == old["counts"]["events_unique"],
                "coverage": before["coverage"]},
            "new_bounded_snapshot": {"collection_id": collection_id, "report_dir": result["report_dir"],
                "counts": result["counts"], "checks": result["checks"], "actual_period": result["actual_period"],
                "event_ids_hash": facts["accounting"]["contract"]["event_ids_hash"]},
        },
        "ROOT_CAUSE": ["Whole-table historical raw inventory compared to durable-ingress epoch counters and outbox completions.",
            "The 10000-event limit was narrative only; no SQL bound or historical receipt baseline existed.",
            "Capacity rejections were mislabeled invalid; validation/parse failures occur at separate pipeline stages.",
            "Stored trades cannot reconstruct duplicate/rejected message occurrences for a retrospective collection."],
        "verification": {"production_data_changed_by_audit": False, "read_only_enforced_by_server": True,
            "observed_core_data_stable": stable, "old_artifacts_unchanged": True,
            "orchestrator_state_unchanged": True, "runtime_ingestion_metrics_excluded_from_stability":
            "The pre-existing runtime independently updates event-loop/reconnect telemetry."},
        "code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "src/collection_reporting/accounting.py", "src/collection_reporting/collector.py",
            "src/collection_reporting/reporter.py", "src/orchestration/runtime.py",
            "scripts/audit_collection_accounting.py")},
        "MISSION_04_ACCEPTANCE": "PASS" if result["quality_status"] in {"PASS", "WARN"} and stable else "FAIL",
        "SAFE_TO_ENABLE_BOUNDED_LIVE_INGESTION": "NO",
    }
    audit_dir.mkdir(parents=True, exist_ok=False)
    for name, value in {"before.json": before, "after.json": after, "facts.json": facts,
                        "OLD_VS_CORRECTED.json": comparison}.items():
        (audit_dir / name).write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    (audit_dir / "manifest.json").write_text(json.dumps(hashes(audit_dir), indent=2, sort_keys=True) + "\n")
    print(json.dumps({"audit_dir": str(audit_dir), "report_dir": result["report_dir"],
                      "checks": result["checks"], "core_data_stable": stable,
                      "MISSION_04_ACCEPTANCE": comparison["MISSION_04_ACCEPTANCE"],
                      "SAFE_TO_ENABLE_BOUNDED_LIVE_INGESTION": "NO"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
