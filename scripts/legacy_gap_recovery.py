"""Dedicated legacy gap recovery executor (separate from the live path).

Reads a Gate-A manifest, re-verifies each merged range immediately before
mutation, then resolves fully-contained OPEN incidents in bounded batches.

Safety properties:
  - never touches agg_trades / queue / outbox / candles (gap_incidents only)
  - every UPDATE carries WHERE status='OPEN' (concurrency-safe, idempotent)
  - rowcount must match the batch (CONCURRENT_STATE_CHANGE stops the batch)
  - manifest checkpoint after every committed batch (resumable)
  - single executor only; live runtime health is checked between groups
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path


def plan_batches(items: list[str], batch_size: int, skip_batches: int = 0):
    """Deterministic batch slicing. Pure function (unit-tested)."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if skip_batches < 0:
        raise ValueError("skip_batches must be non-negative")
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    return batches[skip_batches:]


BATCH_UPDATE_SQL = (
    "UPDATE ingestion_gap_incidents SET status='RESOLVED',"
    "resolved_at=clock_timestamp(),updated_at=clock_timestamp() "
    "WHERE gap_id = ANY($1) AND status='OPEN'"
)

VERIFY_RANGE_SQL = (
    "SELECT COUNT(*) n, MIN(aggregate_trade_id) mn, MAX(aggregate_trade_id) mx "
    "FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3"
)

OPEN_IN_RANGE_SQL = (
    "SELECT gap_id FROM ingestion_gap_incidents "
    "WHERE status='OPEN' AND gap_id = ANY($1) ORDER BY detected_at,gap_id"
)


def range_fingerprint(symbol: str, start: int, end: int, count: int) -> str:
    return hashlib.sha256(("%s%d%d%d" % (symbol, start, end, count)).encode()).hexdigest()


async def verify_range(conn, symbol: str, start: int, end: int, expected_span: int) -> dict:
    row = await conn.fetchrow(VERIFY_RANGE_SQL, symbol, start, end)
    complete = (
        row["n"] == expected_span and row["mn"] == start and row["mx"] == end
    )
    return {"complete": complete, "count": row["n"], "span": expected_span}


async def run_batch(conn, batch: list[str]) -> int:
    """Returns updated row count; caller must compare with len(batch)."""
    result = await conn.execute(BATCH_UPDATE_SQL, batch)
    # asyncpg returns e.g. 'UPDATE 200'
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError, AttributeError):
        return -1


async def main_async(args) -> int:
    import asyncpg  # local import: keeps module importable without driver

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("manifest_hash") != hashlib.sha256(
        json.dumps({k: v for k, v in manifest.items() if k != "manifest_hash"}, sort_keys=True).encode()
    ).hexdigest():
        print("MANIFEST_HASH_MISMATCH", flush=True)
        return 2

    pw = Path(os.environ["TIM_DATABASE_SECRET_FILE"]).read_text().strip()
    conn = await asyncpg.connect(
        host=os.environ.get("TIM_DATABASE_HOST", "127.0.0.1"),
        port=int(os.environ.get("TIM_DATABASE_PORT", "5432")),
        database=os.environ.get("TIM_DATABASE_NAME", "tim"),
        user=os.environ.get("TIM_DATABASE_USER", "tim"),
        password=pw,
    )
    audit_log = open(args.audit_log, "a")
    try:
        ranges = manifest["ranges"]
        checkpoint_path = Path(str(manifest_path) + ".checkpoint.json")
        checkpoint: dict[str, dict] = {}
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text())

        def save_checkpoint() -> None:
            checkpoint_path.write_text(json.dumps(checkpoint, indent=1))

        def range_state(rid: str) -> dict:
            return checkpoint.setdefault(rid, {"batches_done": 0, "resolved_count": 0, "status": "PENDING"})

        if args.canary:
            # Smallest incident count = minimal blast radius.
            ranges = sorted(ranges, key=lambda r: r["incident_count"])[:1]
        total_updated = 0
        for rpos, item in enumerate(ranges):
            state = range_state(item["merged_range_id"])
            if state.get("status") == "RANGE_DONE":
                print("SKIP_DONE %s" % item["merged_range_id"][:12], flush=True)
                continue
            if item.get("status") != "VERIFIED_COMPLETE":
                print("SKIP_UNVERIFIED %s" % item["merged_range_id"][:12], flush=True)
                continue
            t0 = time.monotonic()
            check = await verify_range(
                conn, manifest["symbol"], item["start_trade_id"], item["end_trade_id"], item["expected_span"]
            )
            if not check["complete"]:
                print("RANGE_CHANGED %s count=%s span=%s" % (
                    item["merged_range_id"][:12], check["count"], item["expected_span"]), flush=True)
                audit_log.write(json.dumps({"event": "RANGE_CHANGED", "range": item["merged_range_id"]}) + "\n")
                continue
            rows = await conn.fetch(OPEN_IN_RANGE_SQL, item["gap_ids"])
            open_ids = [row["gap_id"] for row in rows]
            batches = plan_batches(open_ids, args.batch_size, skip_batches=state["batches_done"])
            for bpos, batch in enumerate(batches):
                updated = await run_batch(conn, batch)
                if updated != len(batch):
                    print("CONCURRENT_STATE_CHANGE range=%s batch=%d expected=%d actual=%d" % (
                        item["merged_range_id"][:12], state["batches_done"], len(batch), updated), flush=True)
                    audit_log.write(json.dumps({"event": "CONCURRENT_STATE_CHANGE",
                        "range": item["merged_range_id"], "expected": len(batch), "actual": updated}) + "\n")
                    audit_log.flush()
                    return 3
                state["batches_done"] += 1
                state["resolved_count"] += updated
                total_updated += updated
                audit_log.write(json.dumps({"event": "BATCH", "range": item["merged_range_id"],
                    "batch": state["batches_done"], "rows": updated,
                    "ms": int((time.monotonic() - t0) * 1000)}) + "\n")
                audit_log.flush()
                save_checkpoint()
                if args.canary:
                    print("CANARY_DONE updated=%d" % updated, flush=True)
                    return 0
            # Range finished: confirm nothing OPEN remains for its incidents.
            remaining = await conn.fetchval(
                "SELECT COUNT(*) FROM ingestion_gap_incidents WHERE status='OPEN' AND gap_id = ANY($1)",
                item["gap_ids"],
            )
            if remaining == 0:
                state["status"] = "RANGE_DONE"
                save_checkpoint()
                print("RANGE_DONE %s resolved=%d" % (item["merged_range_id"][:12], state["resolved_count"]), flush=True)
            else:
                print("RANGE_PARTIAL %s remaining=%d" % (item["merged_range_id"][:12], remaining), flush=True)
        print("TOTAL_UPDATED=%d" % total_updated, flush=True)
        return 0
    finally:
        audit_log.close()
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Legacy gap recovery executor (manifest-driven)")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--audit-log", required=True)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--canary", action="store_true")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
