"""Read-only market rows for the AI context from TIM's Postgres (same safety as src/ops_mcp/coverage.py).

The DSN comes from the environment and should name a SELECT-only role. The session is opened
read-only and refused if it does not report itself as read-only. Only candles that closed at or
before the cutoff are read; delta comes from agg_trades of the same window (taker buy minus sell).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from src.database.safety import guard_database_connection
from src.research_lab.ki_filter.context import TIMEFRAME_MINUTES

READ_ONLY_SETTINGS = {"default_transaction_read_only": "on"}
CANDLES_BACK = 24
DELTA_TIMEFRAMES = {"15m", "1h"}  # 1d would scan weeks of trades
SELECT_CANDLES = (
    "SELECT open_time, open, high, low, close, volume FROM candles WHERE symbol=$1 AND timeframe=$2 AND closed "
    "AND open_time >= $3 AND open_time + $4::interval <= $5 ORDER BY open_time")
SELECT_DELTA = (
    "SELECT date_bin($1::interval, trade_time, TIMESTAMPTZ '1970-01-01') AS open_time, "
    "SUM(CASE WHEN buyer_is_maker THEN -quantity ELSE quantity END) AS delta "
    "FROM agg_trades WHERE symbol=$2 AND trade_time >= $3 AND trade_time < $4 GROUP BY 1")


class MarketError(Exception):
    pass


class MarketReader:
    def __init__(self, dsn: str | None, connect: Callable[..., Awaitable[Any]] | None = None) -> None:
        self.dsn = dsn or None
        self._connect = connect

    @property
    def configured(self) -> bool:
        return self.dsn is not None

    def candles(self, symbol: str, timeframe: str, cutoff: datetime, back: int = CANDLES_BACK) -> list[dict[str, Any]]:
        if self.dsn is None:
            return []
        if timeframe not in TIMEFRAME_MINUTES or not 1 <= back <= 200:
            raise MarketError("invalid market request")
        try:
            guard_database_connection(self.dsn)
        except Exception:
            raise MarketError("market database rejected by safety guard") from None
        return asyncio.run(self._read(symbol, timeframe, cutoff, back))

    async def _read(self, symbol: str, timeframe: str, cutoff: datetime, back: int) -> list[dict[str, Any]]:
        connect = self._connect
        if connect is None:
            import asyncpg
            connect = asyncpg.connect
        step = timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
        start = cutoff - step * back
        try:
            connection = await connect(self.dsn, timeout=5, command_timeout=30,
                                       server_settings=dict(READ_ONLY_SETTINGS))
        except Exception as error:
            raise MarketError(f"market database unreachable: {type(error).__name__}") from None
        try:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                if await connection.fetchval("SHOW default_transaction_read_only") != "on":
                    raise MarketError("market session is not read-only")
                rows = await connection.fetch(SELECT_CANDLES, symbol, timeframe, start, step, cutoff)
                deltas = {}
                if timeframe in DELTA_TIMEFRAMES and rows:
                    end = min(cutoff, rows[-1]["open_time"] + step)
                    for row in await connection.fetch(SELECT_DELTA, step, symbol, start, end):
                        deltas[row["open_time"]] = float(row["delta"])
        except MarketError:
            raise
        except Exception as error:
            raise MarketError(f"market query failed: {type(error).__name__}") from None
        finally:
            await connection.close()
        return [{"open_time": row["open_time"], "open": row["open"], "high": row["high"], "low": row["low"],
                 "close": row["close"], "volume": row["volume"], "delta": deltas.get(row["open_time"])}
                for row in rows]
