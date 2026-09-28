#!/usr/bin/env python3
"""Create a read-only closure audit for the seven historical BTCUSDT gaps."""

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

RANGES = (
    (1, 4030964128, 4043645752),
    (2, 4043646753, 4043728445),
    (3, 4043729446, 4043803591),
    (4, 4043804592, 4043961031),
    (5, 4043962032, 4044038564),
    (6, 4044039565, 4044092403),
    (7, 4047610943, 4064031063),
)


def canonical_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


async def build(database_url: str) -> dict:
    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=120)
    client = PublicBinanceAggTradeClient(minimum_interval=0.1)
    rows = []
    try:
        async with connection.transaction(isolation="repeatable_read", readonly=True):
            for range_id, start, end in RANGES:
                present = int(await connection.fetchval(
                    """SELECT count(DISTINCT aggregate_trade_id) FROM agg_trades
                       WHERE symbol='BTCUSDT' AND aggregate_trade_id BETWEEN $1 AND $2""",
                    start, end,
                ))
                probes = []
                for requested in (start, end):
                    value = (await client.fetch("BTCUSDT", requested, limit=1))[0]
                    probes.append({
                        "requested_id": requested,
                        "returned_id": value.trade_id,
                        "event_time_utc": value.event_time.isoformat(),
                        "exact": value.trade_id == requested,
                    })
                expected = end - start + 1
                rows.append({
                    "range_id": range_id,
                    "from_id": start,
                    "to_id": end,
                    "expected_records": expected,
                    "present_distinct_records": present,
                    "missing_records": expected - present,
                    "coverage_percent": "100.000" if present == expected else f"{100 * present / expected:.3f}",
                    "official_boundary_probes": probes,
                    "status": "CLOSED" if present == expected and all(item["exact"] for item in probes) else "OPEN",
                })
    finally:
        await connection.close()
    report = {
        "schema_version": "1.0.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "OBSERVE",
        "trading_actions": 0,
        "database_rows_written": 0,
        "source": "BINANCE_PUBLIC_SPOT_AGGTRADE",
        "ranges": rows,
        "all_ranges_closed": all(row["status"] == "CLOSED" for row in rows),
        "total_expected_records": sum(row["expected_records"] for row in rows),
        "total_missing_records": sum(row["missing_records"] for row in rows),
    }
    material = dict(report)
    material.pop("generated_at_utc")
    report["report_hash"] = canonical_hash(material)
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/data_quality/historical_gap_closure_audit.json")
    args = parser.parse_args()
    report = await build(args.database_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({
        "all_ranges_closed": report["all_ranges_closed"],
        "total_expected_records": report["total_expected_records"],
        "total_missing_records": report["total_missing_records"],
        "report_hash": report["report_hash"],
    }, sort_keys=True))
    return 0 if report["all_ranges_closed"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
