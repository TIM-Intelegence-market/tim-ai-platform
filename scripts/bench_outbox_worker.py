#!/usr/bin/env python3
"""Measure the durable outbox worker cycle against an ISOLATED test database only.

Seeds a bloated outbox (completed filler rows) plus a live-like stream of active
trades, then runs the real TIM worker loop (claim -> load_trade -> candle handler
-> acknowledge -> metrics) and reports throughput and a per-step time breakdown.

Refuses any database that is not the explicit isolated test target
(TIM_DURABLE_TEST_DATABASE_URL, see src/database/safety.py). Never run against
production.

usage: TIM_RUNTIME_ENV=test TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS=true \
       TIM_DATABASE_SECRET_PROVIDER=url-env TIM_DURABLE_TEST_DATABASE_URL=... \
       python scripts/bench_outbox_worker.py [--filler 200000] [--active 3000]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import settings  # noqa: E402
from src.database.safety import require_safe_test_database  # noqa: E402

SYMBOL = settings.symbol


def timed(stats: dict, name: str, function):
    async def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return await function(*args, **kwargs)
        finally:
            stats[name].append(time.perf_counter() - started)
    return wrapper


async def clean(app) -> None:
    async with app.database.acquire() as connection:
        await connection.execute("DELETE FROM ingestion_outbox WHERE symbol=$1", SYMBOL)
        # The agg_trades foreign key is checked per deleted row against the outbox,
        # which has no (symbol, trade id) index; without dead tuples that stays cheap.
        await connection.execute("VACUUM ingestion_outbox")
        for table in ("candles", "agg_trades", "ingestion_cursors", "ingestion_gap_incidents"):
            await connection.execute(f"DELETE FROM {table} WHERE symbol=$1", SYMBOL)
        await connection.execute("DELETE FROM ingestion_metrics")


async def seed(app, filler: int, active: int) -> None:
    from src.models.market_data import Trade

    await clean(app)
    async with app.database.acquire() as connection:
        base = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=6)
        # Completed history (bloat): raw rows plus COMPLETED outbox rows, far below the active range.
        await connection.execute(
            """INSERT INTO agg_trades(symbol,aggregate_trade_id,trade_time,price,quantity,buyer_is_maker,source)
               SELECT $1, g, $2::timestamptz + g * interval '10 milliseconds', 100.0, 0.01, false, 'BINANCE_SPOT_AGGTRADE'
               FROM generate_series(1, $3) g""",
            SYMBOL, base, filler,
        )
        await connection.execute(
            """INSERT INTO ingestion_outbox(outbox_id,worker_name,idempotency_key,source,market,symbol,data_type,
                   aggregate_trade_id,status,attempts,input_hash,output_hash,worker_version,completed_at)
               SELECT encode(sha256(('o'||g)::bytea),'hex'),'CANDLE_V1',encode(sha256(('k'||g)::bytea),'hex'),
                      'BINANCE','SPOT',$1,'AGG_TRADE',g,'COMPLETED',1,encode(sha256(('i'||g)::bytea),'hex'),
                      encode(sha256(('h'||g)::bytea),'hex'),'bench',clock_timestamp()
               FROM generate_series(1, $2) g""",
            SYMBOL, filler,
        )
        await connection.execute("ANALYZE ingestion_outbox")
    # Active work arrives through the real ingress path (cursor, gap checks, outbox).
    start = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(hours=2)
    for index in range(active):
        trade_id = filler + 1 + index
        await app.durable_store.ingest_trade(
            Trade(SYMBOL, 100.0 + (index % 50) / 100, 0.01, start + timedelta(milliseconds=40 * index), trade_id, index % 2 == 0)
        )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filler", type=int, default=200_000)
    parser.add_argument("--active", type=int, default=3_000)
    parser.add_argument("--batch", type=int, default=None, help="override worker batch size (default: settings.outbox_batch_size)")
    args = parser.parse_args()
    require_safe_test_database(settings.database_url)

    import main as tim

    app = tim.TIMApplication()
    await app.database.connect()
    try:
        await app.database.initialize_schema()
        await seed(app, args.filler, args.active)
        stats: dict[str, list[float]] = defaultdict(list)
        store, worker = app.durable_store, app.enrichment_worker
        if args.batch is not None:
            worker.batch_size = args.batch
        for name in ("claim_detailed", "claim_strict_prefix", "load_trade", "load_trades", "renew_leases", "defer", "acknowledge", "record_metric", "metrics_snapshot"):
            setattr(store, name, timed(stats, name, getattr(store, name)))
        worker.handler = timed(stats, "handler", worker.handler)
        completed = 0
        original_run_once = worker.run_once

        async def run_once():
            nonlocal completed
            result = await original_run_once()
            completed += int(result.get("completed", 0))
            if completed >= args.active or (not result.get("claimed") and completed):
                app.worker_stop.set()
            return result

        worker.run_once = timed(stats, "run_once", run_once)
        started = time.perf_counter()
        await asyncio.wait_for(app._worker_loop(), timeout=3_600)
        elapsed = time.perf_counter() - started
        report = {
            "filler_completed_rows": args.filler,
            "active_items": args.active,
            "batch_size": worker.batch_size,
            "completed": completed,
            "elapsed_seconds": round(elapsed, 2),
            "items_per_second": round(completed / elapsed, 1) if elapsed else None,
            "ms_per_item": round(1000 * elapsed / completed, 2) if completed else None,
            "steps_total_ms_per_item": {
                name: round(1000 * sum(values) / max(completed, 1), 2) for name, values in sorted(stats.items())
            },
            "calls": {name: len(values) for name, values in sorted(stats.items())},
        }
        print(json.dumps(report, indent=1))
    finally:
        try:
            await clean(app)
        finally:
            await app.database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
