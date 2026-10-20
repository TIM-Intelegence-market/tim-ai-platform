#!/usr/bin/env python3
"""Refresh measured horizon inputs and audit bounded open gap markers."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.database.connection import Database
from src.data_ingestion.durable import DurableIngestionStore
from src.operational.horizon_readiness import collect_horizons


def save(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)


async def run(*, resolve_verified: bool = False, max_gaps: int = 25, max_trade_ids: int = 200_000) -> dict:
    database = Database(settings.database_url, min_size=1, max_size=1)
    await database.connect()
    try:
        symbol = settings.symbol.upper()
        now = datetime.now(timezone.utc)
        report_path = ROOT / "data/operational/readiness_inputs.json"
        try:
            previous = json.loads(report_path.read_text())
            after_id = str(previous.get("last_checked_gap_id", ""))
        except (OSError, ValueError, AttributeError):
            after_id = ""
        async with database.acquire() as connection:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                horizons = await collect_horizons(connection, symbol, now)
                inventory = await connection.fetch(
                    """SELECT reason,status,count(*) AS count,
                       min(detected_at) AS oldest_detected_at,
                       count(*) FILTER (WHERE missing_from_id IS NULL OR missing_to_id IS NULL) AS unknown_range,
                       count(*) FILTER (WHERE missing_from_id >= 0 AND missing_to_id >= missing_from_id
                         AND missing_to_id::numeric-missing_from_id+1 <= $2::bigint) AS bounded_candidates
                       FROM ingestion_gap_incidents WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')
                       GROUP BY reason,status ORDER BY count(*) DESC""", symbol, max_trade_ids,
                )
                # Filter before LIMIT and rotate across bounded ranges so an
                # incomplete prefix cannot starve later complete incidents.
                candidate_query = """SELECT gap_id,missing_from_id,missing_to_id,reason
                       FROM ingestion_gap_incidents
                       WHERE symbol=$1 AND status='OPEN' AND missing_from_id >= 0
                         AND missing_to_id >= missing_from_id
                         AND missing_to_id::numeric-missing_from_id+1 <= $2::bigint
                         AND gap_id > $4
                       ORDER BY gap_id LIMIT $3"""
                candidates = await connection.fetch(candidate_query, symbol, max_trade_ids, max_gaps, after_id)
                if not candidates and after_id:
                    candidates = await connection.fetch(candidate_query, symbol, max_trade_ids, max_gaps, "")
                checked = []
                for gap in candidates:
                    present = await connection.fetchval(
                        """SELECT count(*) FROM agg_trades WHERE symbol=$1
                           AND aggregate_trade_id BETWEEN $2 AND $3""",
                        symbol, gap["missing_from_id"], gap["missing_to_id"],
                    )
                    expected = gap["missing_to_id"] - gap["missing_from_id"] + 1
                    checked.append({**dict(gap), "expected_ids": expected, "stored_ids": int(present),
                                    "complete": present == expected, "resolved": False})
        # Fresh completeness verification on write, outside the audit snapshot.
        if resolve_verified:
            store = DurableIngestionStore(database)
            for gap in checked:
                if gap["complete"]:
                    gap["resolved"] = await store.resolve_gap(gap["gap_id"])
        save(ROOT / "data/operational/horizon_readiness.json", horizons)
        report = {
            "checked_at": now.isoformat(), "status": "PASS", "mode": "OBSERVE", "trading_actions": 0,
            "open_gap_inventory_before": [dict(row) for row in inventory], "checked_gaps": checked,
            "resolved": sum(gap["resolved"] for gap in checked), "max_trade_ids": max_trade_ids,
            "max_gaps": max_gaps, "resolve_verified": resolve_verified,
            "last_checked_gap_id": checked[-1]["gap_id"] if checked else "",
            "historical_backfill_performed": False,
        }
        save(report_path, report)
        return {"horizons": horizons, "gap_audit": report}
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve-verified", action="store_true")
    parser.add_argument("--max-gaps", type=int, default=25)
    parser.add_argument("--max-trade-ids", type=int, default=200_000)
    args = parser.parse_args()
    if not 1 <= args.max_gaps <= 100 or not 1 <= args.max_trade_ids <= 1_000_000:
        parser.error("max-gaps must be 1..100 and max-trade-ids 1..1000000")
    result = asyncio.run(run(resolve_verified=args.resolve_verified, max_gaps=args.max_gaps, max_trade_ids=args.max_trade_ids))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
