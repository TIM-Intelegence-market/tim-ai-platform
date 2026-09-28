#!/usr/bin/env python3
"""Backfill offene DATA_GAPs idempotent via Public Binance REST.

Phase 1.1 — Ohne 95% und Audit PASS ist jede Horizon-Lüge.
Quelle: TIM_TRANSPORT_RELIABILITY_REPORT.md, durable.py, catchup.py, docs/DATA_QUALITY.md

Verwendung:
  .venv/bin/python scripts/backfill_gaps.py --symbol BTCUSDT --max-gaps 20 --dry-run
  .venv/bin/python scripts/backfill_gaps.py --symbol BTCUSDT --max-gaps 63 --wait-for-queue 5

Garantien:
  - Idempotent: INSERT ... ON CONFLICT DO NOTHING (durable.py:379,429)
  - Bounded: max_pages 100, page_limit 1000, queue_capacity 50_000
  - Fail-closed: QueueCapacityError → warten, nicht droppen
  - Provenance: PUBLIC_MARKET_DATA_DETERMINISTIC, SHA-256 input_hash
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.data_ingestion.catchup import CatchUpCoordinator, PublicBinanceAggTradeClient
from src.data_ingestion.durable import DurableIngestionStore, QueueCapacityError
from src.database.connection import Database


async def wait_for_queue_space(store: DurableIngestionStore, symbol: str, threshold: int = 45000, poll: float = 5.0, timeout: float = 300.0) -> bool:
    """Warte bis queue_depth < threshold oder timeout."""
    import asyncio as aio
    elapsed = 0.0
    while elapsed < timeout:
        snap = await store.metrics_snapshot(symbol)
        depth = snap["queue_depth"]
        if depth < threshold:
            return True
        print(f"[backfill] queue_depth {depth} >= {threshold} — warte {poll}s (oldest_age {snap['queue_oldest_age']})")
        await aio.sleep(poll)
        elapsed += poll
    return False


async def main() -> int:
    p = argparse.ArgumentParser(description="Fülle offene Gaps idempotent via Binance aggTrades REST")
    p.add_argument("--symbol", default=settings.symbol, help="z. B. BTCUSDT")
    p.add_argument("--max-gaps", type=int, default=20, help="max Gaps pro Lauf (1-1000)")
    p.add_argument("--max-pages", type=int, default=100, help="max REST-Pages je Gap")
    p.add_argument("--page-limit", type=int, default=1000, help="limit je REST-Call (1-1000)")
    p.add_argument("--wait-for-queue", type=float, default=5.0, help="Sekunden warten bei QueueCapacityError")
    p.add_argument("--dry-run", action="store_true", help="Nur Gaps listen, kein REST")
    p.add_argument("--queue-threshold", type=int, default=45000, help="Warte bis queue_depth < threshold")
    args = p.parse_args()

    if not 1 <= args.max_gaps <= 1000:
        print("max-gaps muss 1-1000 sein", file=sys.stderr)
        return 2

    db = Database(settings.database_url)
    await db.connect()
    try:
        # Für Backfill temporär größere Queue, damit historische Lücken trotz vollem Live-Queue gefüllt werden können
        # Live-Runtime bleibt bei 50k, Backfill darf 200k nutzen — idempotent, kein Datenverlust
        store = DurableIngestionStore(db, queue_capacity=200_000)
        client = PublicBinanceAggTradeClient()
        coordinator = CatchUpCoordinator(store, client, max_pages=args.max_pages, page_limit=args.page_limit)

        cursor = await store.get_cursor(args.symbol)
        if cursor:
            print(f"[backfill] Cursor {args.symbol}: last_id={cursor.last_aggregate_trade_id} state={cursor.recovery_state} cursor_age={await store.metrics_snapshot(args.symbol).then(lambda s: s['cursor_age']) if False else 'n/a'}")
        else:
            print(f"[backfill] Kein Cursor für {args.symbol} — bootstrap zuerst")
            await store.bootstrap_cursor(args.symbol)

        fetch_limit = max(100, args.max_gaps * 3)
        raw_gaps = await store.open_gaps(args.symbol, limit=fetch_limit)
        gaps = sorted(raw_gaps, key=lambda g: ((g.get("missing_to_id") or 0) - (g.get("missing_from_id") or 0), g.get("detected_at") or ""))[:args.max_gaps]
        print(f"[backfill] Offene Gaps: {len(gaps)} (gefiltert aus {len(raw_gaps)} raw, limit {args.max_gaps}) — sortiert klein→groß")
        if not gaps:
            print("[backfill] Keine offenen Gaps — DONE, coverage prüfen via data_quality_report.py")
            snap = await store.metrics_snapshot(args.symbol)
            print(json.dumps(snap, indent=2))
            return 0

        for g in gaps:
            print(f"  gap_id={g['gap_id'][:16]}... from={g['missing_from_id']} to={g['missing_to_id']} reason={g['reason']} status={g['status']}")

        if args.dry_run:
            print("[backfill] dry-run — kein REST, exit 0")
            return 0

        # Vor jedem Gap: warte auf Queue-Platz
        ok = await wait_for_queue_space(store, args.symbol, threshold=args.queue_threshold, poll=args.wait_for_queue, timeout=120)
        if not ok:
            print(f"[backfill] Queue bleibt voll >{args.queue_threshold} — breche ab, worker muss drainen", file=sys.stderr)
            snap = await store.metrics_snapshot(args.symbol)
            print(json.dumps(snap, indent=2))
            return 1

        total_persisted = 0
        for idx, gap in enumerate(gaps, 1):
            print(f"[backfill] {idx}/{len(gaps)} Gap {gap['gap_id'][:16]} {gap['missing_from_id']}→{gap['missing_to_id']}")
            try:
                result = await coordinator.recover_open_gap(gap)
            except QueueCapacityError as e:
                print(f"[backfill] QueueCapacityError: {e} — warte {args.wait_for_queue}s")
                await asyncio.sleep(args.wait_for_queue)
                # retry once
                result = await coordinator.recover_open_gap(gap)

            print(f"  → {result.status} persisted={result.persisted} duplicates={result.duplicates} pages={result.pages} reason={result.reason}")
            total_persisted += result.persisted
            if result.status == "OPEN":
                print(f"  ⚠ Gap bleibt OPEN — Grund: {result.reason}")

            # Zwischen Gaps kurz warten, um Queue nicht zu fluten
            await asyncio.sleep(0.5)

        snap = await store.metrics_snapshot(args.symbol)
        print(f"[backfill] Fertig. total_persisted={total_persisted}")
        print(json.dumps(snap, indent=2))
        open_after = await store.open_gaps(args.symbol, limit=5)
        print(f"[backfill] Offene Gaps danach: {len(open_after)}")
        return 0
    finally:
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
