#!/usr/bin/env python3
"""Finalize closed BTCUSDT 1-minute candles directly from persisted raw trades.

This is a fail-closed, raw-data-only latency guard for the live candle path.
It never synthesizes or forward-fills a candle: an empty raw minute produces no
row and is therefore visible to the coverage campaign.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.models.market_data import Candle


UTC = timezone.utc
ONE_MINUTE = timedelta(minutes=1)


def minute_floor(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(second=0, microsecond=0)


def closed_bounds(now: datetime, lookback_minutes: int) -> tuple[datetime, datetime]:
    if lookback_minutes < 1:
        raise ValueError("lookback_minutes must be positive")
    end = minute_floor(now)
    return end - timedelta(minutes=lookback_minutes), end


def candle_from_row(row: Any) -> Candle:
    open_time = row["open_time"].astimezone(UTC)
    return Candle(
        symbol=row["symbol"],
        timeframe="1m",
        open_time=open_time,
        close_time=open_time + ONE_MINUTE,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        trade_count=int(row["trade_count"]),
        closed=True,
    )


async def finalize(database_url: str, symbol: str, lookback_minutes: int, now: datetime | None = None) -> dict[str, object]:
    checked_at = now or datetime.now(UTC)
    start, end = closed_bounds(checked_at, lookback_minutes)
    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=60)
    transaction = connection.transaction()
    try:
        await transaction.start()
        rows = await connection.fetch(
            """WITH minutes AS (
                   SELECT generate_series($2::timestamptz, $3::timestamptz - interval '1 minute', interval '1 minute') AS open_time
               ), aggregate AS (
                   SELECT date_trunc('minute', trade_time) AS open_time,
                          (array_agg(price ORDER BY trade_time, aggregate_trade_id))[1] AS open,
                          max(price) AS high, min(price) AS low,
                          (array_agg(price ORDER BY trade_time DESC, aggregate_trade_id DESC))[1] AS close,
                          sum(quantity) AS volume, count(*) AS trade_count
                   FROM agg_trades
                   WHERE symbol=$1 AND trade_time >= $2 AND trade_time < $3
                   GROUP BY date_trunc('minute', trade_time)
               )
               SELECT $1 AS symbol, minutes.open_time, aggregate.open, aggregate.high, aggregate.low,
                      aggregate.close, aggregate.volume, aggregate.trade_count
               FROM minutes JOIN aggregate USING (open_time)
               ORDER BY minutes.open_time""",
            symbol, start, end,
        )
        candles = [candle_from_row(row) for row in rows]
        for candle in candles:
            await connection.execute(
                """INSERT INTO candles(symbol,timeframe,open_time,close_time,open,high,low,close,volume,trade_count,closed)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,true)
                   ON CONFLICT(symbol,timeframe,open_time) DO UPDATE SET
                     close_time=EXCLUDED.close_time,open=EXCLUDED.open,high=EXCLUDED.high,low=EXCLUDED.low,
                     close=EXCLUDED.close,volume=EXCLUDED.volume,trade_count=EXCLUDED.trade_count,closed=true""",
                candle.symbol, candle.timeframe, candle.open_time, candle.close_time,
                candle.open, candle.high, candle.low, candle.close, candle.volume, candle.trade_count,
            )
        await transaction.commit()
    except BaseException:
        await transaction.rollback()
        raise
    finally:
        await connection.close()
    return {
        "checked_at_utc": checked_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "window_start_utc": start.isoformat().replace("+00:00", "Z"),
        "window_end_utc": end.isoformat().replace("+00:00", "Z"),
        "raw_backed_closed_candles": len(candles),
        "symbol": symbol,
        "synthetic_data": False,
        "forward_fill": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--lookback-minutes", type=int, default=90)
    args = parser.parse_args()
    import json
    print(json.dumps(asyncio.run(finalize(args.database_url, args.symbol, args.lookback_minutes)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
