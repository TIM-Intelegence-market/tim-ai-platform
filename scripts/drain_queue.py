#!/usr/bin/env python3
"""Drain durable outbox queue without live ingestion — für 1.1 Backfill."""
import asyncio, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.database.connection import Database
from config.settings import settings
from main import TIMApplication

async def main():
    import argparse
    p = argparse.ArgumentParser(description="Drain outbox queue (CANDLE_V1) ohne WS")
    p.add_argument("--target", type=int, default=10000, help="queue_depth Ziel")
    p.add_argument("--timeout", type=float, default=300, help="max Sekunden")
    p.add_argument("--batch", type=int, default=100, help="batch_size")
    args = p.parse_args()

    app = TIMApplication()
    # Override worker batch for faster drain
    app.enrichment_worker.batch_size = args.batch
    await app.database.connect()
    await app.durable_store.bootstrap_cursor(settings.symbol)
    await app.restore_persisted_state()
    print(f"[drain] start queue_depth Ziel <{args.target}, batch {args.batch}")
    start = asyncio.get_running_loop().time()
    while True:
        snap = await app.durable_store.metrics_snapshot(settings.symbol)
        depth = snap["queue_depth"]
        print(f"[drain] depth={depth} oldest_age={snap['queue_oldest_age']} gaps={snap['open_gap_total']} cursor_age={snap['cursor_age']:.1f}")
        if depth <= args.target:
            print(f"[drain] Ziel erreicht depth {depth} <= {args.target}")
            break
        if asyncio.get_running_loop().time() - start > args.timeout:
            print(f"[drain] Timeout {args.timeout}s bei depth {depth}")
            break
        result = await app.enrichment_worker.run_once()
        if result["claimed"] == 0:
            await asyncio.sleep(0.5)
        # Alle 20 Durchläufe kurz warten
        await asyncio.sleep(0.05)
    await app.database.close()
    print("[drain] fertig")

if __name__ == "__main__":
    asyncio.run(main())
