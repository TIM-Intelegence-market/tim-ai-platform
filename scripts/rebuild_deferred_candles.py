"""Rebuild closed 1m candles offline from persisted raw aggTrades.

Two scopes, dry run by default (prints the plan and changes nothing):

- ``--scope deferred`` (default): minutes whose CANDLE_V1 outbox rows are
  DEFERRED. ``--apply`` rebuilds each eligible minute in its own transaction
  and marks that minute's DEFERRED rows COMPLETED.
- ``--scope uncandled --from <ISO> [--to <ISO>]``: closed minutes in the window
  that have raw trades but no closed 1m candle and no outbox work at all (for
  example promoted offline candidates). ``--apply`` writes the candle only.

Live queue, cursor, gap ledger and follow-up stages are never written. Only
public market data, no trading action, OBSERVE only.

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
from src.data_ingestion.deferred_candles import rebuild_deferred_candles, rebuild_uncandled_candles
from src.database.connection import Database


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("window bounds must carry a timezone, e.g. 2026-10-01T00:00:00Z")
    return parsed.astimezone(timezone.utc)


async def run(arguments: argparse.Namespace) -> tuple[int, dict]:
    database = None
    try:
        database = Database(arguments.database_url, min_size=1, max_size=1)
        await database.connect()
        async with database.acquire() as connection:
            if arguments.scope == "deferred":
                report = await rebuild_deferred_candles(
                    connection,
                    arguments.symbol,
                    apply=arguments.apply,
                    safety_seconds=arguments.safety_seconds,
                    max_minutes=arguments.max_minutes,
                )
            else:
                report = await rebuild_uncandled_candles(
                    connection,
                    arguments.symbol,
                    apply=arguments.apply,
                    window_start=arguments.window_start,
                    window_end=arguments.window_end,
                    safety_seconds=arguments.safety_seconds,
                    max_minutes=arguments.max_minutes,
                )
        payload = report.as_dict()
        remaining = report.blocked_minutes + report.conflict_minutes
        payload["status"] = "PASS" if remaining == 0 else "MINUTES_REMAIN"
        if arguments.receipt_dir is not None and arguments.apply:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = arguments.receipt_dir / arguments.symbol / f"rebuild_{arguments.scope}_{stamp}.json"
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
    parser.add_argument("--scope", choices=("deferred", "uncandled"), default="deferred")
    parser.add_argument("--from", dest="window_start", type=parse_utc, default=None,
                        help="uncandled scope: window start (ISO 8601 with timezone), required")
    parser.add_argument("--to", dest="window_end", type=parse_utc, default=None,
                        help="uncandled scope: window end (exclusive); default is the last closed minute")
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
    if arguments.scope == "uncandled" and arguments.window_start is None:
        parser.error("--scope uncandled needs --from")
    if arguments.scope == "deferred" and (arguments.window_start or arguments.window_end):
        parser.error("--from/--to apply to --scope uncandled only")
    if arguments.window_end is not None and arguments.window_start is not None and arguments.window_end <= arguments.window_start:
        parser.error("--to must be after --from")
    if arguments.database_url is None:
        arguments.database_url = settings.database_url
    if str(arguments.receipt_dir) in {"", "."}:
        arguments.receipt_dir = None
    code, payload = asyncio.run(run(arguments))
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
