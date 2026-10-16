"""Evidence the running runtime measures itself, so the dashboard never has to
fall back to weeks-old audit files for states that can be checked live.

Read-only against the database: one bounded SELECT for the rolling 24h
coverage room and one ``SHOW`` for the PostgreSQL listener. No writes to the
database, no network probes, no secrets.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
WINDOW_MINUTES = 1440
LOOPBACK_ADDRESSES = frozenset({"localhost", "127.0.0.1", "::1"})


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def rolling_liveness_record(open_times: list[datetime], window_start: datetime, window_end: datetime, computed_at: datetime) -> dict[str, Any]:
    """Coverage room for closed 1m candles in [window_start, window_end)."""
    valid = len({value for value in open_times if window_start <= value < window_end})
    coverage = valid / WINDOW_MINUTES
    return {
        "schema_version": "1.0.0",
        "calculation_method": "PRODUCT_EXPECTED_SET_V1",
        "closed_only": True,
        "data_type": "CLOSED_1M_CANDLE_DERIVED_FROM_AGGTRADE",
        "expected_interval": "PT1M",
        "window_start_utc": _iso(window_start),
        "window_end_utc": _iso(window_end),
        "coverage": round(coverage, 5),
        "coverage_percent": f"{coverage * 100:.3f}",
        "valid_observations": valid,
        "expected_observations": WINDOW_MINUTES,
        "status": "PASS" if valid == WINDOW_MINUTES else "FAIL",
        "computed_at_utc": _iso(computed_at),
        "source": "postgres://candles(BTCUSDT,1m,closed)",
        "trading_actions": 0,
    }


async def compute_rolling_liveness(connection: Any, symbol: str = "BTCUSDT", now: datetime | None = None) -> dict[str, Any]:
    """Count distinct closed 1m candles in the last 24h on an open connection."""
    computed_at = now or datetime.now(UTC)
    window_end = computed_at.astimezone(UTC).replace(second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=WINDOW_MINUTES)
    rows = await connection.fetch(
        """SELECT DISTINCT open_time FROM candles
           WHERE symbol=$1 AND timeframe='1m' AND closed=true
             AND open_time >= $2 AND open_time < $3""",
        symbol, window_start, window_end,
    )
    return rolling_liveness_record([row["open_time"] for row in rows], window_start, window_end, computed_at)


def listener_record(listen_addresses: str, port: Any, checked_at: datetime) -> dict[str, Any]:
    """PASS only when PostgreSQL listens on loopback addresses alone."""
    addresses = [part.strip() for part in str(listen_addresses).split(",") if part.strip()]
    exposed = [address for address in addresses if address not in LOOPBACK_ADDRESSES]
    return {
        "listen_addresses": ",".join(addresses) or "(none)",
        "port": port,
        "status": "FAIL" if exposed else "PASS",
        "exposed_addresses": exposed,
        "checked_at_utc": _iso(checked_at),
        "source": "runtime: SHOW listen_addresses",
    }


async def check_listener(connection: Any, now: datetime | None = None) -> dict[str, Any]:
    listen = await connection.fetchval("SHOW listen_addresses")
    port = await connection.fetchval("SHOW port")
    return listener_record(listen, port, now or datetime.now(UTC))


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
