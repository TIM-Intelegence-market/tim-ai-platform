from __future__ import annotations

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
    database = None
    try:
        database = Database(settings.database_url, min_size=1, max_size=2)
        await database.connect()
        store = DurableIngestionStore(database, queue_capacity=arguments.queue_capacity)
        coordinator = CatchUpCoordinator(
            store,
            PublicBinanceAggTradeClient(minimum_interval=arguments.minimum_interval),
            max_pages=arguments.max_pages,
            page_limit=arguments.page_limit,
        )
        results = []
        if arguments.next_live_trade_id is not None:
            results.append(await coordinator.recover_before(arguments.symbol, arguments.next_live_trade_id))
        else:
            for gap in await store.open_gaps(arguments.symbol, limit=arguments.max_gaps):
                results.append(await coordinator.recover_open_gap(gap))
        payload = {
            "mode": "OBSERVE",
            "source": "BINANCE_PUBLIC_SPOT_REST",
            "authenticated": False,
            "trading_actions": 0,
            "bounded": {
                "max_gaps": arguments.max_gaps,
                "max_pages_per_gap": arguments.max_pages,
                "page_limit": arguments.page_limit,
            },
            "results": [asdict(result) for result in results],
        }
        passed = all(result.status in {"COMPLETE", "NO_GAP"} for result in results)
        payload["status"] = "PASS" if passed else "OPEN_GAPS_REMAIN"
        return (0 if passed else 2), payload
    except Exception as error:
        return 3, {
            "status": "ERROR",
            "mode": "OBSERVE",
            "authenticated": False,
            "trading_actions": 0,
            "error_type": type(error).__name__,
            "error": str(error),
        }
    finally:
        if database is not None:
            await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded public Binance aggTrade catch-up")
    parser.add_argument("--symbol", default=settings.symbol.upper())
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--next-live-trade-id", type=int)
    group.add_argument("--open-gaps", action="store_true")
    parser.add_argument("--max-gaps", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--page-limit", type=int, default=1_000)
    parser.add_argument("--queue-capacity", type=int, default=50_000)
    parser.add_argument("--minimum-interval", type=float, default=0.05)
    arguments = parser.parse_args()
    if not 1 <= arguments.max_gaps <= 100:
        parser.error("--max-gaps must be between 1 and 100")
    code, payload = asyncio.run(run(arguments))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
