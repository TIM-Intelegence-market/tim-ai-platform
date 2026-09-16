"""Fetch one verified Binance aggTrade range into an immutable offline candidate.

This tool has no database dependency and cannot mutate TIM's live cursor,
outbox, or gap state. It is deliberately range-bounded and restart-safe.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data_ingestion.catchup import PublicBinanceAggTradeClient


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--range-id", type=int, required=True)
    p.add_argument("--from-id", type=int, required=True)
    p.add_argument("--to-id", type=int, required=True)
    p.add_argument("--output-root", type=Path, default=Path("data/offline_raw_backfill_candidate"))
    args = p.parse_args()
    if args.from_id < 0 or args.to_id < args.from_id:
        raise SystemExit("invalid inclusive range")
    root = args.output_root / args.symbol / f"range_{args.range_id:02d}"
    payload = root / "agg_trades.jsonl"
    manifest = root / "manifest.json"
    if payload.exists() or manifest.exists():
        raise SystemExit("immutable candidate already exists; verify it instead of overwriting")
    root.mkdir(parents=True, exist_ok=False)
    temporary = payload.with_suffix(".partial")
    client = PublicBinanceAggTradeClient(minimum_interval=0.1)
    expected = args.from_id
    count = 0
    digest = hashlib.sha256()
    try:
        with temporary.open("wb") as handle:
            while expected <= args.to_id:
                batch = await client.fetch(args.symbol, expected, limit=min(1000, args.to_id - expected + 1))
                if not batch or batch[0].trade_id != expected:
                    raise RuntimeError(f"non-exact boundary at {expected}")
                for trade in batch:
                    if trade.trade_id != expected:
                        raise RuntimeError(f"non-contiguous trade id {trade.trade_id}; expected {expected}")
                    row = json.dumps({"symbol": trade.symbol, "aggregate_trade_id": trade.trade_id, "event_time": trade.event_time.isoformat(), "price": str(trade.price), "quantity": str(trade.quantity), "buyer_is_maker": trade.buyer_is_maker}, sort_keys=True, separators=(",", ":")).encode() + b"\n"
                    handle.write(row); digest.update(row); count += 1; expected += 1
        if count != args.to_id - args.from_id + 1:
            raise RuntimeError("count mismatch")
        temporary.replace(payload)
        value = {"status": "COMPLETE", "mode": "OFFLINE_CANDIDATE_ONLY", "symbol": args.symbol, "range_id": args.range_id, "from_id": args.from_id, "to_id": args.to_id, "expected_records": args.to_id - args.from_id + 1, "records": count, "sha256": digest.hexdigest(), "created_at_utc": datetime.now(timezone.utc).isoformat(), "live_outbox_mutations": 0, "live_cursor_mutations": 0, "trading_actions": 0}
        manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(value, sort_keys=True))
        return 0
    except Exception:
        temporary.unlink(missing_ok=True)
        root.rmdir()
        raise


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
