"""Rebuild closed 1m candles for minutes whose CANDLE_V1 work was DEFERRED.

Dry run by default: prints the plan and changes nothing. ``--apply`` rebuilds
each eligible minute in its own transaction from persisted raw aggTrades and
marks that minute's DEFERRED outbox rows COMPLETED. Live queue, cursor, gap
ledger and follow-up stages are never written. Only public market data, no
trading action, OBSERVE only.

Exit codes: 0 every planned minute was rebuilt (or there was nothing to do),
2 minutes remain blocked or conflicted, 3 error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.data_ingestion.deferred_candles import rebuild_deferred_candles
from src.database.connection import Database


async def run(arguments: argparse.Namespace) -> tuple[int, dict]:
    database = None
    try:
        database = Database(arguments.database_url, min_size=1, max_size=1)
        await database.connect()
        async with database.acquire() as connection:
            report = await rebuild_deferred_candles(
                connection,
                arguments.symbol,
                apply=arguments.apply,
                safety_seconds=arguments.safety_seconds,
                max_minutes=arguments.max_minutes,
            )
        payload = report.as_dict()
        remaining = report.blocked_minutes + report.conflict_minutes
        payload["status"] = "PASS" if remaining == 0 else "MINUTES_REMAIN"
        if arguments.receipt_dir is not None and arguments.apply:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = arguments.receipt_dir / arguments.symbol / f"rebuild_{stamp}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            payload["receipt_path"] = str(target)
        return (0 if remaining == 0 else 2), payload
    except Exception as error:
        return 3, {
            "status": "ERROR",
            "mode": "OBSERVE",
            "trading_actions": 0,
            "error_type": type(error).__name__,
            "error": str(error),
        }
    finally:
        if database is not None:
            await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", default=None, help="defaults to the configured runtime database")
    parser.add_argument("--symbol", default=settings.symbol.upper())
    parser.add_argument("--apply", action="store_true", help="write candles and complete DEFERRED rows (default: dry run)")
    parser.add_argument("--max-minutes", type=int, default=500, help="oldest-first bound per run (1..10000)")
    parser.add_argument("--safety-seconds", type=int, default=120, help="keep this far away from the live minute")
    parser.add_argument("--receipt-dir", type=Path, default=Path("data/deferred_candle_rebuild"),
                        help="where an --apply run writes its JSON receipt; pass '' to skip")
    arguments = parser.parse_args()
    if not 1 <= arguments.max_minutes <= 10_000:
        parser.error("--max-minutes must be between 1 and 10000")
    if arguments.safety_seconds < 0:
        parser.error("--safety-seconds must not be negative")
    if arguments.database_url is None:
        arguments.database_url = settings.database_url
    if str(arguments.receipt_dir) in {"", "."}:
        arguments.receipt_dir = None
    code, payload = asyncio.run(run(arguments))
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
