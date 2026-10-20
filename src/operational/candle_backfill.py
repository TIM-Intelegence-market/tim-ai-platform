"""Governed one-off rebuild of missing 1m candles from stored, ID-complete raw trades.

The history-recovery timer only repairs the last seven days. Older PARTIAL_WRITE gaps
(raw aggTrades present, 1m candle never written) need an explicit window and a recorded
governance decision before the rebuilt minutes may count for V2 readiness.

Every minute goes through ``rebuild_verified_minute``: it writes a candle only when the
raw trade IDs across both minute boundaries are complete. Nothing is synthesised,
forward-filled or fetched from outside. Each run writes a versioned manifest with one
proof per minute, so the backfill stays separately traceable from live-written candles.
OBSERVE only: no orders, no cursor or queue changes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.operational.history_recovery import rebuild_verified_minute

SCHEMA_VERSION = "1.0.0"
MAX_WINDOW_MINUTES = 43_200  # 30 days per run

MISSING_MINUTES_SQL = """
SELECT minute FROM generate_series($2::timestamptz, $3::timestamptz - interval '1 minute',
                                   interval '1 minute') AS minute
WHERE NOT EXISTS (
    SELECT 1 FROM candles c WHERE c.symbol=$1 AND c.timeframe='1m' AND c.open_time=minute
      AND c.closed=true AND c.close_time=minute+interval '1 minute'
      AND c.low <= LEAST(c.open,c.close) AND c.high >= GREATEST(c.open,c.close)
      AND c.low <= c.high AND c.volume >= 0 AND c.trade_count > 0)
ORDER BY minute
"""

CANDLE_SQL = """
SELECT open_time, close_time, open, high, low, close, volume, trade_count, closed
FROM candles WHERE symbol=$1 AND timeframe='1m' AND open_time=$2
"""


class _DryRunRollback(Exception):
    """Raised inside the per-minute transaction to discard a dry-run write."""


@dataclass(frozen=True)
class Governance:
    approved_by: str
    decision_ref: str
    approved_at_utc: str

    def validate(self) -> None:
        for name in ("approved_by", "decision_ref", "approved_at_utc"):
            if not getattr(self, name).strip():
                raise ValueError(f"governance field {name} is required for --apply")
        parse_utc(self.approved_at_utc)


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"timestamp must be UTC with trailing Z: {value!r}")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    return parsed.astimezone(timezone.utc)


def validate_window(start: datetime, end: datetime, now: datetime) -> None:
    for value in (start, end):
        if value.tzinfo is None or value.second or value.microsecond:
            raise ValueError("window bounds must be timezone-aware and minute-aligned")
    if end <= start:
        raise ValueError("window end must be after start")
    if (end - start) > timedelta(minutes=MAX_WINDOW_MINUTES):
        raise ValueError(f"window exceeds {MAX_WINDOW_MINUTES} minutes; split it into several runs")
    if end > now - timedelta(minutes=2):
        raise ValueError("window end must be settled (at least 2 minutes in the past)")


def candle_hash(row: Any) -> str:
    payload = {
        "open_time": row["open_time"].astimezone(timezone.utc).isoformat(),
        "close_time": row["close_time"].astimezone(timezone.utc).isoformat(),
        **{key: repr(float(row[key])) for key in ("open", "high", "low", "close", "volume")},
        "trade_count": int(row["trade_count"]),
        "closed": bool(row["closed"]),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def rebuild_one(connection: Any, symbol: str, minute: datetime, *, now: datetime, apply: bool) -> dict[str, Any]:
    """Rebuild one minute inside its own transaction; roll back unless ``apply``."""
    proof: dict[str, Any] = {"minute": minute.astimezone(timezone.utc).isoformat()}
    try:
        async with connection.transaction(isolation="repeatable_read"):
            prior = await connection.fetchrow(CANDLE_SQL, symbol, minute)
            proof["prior_row_hash"] = candle_hash(prior) if prior else None
            result = await rebuild_verified_minute(connection, symbol, minute, now=now)
            proof.update(result)
            if result["status"] == "REBUILT":
                proof["candle_hash"] = candle_hash(await connection.fetchrow(CANDLE_SQL, symbol, minute))
            if not apply:
                raise _DryRunRollback
    except _DryRunRollback:
        pass
    return proof


async def run_backfill(database: Any, symbol: str, start: datetime, end: datetime, *, now: datetime,
                       apply: bool, governance: Governance | None, code_hashes: dict[str, str]) -> dict[str, Any]:
    validate_window(start, end, now)
    if apply:
        if governance is None:
            raise ValueError("--apply requires a governance decision")
        governance.validate()
    async with database.acquire() as connection:
        missing = [row["minute"] for row in await connection.fetch(MISSING_MINUTES_SQL, symbol, start, end)]
        proofs = [await rebuild_one(connection, symbol, minute, now=now, apply=apply) for minute in missing]
        still_missing = len(await connection.fetch(MISSING_MINUTES_SQL, symbol, start, end))
    statuses: dict[str, int] = {}
    for proof in proofs:
        statuses[proof["status"]] = statuses.get(proof["status"], 0) + 1
    total = int((end - start) / timedelta(minutes=1))
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "TIM_1M_CANDLE_BACKFILL",
        "mode": "APPLY" if apply else "DRY_RUN",
        "trading_actions": 0,
        "source": "STORED_AUTHORITATIVE_AGGTRADES_ONLY",
        "synthetic_data": "NONE",
        "forward_fill": "NONE",
        "symbol": symbol,
        "window": {"start_utc": start.isoformat(), "end_utc": end.isoformat(), "minutes": total},
        "run_at_utc": now.isoformat(),
        "governance": None if governance is None else {
            "approved_by": governance.approved_by,
            "decision_ref": governance.decision_ref,
            "approved_at_utc": governance.approved_at_utc,
        },
        "code_hashes": code_hashes,
        "totals": {
            "missing_before": len(missing),
            "rebuilt": statuses.get("REBUILT", 0),
            "not_rebuilt": len(missing) - statuses.get("REBUILT", 0),
            "status_counts": statuses,
            "missing_after": still_missing,
        },
        "proofs": proofs,
    }
    body = json.dumps(manifest, sort_keys=True, default=str).encode()
    manifest["manifest_sha256"] = hashlib.sha256(body).hexdigest()
    return manifest
