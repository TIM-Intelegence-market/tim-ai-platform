#!/usr/bin/env python3
"""Pre-register and evaluate the prospective coverage window for the TIM server.

declare   write docs/autonomous_trader/campaigns/debian_campaign_<start>.json before the
          window starts; commit it, then its commit time proves it predates the data.
evaluate  measure closed 1m candle coverage inside a declared window (read-only).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc
CAMPAIGN_DIR = ROOT / "docs/autonomous_trader/campaigns"
SCHEMA_VERSION = "1.0.0"
# Step 2 of the operating plan: >= 99.5 % coverage, no unexplained gaps.
DEFAULT_TARGET_PERCENT = 99.5
DEFAULT_DAYS = 14
# The window may not start before this lead time, so the declaration is committed first.
MIN_LEAD = timedelta(hours=1)


class CampaignError(ValueError):
    pass


def parse_minute(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CampaignError(f"not an ISO timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise CampaignError("timestamp needs an explicit UTC offset")
    parsed = parsed.astimezone(UTC)
    if parsed.second or parsed.microsecond:
        raise CampaignError("window boundaries must be whole UTC minutes")
    return parsed


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                              check=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise CampaignError("git commit unavailable") from exc


def build_declaration(*, start: datetime, days: int, target_percent: float, host_id: str, symbol: str,
                      commit: str, now: datetime) -> dict[str, Any]:
    if start - now < MIN_LEAD:
        raise CampaignError(f"window must start at least {MIN_LEAD} after now")
    if not 1 <= days <= 90:
        raise CampaignError("days must be between 1 and 90")
    if not 90.0 <= target_percent <= 100.0:
        raise CampaignError("target must be between 90 and 100 percent")
    if not host_id.strip():
        raise CampaignError("host id required")
    end = start + timedelta(days=days)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "TIM_DEBIAN_PROSPECTIVE_COVERAGE_WINDOW",
        "declared_at": iso(now),
        "window_start": iso(start),
        "window_end": iso(end),
        "expected_minutes": int((end - start).total_seconds() // 60),
        "symbol": symbol,
        "timeframe": "1m",
        "measure": "distinct closed 1m candles with open_time in [window_start, window_end)",
        "target_coverage_percent": target_percent,
        "host_id": host_id.strip(),
        "code_commit": commit,
        "mode": "OBSERVE",
        "trading_actions": 0,
    }


def declaration_path(declaration: dict[str, Any]) -> Path:
    start = parse_minute(declaration["window_start"])
    return CAMPAIGN_DIR / f"debian_campaign_{start.strftime('%Y%m%dT%H%MZ')}.json"


def coverage(declaration: dict[str, Any], present: set[datetime], now: datetime) -> dict[str, Any]:
    start, end = parse_minute(declaration["window_start"]), parse_minute(declaration["window_end"])
    measured_end = min(end, now.astimezone(UTC).replace(second=0, microsecond=0))
    expected: list[datetime] = []
    cursor = start
    while cursor < measured_end:
        expected.append(cursor)
        cursor += timedelta(minutes=1)
    missing = [minute for minute in expected if minute not in present]
    observed = len(expected) - len(missing)
    percent = round(100.0 * observed / len(expected), 4) if expected else 0.0
    complete = measured_end >= end
    target = float(declaration["target_coverage_percent"])
    if not expected:
        status = "NOT_STARTED"
    elif not complete:
        status = "RUNNING"
    else:
        status = "PASS" if percent >= target else "FAIL"
    return {
        "status": status,
        "window_start": iso(start),
        "window_end": iso(end),
        "measured_until": iso(measured_end),
        "expected_minutes": len(expected),
        "observed_minutes": observed,
        "missing_minutes": len(missing),
        "coverage_percent": percent,
        "target_coverage_percent": target,
        "missing_ranges": ranges(missing)[:50],
    }


def ranges(minutes: list[datetime]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for minute in minutes:
        if result and parse_minute(result[-1]["last"]) + timedelta(minutes=1) == minute:
            result[-1]["last"] = iso(minute)
            result[-1]["minutes"] += 1
        else:
            result.append({"first": iso(minute), "last": iso(minute), "minutes": 1})
    return result


async def present_minutes(database_url: str, symbol: str, start: datetime, end: datetime) -> set[datetime]:
    import asyncpg

    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=300)
    try:
        rows = await connection.fetch(
            """SELECT DISTINCT open_time FROM candles
               WHERE symbol=$1 AND timeframe='1m' AND closed=true AND open_time >= $2 AND open_time < $3""",
            symbol, start, end,
        )
    finally:
        await connection.close()
    return {row["open_time"].astimezone(UTC) for row in rows}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TIM server coverage window (OBSERVE only)")
    sub = parser.add_subparsers(dest="command", required=True)
    declare = sub.add_parser("declare")
    declare.add_argument("--start", required=True, help="UTC minute, e.g. 2026-10-05T00:00Z")
    declare.add_argument("--days", type=int, default=DEFAULT_DAYS)
    declare.add_argument("--target", type=float, default=DEFAULT_TARGET_PERCENT)
    declare.add_argument("--host-id", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--declaration", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "declare":
            from config.settings import settings

            declaration = build_declaration(start=parse_minute(args.start), days=args.days, target_percent=args.target,
                                            host_id=args.host_id, symbol=settings.symbol, commit=git_commit(),
                                            now=datetime.now(UTC))
            path = declaration_path(declaration)
            if path.exists():
                raise CampaignError(f"{path.name} already exists; a declaration is never overwritten")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(declaration, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            payload = {"status": "DECLARED", "path": str(path.relative_to(ROOT)),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "next_step": "commit and push this file before window_start"}
        else:
            from config.settings import settings

            declaration = json.loads(args.declaration.read_text(encoding="utf-8"))
            start, end = parse_minute(declaration["window_start"]), parse_minute(declaration["window_end"])
            present = asyncio.run(present_minutes(settings.database_url, declaration["symbol"], start, end))
            payload = coverage(declaration, present, datetime.now(UTC))
    except (CampaignError, OSError, KeyError, ValueError) as exc:
        payload = {"status": "BLOCKED", "reason": str(exc)}
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] in {"DECLARED", "PASS", "RUNNING", "NOT_STARTED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
