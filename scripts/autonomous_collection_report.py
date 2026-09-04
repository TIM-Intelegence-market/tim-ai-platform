from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.collection_reporting import (
    CollectionPreflightError,
    CollectionReportBuilder,
    CollectionReportError,
    collect_read_only_facts,
)


async def run(args: argparse.Namespace) -> int:
    try:
        facts = await collect_read_only_facts(
            settings.database_url,
            root=ROOT,
            symbol=args.symbol,
            collection_id=args.collection_id,
            require_drained=True,
        )
        result = CollectionReportBuilder().write(ROOT, facts)
    except CollectionPreflightError as exc:
        print(json.dumps({
            "autonomous_collection_preflight": "FAIL",
            "state": "SAFE_STOP",
            "reasons": exc.reasons,
            "queue_status": exc.snapshot.get("status_counts", {}),
            "trading_actions": 0,
            "live_trading": "DISABLED",
        }, indent=2, sort_keys=True, default=str))
        return 2
    except (OSError, ValueError, CollectionReportError) as exc:
        print(json.dumps({"state": "SAFE_STOP", "error": f"{type(exc).__name__}: {exc}", "trading_actions": 0}, sort_keys=True))
        return 2
    print(json.dumps({
        "autonomous_collection": "PASS" if result["tim_autonomous_collection_ready"] else "PARTIAL",
        "collection_id": result["collection_id"],
        "data_quality": result["quality_status"],
        "decision_status": result["decision_status"],
        "management_traffic_light": result["management_traffic_light"],
        "report_dir": result["report_dir"],
        "result_hash": result["result_hash"],
        "tim_autonomous_collection_ready": "YES" if result["tim_autonomous_collection_ready"] else "NO",
        "trading_actions": 0,
        "live_trading": "DISABLED",
    }, indent=2, sort_keys=True))
    return 0 if result["tim_autonomous_collection_ready"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only TIM collection validation and decision report")
    parser.add_argument("--symbol", default=settings.symbol)
    parser.add_argument("--collection-id")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
