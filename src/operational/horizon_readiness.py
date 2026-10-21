"""Measured horizon inputs; these checks never grant trading qualification."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

HORIZON_MINUTES = {"SHORT": 5, "MID": 240, "LONG": 10080}


def horizon_bounds(now: datetime, minutes: int) -> tuple[datetime, datetime]:
    # Use the same settling allowance as the server's live gap check.
    end = now.astimezone(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=2)
    return end - timedelta(minutes=minutes), end


def evaluate_horizon(minutes: int, facts: dict[str, Any]) -> dict[str, Any]:
    count = facts.get("valid_minutes", 0)
    complete = type(count) is int and count == minutes
    features = {}
    if complete:
        try:
            first, last, high, low, volume = (float(facts[name]) for name in
                                             ("first_open", "last_close", "high", "low", "volume"))
            if not all(math.isfinite(value) for value in (first, last, high, low, volume)):
                raise ValueError("non-finite feature input")
            if min(first, last, high, low) <= 0 or high < max(first, last) or low > min(first, last) or volume < 0:
                raise ValueError("invalid candle aggregates")
            features = {"return_fraction": last / first - 1,
                        "range_fraction": high / low - 1, "volume": volume}
            if not all(math.isfinite(value) for value in features.values()):
                features = {}
        except (ValueError, TypeError, KeyError, OverflowError):
            pass
    return {
        "data": "PASS" if complete else "FAIL",
        "features": "PASS" if features else "UNAVAILABLE",
        "quality": "PASS" if complete and features else "FAIL",
        "qualification": "PENDING",
        "readiness": "BLOCKED",
        "valid_minutes": count, "expected_minutes": minutes,
        "missing_minutes": max(0, minutes - count) if type(count) is int else None,
        "measured_features": features,
        "quality_scope": "CLOSED_1M_CANDLE_CONTINUITY_AND_OHLC_VALIDITY",
        "qualification_reason": "No approved horizon-specific qualification evidence is recorded.",
        "activation_allowed": False,
    }


async def collect_horizons(connection: Any, symbol: str, now: datetime) -> dict[str, Any]:
    horizons = {}
    for name, minutes in HORIZON_MINUTES.items():
        start, end = horizon_bounds(now, minutes)
        rows = await connection.fetch(
            """SELECT open_time,open,high,low,close,volume FROM candles
               WHERE symbol=$1 AND timeframe='1m' AND closed=true
                 AND open_time >= $2 AND open_time < $3
                 AND open_time=date_trunc('minute',open_time)
                 AND close_time=open_time+interval '1 minute'
                 AND low <= LEAST(open,close) AND high >= GREATEST(open,close)
                 AND low <= high AND volume >= 0 AND trade_count > 0
               ORDER BY open_time""", symbol, start, end,
        )
        facts: dict[str, Any] = {"valid_minutes": len(rows)}
        if rows:
            facts.update(first_open=rows[0]["open"], last_close=rows[-1]["close"],
                         high=max(row["high"] for row in rows), low=min(row["low"] for row in rows),
                         volume=sum(row["volume"] for row in rows))
        horizons[name] = {**evaluate_horizon(minutes, facts),
                          "window_start_utc": start.isoformat(), "window_end_utc": end.isoformat()}
    return {
        "schema_version": "1.0.0", "checked_at": now.isoformat(), "status": "PASS",
        "symbol": symbol, "source": "POSTGRES_CLOSED_1M_CANDLES",
        "feature_version": "CANDLE_RETURN_RANGE_VOLUME_V1", "horizons": horizons,
        "mode": "OBSERVE", "trading_actions": 0,
        "limitation": "Measures candle inputs and descriptive features, not strategy validity or raw-trade completeness.",
    }
