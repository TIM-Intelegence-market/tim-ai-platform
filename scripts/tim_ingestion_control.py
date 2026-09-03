from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.data_ingestion.control import IngestionControl
from src.data_ingestion.durable import DurableIngestionStore
from src.database.connection import Database


async def run(command: str, symbol: str, timeout: float) -> tuple[int, dict]:
    database = None
    try:
        database = Database(settings.database_url, min_size=1, max_size=2)
        await database.connect()
        schema_evidence = None
        if command == "bootstrap":
            async with database.acquire() as connection:
                raw_table_exists = await connection.fetchval("SELECT to_regclass('public.agg_trades') IS NOT NULL")
            schema_path = (
                ROOT / "src/database/migrations/004_durable_ingestion.sql"
                if raw_table_exists
                else ROOT / "src/database/schema.sql"
            )
            schema_bytes = schema_path.read_bytes()
            await database.initialize_schema(schema_path)
            schema_evidence = {
                "status": "PASS",
                "path": str(schema_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(schema_bytes).hexdigest(),
                "existing_raw_table": bool(raw_table_exists),
            }
        control = IngestionControl(DurableIngestionStore(database), symbol)
        if command == "bootstrap":
            await control.store.bootstrap_cursor(symbol)
        report = await control.checkpoint(timeout) if command == "checkpoint" else await control.status()
        if schema_evidence is not None:
            report["schema_bootstrap"] = schema_evidence
        passed = report.get("checkpoint_safe", report.get("cursor_valid", False))
        return (0 if passed else 2), report
    except Exception as error:
        return 3, {
            "mode": "OBSERVE",
            "trading_actions": 0,
            "status": "ERROR",
            "error_type": type(error).__name__,
            "error": str(error),
        }
    finally:
        if database is not None:
            await database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="TIM durable-ingestion checkpoint/status")
    parser.add_argument("command", choices=("status", "bootstrap", "checkpoint"))
    parser.add_argument("--symbol", default=settings.symbol)
    parser.add_argument("--timeout", type=float, default=30.0)
    arguments = parser.parse_args()
    code, report = asyncio.run(run(arguments.command, arguments.symbol.upper(), arguments.timeout))
    print(json.dumps(report, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
