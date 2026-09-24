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

    now = utc_minute(datetime.now(UTC))
    window_end = now
    window_start = window_end - timedelta(minutes=WINDOW_MINUTES)
    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=60)
    transaction = connection.transaction(isolation="repeatable_read", readonly=True)
    await transaction.start()
    try:
        rows = await connection.fetch(
            """SELECT DISTINCT open_time FROM candles
               WHERE symbol='BTCUSDT' AND timeframe='1m' AND closed=true
                 AND open_time >= $1 AND open_time < $2""",
            window_start, window_end,
        )
    finally:
        await transaction.rollback()
        await connection.close()
    valid_minutes = len(rows)
    coverage = valid_minutes / WINDOW_MINUTES
    return {
        "schema_version": "1.0.0",
        "calculation_method": "PRODUCT_EXPECTED_SET_V1",
        "closed_only": True,
        "data_type": "CLOSED_1M_CANDLE_DERIVED_FROM_AGGTRADE",
        "expected_interval": "PT1M",
        "window_start_utc": iso(window_start),
        "window_end_utc": iso(window_end),
        "coverage": round(coverage, 5),
        "coverage_percent": f"{coverage * 100:.3f}",
        "valid_observations": valid_minutes,
        "expected_observations": WINDOW_MINUTES,
        "status": "PASS" if valid_minutes == WINDOW_MINUTES else "FAIL",
        "computed_at_utc": iso(datetime.now(UTC)),
        "source": "postgres://candles(BTCUSDT,1m,closed)",
        "trading_actions": 0,
    }


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
