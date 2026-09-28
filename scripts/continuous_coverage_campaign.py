#!/usr/bin/env python3
"""Run an immutable, fail-closed 100% BTCUSDT 1-minute coverage campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT))

from config.settings import settings

UTC = timezone.utc
ONE_MINUTE = timedelta(minutes=1)
DEFAULT_DURATION_DAYS = 30
MAX_POWER_TELEMETRY_AGE = timedelta(seconds=180)


def utc_minute(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(second=0, microsecond=0)


def parse_utc_minute(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.second or parsed.microsecond:
        raise ValueError("timestamp must be aligned to a UTC minute")
    return utc_minute(parsed)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_once(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def declaration(start: datetime, end: datetime) -> dict[str, Any]:
    payload = {
        "schema_version": "1.0.0",
        "campaign_type": "TIM_100_PERCENT_CONTINUOUS_COVERAGE",
        "created_at_utc": iso(datetime.now(UTC)),
        "market": "BINANCE_SPOT",
        "instrument": "BTCUSDT",
        "timeframe": "1m",
        "window_start_utc": iso(start),
        "window_end_utc": iso(end),
        "target_coverage": "100.000%",
        "closed_candles_only": True,
        "forward_fill": "PROHIBITED",
        "synthetic_data": "PROHIBITED",
        "excluded_intervals": [],
        "failure_rule": "Any missing raw-trade minute or closed-candle minute after its close permanently fails this campaign.",
        "operational_failure_rule": "Missing, failed, malformed, or stale power-state telemetry permanently fails this campaign.",
        "trading_actions": 0,
    }
    return {**payload, "declaration_hash": digest(payload)}


def evaluated_end(start: datetime, end: datetime, now: datetime) -> datetime:
    """Do not judge the current minute before it and its candle can close."""
    safe_cutoff = utc_minute(now) - ONE_MINUTE
    return min(end, max(start, safe_cutoff))


def missing_minutes(start: datetime, end: datetime, present: set[datetime]) -> list[str]:
    cursor = start
    missing: list[str] = []
    while cursor < end:
        if cursor not in present:
            missing.append(iso(cursor))
        cursor += ONE_MINUTE
    return missing


def power_telemetry_status(path: Path, now: datetime) -> dict[str, object]:
    """Require a fresh, passing read-only proof that sleep protection is active."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed_at = datetime.fromisoformat(str(payload["observed_at_utc"]).replace("Z", "+00:00"))
        age = now - observed_at.astimezone(UTC)
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "FAIL", "reason": "MISSING_OR_MALFORMED"}
    if payload.get("status") != "PASS":
        return {"status": "FAIL", "reason": "TELEMETRY_REPORTED_FAILURE"}
    if age < timedelta(0) or age > MAX_POWER_TELEMETRY_AGE:
        return {"status": "FAIL", "reason": "STALE", "age_seconds": round(age.total_seconds(), 3)}
    return {"status": "PASS", "age_seconds": round(age.total_seconds(), 3)}


async def inspect(database_url: str, start: datetime, end: datetime) -> tuple[set[datetime], set[datetime]]:
    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=60)
    transaction = connection.transaction(isolation="repeatable_read", readonly=True)
    await transaction.start()
    try:
        candles = await connection.fetch(
            """SELECT DISTINCT open_time FROM candles
               WHERE symbol='BTCUSDT' AND timeframe='1m' AND closed=true
                 AND open_time >= $1 AND open_time < $2""",
            start, end,
        )
        raw = await connection.fetch(
            """SELECT DISTINCT date_trunc('minute', trade_time) AS minute
               FROM agg_trades WHERE symbol='BTCUSDT'
                 AND trade_time >= $1 AND trade_time < $2""",
            start, end,
        )
    finally:
        await transaction.rollback()
        await connection.close()
    return ({utc_minute(row["open_time"]) for row in candles}, {utc_minute(row["minute"]) for row in raw})


async def check(args: argparse.Namespace) -> int:
    campaign = json.loads(args.declaration.read_text(encoding="utf-8"))
    signed = {key: value for key, value in campaign.items() if key != "declaration_hash"}
    if campaign.get("declaration_hash") != digest(signed):
        raise RuntimeError("campaign declaration hash does not match")
    start = parse_utc_minute(campaign["window_start_utc"])
    end = parse_utc_minute(campaign["window_end_utc"])
    prior = json.loads(args.status.read_text(encoding="utf-8")) if args.status.exists() else {}
    if prior.get("state") == "FAILED_PERMANENT":
        print(json.dumps(prior, sort_keys=True))
        return 2
    now = datetime.now(UTC)
    power_telemetry = power_telemetry_status(args.power_status, now)
    checked_end = evaluated_end(start, end, now)
    candles, raw = await inspect(args.database_url, start, checked_end)
    missing_candles = missing_minutes(start, checked_end, candles)
    missing_raw = missing_minutes(start, checked_end, raw)
    complete = checked_end == end
    state = "FAILED_PERMANENT" if missing_candles or missing_raw or power_telemetry["status"] != "PASS" else "PASS" if complete else "RUNNING"
    expected = int((checked_end - start) / ONE_MINUTE)
    result = {
        "campaign_declaration_hash": campaign["declaration_hash"],
        "checked_at_utc": iso(datetime.now(UTC)),
        "checked_window_start_utc": iso(start),
        "checked_window_end_utc": iso(checked_end),
        "target_window_end_utc": iso(end),
        "expected_minutes": expected,
        "closed_candle_minutes": len(candles),
        "raw_trade_minutes": len(raw),
        "missing_closed_candle_minutes": missing_candles,
        "missing_raw_trade_minutes": missing_raw,
        "power_telemetry": power_telemetry,
        "coverage_percent": "100.000" if not missing_candles else f"{100 * (expected - len(missing_candles)) / max(1, expected):.3f}",
        "state": state,
        "trading_actions": 0,
    }
    atomic_write(args.status, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if state in {"RUNNING", "PASS"} else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--declaration", type=Path, default=ROOT / "artifacts/continuous_coverage/campaign.json")
    parser.add_argument("--status", type=Path, default=ROOT / "artifacts/continuous_coverage/status.json")
    parser.add_argument("--power-status", type=Path, default=ROOT / "data/operational/power_state_telemetry.json")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--start")
    parser.add_argument("--duration-days", type=int, default=DEFAULT_DURATION_DAYS)
    args = parser.parse_args()
    if args.initialize:
        if args.duration_days < 1:
            parser.error("--duration-days must be positive")
        start = parse_utc_minute(args.start) if args.start else utc_minute(datetime.now(UTC)) + ONE_MINUTE
        write_once(args.declaration, declaration(start, start + timedelta(days=args.duration_days)))
        print(json.dumps(json.loads(args.declaration.read_text()), sort_keys=True))
        return 0
    return asyncio.run(check(args))


if __name__ == "__main__":
    raise SystemExit(main())
