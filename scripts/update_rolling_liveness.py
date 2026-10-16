#!/usr/bin/env python3
"""Refresh the rolling 24h liveness evidence room from persisted candles.

Deterministic, read-only against the database: counts distinct closed 1m
candles in the last PT1440M window and writes the bounded evidence file the
control-center dashboard renders as the "Rolling Liveness" coverage room.
The legacy August baseline snapshot stays untouched as the fallback source.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from config.settings import settings

UTC = timezone.utc
WINDOW_MINUTES = 1440


def utc_minute(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(second=0, microsecond=0)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


async def compute(database_url: str) -> dict:
    import asyncpg

    from src.operational.live_evidence import compute_rolling_liveness

    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=60)
    transaction = connection.transaction(isolation="repeatable_read", readonly=True)
    await transaction.start()
    try:
        return await compute_rolling_liveness(connection, "BTCUSDT")
    finally:
        await transaction.rollback()
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--output", type=Path, default=ROOT / "data/operational/rolling_liveness.json")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay-seconds", type=float, default=5.0)
    args = parser.parse_args()
    # Bounded retries for transient DB timeouts: a stale evidence file is
    # worse than a late one, but retries must stay bounded so a dead
    # database still surfaces as a launchd failure, not silence.
    last_error: Exception | None = None
    for attempt in range(max(1, args.retries)):
        try:
            result = asyncio.run(compute(args.database_url))
            break
        except (TimeoutError, asyncio.TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < max(1, args.retries):
                time.sleep(args.retry_delay_seconds)
    else:
        raise last_error  # type: ignore[misc]
    atomic_write(args.output, result)
    print(json.dumps({"output": str(args.output), "status": result["status"], "coverage_percent": result["coverage_percent"]}))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
