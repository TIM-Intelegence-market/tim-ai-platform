from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.data_ingestion.catchup import PublicBinanceAggTradeClient


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

async def build(symbol: str) -> dict[str, object]:
    connection = await asyncpg.connect(settings.database_url, timeout=5, command_timeout=60)
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            bounds = await connection.fetchrow(
                """SELECT count(*) raw_markers,min(missing_from_id) first_id,max(missing_to_id) last_id
                   FROM ingestion_gap_incidents WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP')
                   AND missing_from_id IS NOT NULL AND missing_to_id IS NOT NULL""", symbol,
            )
            if not bounds or not bounds["raw_markers"]:
                return {"symbol": symbol, "raw_markers": 0, "ranges": [], "unknown_gaps": 0}
            holes = await connection.fetch(
                """WITH ordered AS (
                       SELECT aggregate_trade_id,lag(aggregate_trade_id) OVER (ORDER BY aggregate_trade_id) prior
                       FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3
                   ), internal AS (
                       SELECT prior+1 first_id,aggregate_trade_id-1 last_id
                       FROM ordered WHERE prior IS NOT NULL AND aggregate_trade_id>prior+1
                   ), present AS (
                       SELECT min(aggregate_trade_id) first_present,max(aggregate_trade_id) last_present
                       FROM agg_trades WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3
                   )
                   SELECT first_id,last_id FROM internal
                   UNION ALL SELECT $2,first_present-1 FROM present WHERE first_present>$2
                   UNION ALL SELECT last_present+1,$3 FROM present WHERE last_present<$3
                   ORDER BY first_id""",
                symbol, int(bounds["first_id"]), int(bounds["last_id"]),
            )
    finally:
        await connection.close()

    client = PublicBinanceAggTradeClient(minimum_interval=0.1)
    ranges = []
    for index, row in enumerate(holes, 1):
        first_id, last_id = int(row["first_id"]), int(row["last_id"])
        probes = []
        for requested in (first_id, last_id):
            try:
                values = await client.fetch(symbol, requested, limit=1)
                returned = values[0].trade_id if values else None
                probes.append({
                    "requested": requested,
                    "returned": returned,
                    "event_time": values[0].event_time.isoformat() if values else None,
                    "exact": returned == requested,
                })
            except Exception as exc:
                probes.append({"requested": requested, "returned": None, "exact": False, "error": f"{type(exc).__name__}: {exc}"})
        recoverable = all(item["exact"] for item in probes)
        ranges.append({
            "range_id": index,
            "missing_from_id": first_id,
            "missing_to_id": last_id,
            "expected_records": last_id - first_id + 1,
            "present_records": 0,
            "category": "RECOVERABLE_BACKFILL" if recoverable else "UNKNOWN",
            "evidence": {"official_binance_public_boundary_probes": probes},
            "action": "DEFER_UNTIL_BOUNDED_CAPACITY_SAFE_PLAN" if recoverable else "SAFE_STOP_REVIEW",
            "data_quality_impact": "CONTINUOUS_COVERAGE_NOT_ESTABLISHED",
        })
    payload = {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "OBSERVE",
        "read_only_database": True,
        "database_rows_written": 0,
        "symbol": symbol,
        "raw_markers": int(bounds["raw_markers"]),
        "canonical_ranges": len(ranges),
        "classified_gaps": sum(item["category"] != "UNKNOWN" for item in ranges),
        "unknown_gaps": sum(item["category"] == "UNKNOWN" for item in ranges),
        "missing_records": sum(item["expected_records"] for item in ranges),
        "ranges": ranges,
    }
    hash_payload = dict(payload); hash_payload.pop("generated_at")
    payload["classification_hash"] = digest(hash_payload)
    return payload


async def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only canonical TIM gap classification")
    parser.add_argument("--symbol", default=settings.symbol)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/collections/gap_classification.json")
    args = parser.parse_args()
    result = await build(args.symbol)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(args.output)
    print(json.dumps({key: result[key] for key in ("raw_markers", "canonical_ranges", "classified_gaps", "unknown_gaps", "missing_records", "classification_hash")}, sort_keys=True))
    return 0 if result["unknown_gaps"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
