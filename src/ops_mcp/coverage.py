"""Read-only data coverage from TIM's Postgres for the tim-ops MCP server (#152 M3b).

The DSN comes only from the environment (TIM_OPS_COVERAGE_DSN) and should
name a role that may only SELECT (docs/ops_mcp/README.md). On top of that
the session is opened with default_transaction_read_only, every read runs in
a read-only transaction, and a session that does not report itself as
read-only is refused before any table is touched. Only candle open times are
read, never prices or volumes; gap incidents are listed with redacted text.
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Awaitable, Callable

from src.database.safety import guard_database_connection
from src.graph_mcp.redaction import redact_text
from src.ops_mcp.readers import SourceError, bounded

UTC = timezone.utc
TIMEFRAMES = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}
MAX_HOURS = 168
TARGET = Decimal("0.95")
SYMBOL = re.compile(r"^[A-Z0-9]{2,20}$")
READ_ONLY_SETTINGS = {"default_transaction_read_only": "on"}

READ_ONLY_CHECK = "SHOW default_transaction_read_only"
NOW = "SELECT clock_timestamp()"
SELECT_CANDLE_TIMES = (
    "SELECT open_time FROM candles WHERE symbol=$1 AND timeframe=$2 AND closed "
    "AND open_time >= $3 AND open_time < $4 ORDER BY open_time")
SELECT_OPEN_GAPS = (
    "SELECT gap_id, status, reason, gap_started_at, gap_ended_at, detected_at "
    "FROM ingestion_gap_incidents WHERE symbol=$1 AND status IN ('OPEN','CATCHING_UP') "
    "ORDER BY detected_at, gap_id LIMIT $2")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _floor(value: datetime, step: timedelta) -> datetime:
    value = value.astimezone(UTC)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return epoch + ((value - epoch) // step) * step


def _missing_ranges(expected: list[datetime], present: set[datetime],
                    step: timedelta) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for moment in expected:
        if moment in present:
            continue
        last = ranges[-1] if ranges else None
        if last and last["_to"] + step == moment:
            last["_to"], last["candles"] = moment, last["candles"] + 1
        else:
            ranges.append({"_from": moment, "_to": moment, "candles": 1})
    return [{"from": _iso(r["_from"]), "to": _iso(r["_to"]), "candles": r["candles"]}
            for r in ranges]


class CoverageReader:
    def __init__(self, dsn: str | None,
                 connect: Callable[..., Awaitable[Any]] | None = None) -> None:
        self.dsn = dsn or None
        self._connect = connect

    @property
    def configured(self) -> bool:
        return self.dsn is not None

    def coverage(self, symbol: str = "BTCUSDT", timeframe: str = "1m", hours: int = 24,
                 limit: int | None = None) -> dict[str, Any]:
        if self.dsn is None:
            return {"status": "not_configured", "hint": "set TIM_OPS_COVERAGE_DSN"}
        if not SYMBOL.fullmatch(symbol) or timeframe not in TIMEFRAMES \
                or not 1 <= hours <= MAX_HOURS:
            raise SourceError("invalid coverage request")
        try:
            guard_database_connection(self.dsn)
        except Exception:
            raise SourceError("coverage database rejected by safety guard") from None
        return asyncio.run(self._read(symbol, timeframe, hours, bounded(limit)))

    async def _read(self, symbol: str, timeframe: str, hours: int,
                    limit: int) -> dict[str, Any]:
        connect = self._connect
        if connect is None:
            import asyncpg
            connect = asyncpg.connect
        try:
            connection = await connect(self.dsn, timeout=5, command_timeout=30,
                                       server_settings=dict(READ_ONLY_SETTINGS))
        except Exception as error:
            raise SourceError(f"coverage database unreachable: {type(error).__name__}") from None
        try:
            async with connection.transaction(isolation="repeatable_read", readonly=True):
                if await connection.fetchval(READ_ONLY_CHECK) != "on":
                    raise SourceError("coverage session is not read-only")
                step = timedelta(minutes=TIMEFRAMES[timeframe])
                end = _floor(await connection.fetchval(NOW), step)
                start = end - timedelta(hours=hours)
                rows = await connection.fetch(SELECT_CANDLE_TIMES, symbol, timeframe, start, end)
                gaps = await connection.fetch(SELECT_OPEN_GAPS, symbol, limit + 1)
        except SourceError:
            raise
        except Exception as error:
            raise SourceError(f"coverage query failed: {type(error).__name__}") from None
        finally:
            await connection.close()
        expected = [start + i * step for i in range((end - start) // step)]
        present = {row["open_time"].astimezone(UTC) for row in rows} & set(expected)
        ratio = (Decimal(len(present)) / Decimal(len(expected))).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
        missing = _missing_ranges(expected, present, step)
        incidents = [{"gap_id": g["gap_id"], "status": g["status"],
                      "reason": redact_text(g["reason"] or ""),
                      "gap_started_at": _iso(g["gap_started_at"]),
                      "gap_ended_at": _iso(g["gap_ended_at"]),
                      "detected_at": _iso(g["detected_at"])} for g in gaps[:limit]]
        return {"status": "ok", "read_only_session": True, "symbol": symbol,
                "timeframe": timeframe, "window_start": _iso(start), "window_end": _iso(end),
                "expected": len(expected), "observed": len(present), "coverage": str(ratio),
                "target": str(TARGET), "meets_target": ratio >= TARGET,
                "missing_ranges": missing[:limit], "missing_truncated": len(missing) > limit,
                "open_incidents": incidents, "incidents_truncated": len(gaps) > limit}
