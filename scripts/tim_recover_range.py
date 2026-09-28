from __future__ import annotations

"""Recover one audited aggregate-trade ID range using public Binance data."""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.data_ingestion.catchup import CatchUpCoordinator, PublicBinanceAggTradeClient
from src.data_ingestion.durable import DurableIngestionStore
from src.database.connection import Database


async def run(arguments: argparse.Namespace) -> tuple[int, dict]:
    database = Database(settings.database_url, min_size=1, max_size=2)
    try:
        await database.connect()
        store = DurableIngestionStore(database, queue_capacity=50_000)
        gap_id = await store.record_gap(
            symbol=arguments.symbol.upper(),
            missing_from_id=arguments.from_id,
            missing_to_id=arguments.to_id,
            reason="HISTORICAL_TARGETED_RECOVERY",
            details={"requested_by": "tim_recover_range", "bounded": True},
        )
        result = await CatchUpCoordinator(
            store, PublicBinanceAggTradeClient(minimum_interval=arguments.minimum_interval),
            max_pages=arguments.max_pages, page_limit=arguments.page_limit,
        ).recover_open_gap({"gap_id": gap_id, "symbol": arguments.symbol.upper(), "missing_from_id": arguments.from_id, "missing_to_id": arguments.to_id})
        payload = {"mode": "OBSERVE", "trading_actions": 0, "gap_id": gap_id, "result": asdict(result)}
        return (0 if result.status == "COMPLETE" else 2), payload
    except Exception as error:
        return 3, {"mode": "OBSERVE", "trading_actions": 0, "status": "ERROR", "error_type": type(error).__name__, "error": str(error)}
    finally:
        await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded exact-range TIM recovery (OBSERVE-only)")
    parser.add_argument("--symbol", default=settings.symbol.upper())
    parser.add_argument("--from-id", type=int, required=True)
    parser.add_argument("--to-id", type=int, required=True)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--page-limit", type=int, default=1_000)
    parser.add_argument("--minimum-interval", type=float, default=0.05)
    arguments = parser.parse_args()
    if arguments.from_id < 0 or arguments.to_id < arguments.from_id:
        parser.error("IDs must be non-negative and --to-id must be >= --from-id")
    required_pages = (arguments.to_id - arguments.from_id + arguments.page_limit) // arguments.page_limit
    if arguments.max_pages < required_pages:
        parser.error("--max-pages is too small for the requested exact range")
    code, payload = asyncio.run(run(arguments))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
