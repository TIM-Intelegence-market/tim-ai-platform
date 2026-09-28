#!/usr/bin/env python3
"""Independently finalize a sealed TIM 100% coverage campaign after its end."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from scripts.continuous_coverage_campaign import digest, inspect, iso, missing_minutes, parse_utc_minute


async def finalize(args: argparse.Namespace) -> int:
    declaration = json.loads(args.declaration.read_text(encoding="utf-8"))
    signed = {key: value for key, value in declaration.items() if key != "declaration_hash"}
    if declaration.get("declaration_hash") != digest(signed):
        raise RuntimeError("campaign declaration hash does not match")
    start = parse_utc_minute(declaration["window_start_utc"])
    end = parse_utc_minute(declaration["window_end_utc"])
    now = datetime.now(timezone.utc)
    if now < end:
        print(json.dumps({"status": "NOT_DUE", "window_end_utc": iso(end), "now_utc": iso(now)}))
        return 2
    hashes = []
    evidence = None
    for _ in range(10):
        candles, raw = await inspect(args.database_url, start, end)
        result = {
            "expected_minutes": int((end - start).total_seconds() / 60),
            "closed_candle_minutes": len(candles),
            "raw_trade_minutes": len(raw),
            "missing_closed_candle_minutes": missing_minutes(start, end, candles),
            "missing_raw_trade_minutes": missing_minutes(start, end, raw),
        }
        hashes.append(hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest())
        evidence = result
    assert evidence is not None
    passed = (
        len(set(hashes)) == 1
        and not evidence["missing_closed_candle_minutes"]
        and not evidence["missing_raw_trade_minutes"]
    )
    report = {
        "schema_version": "1.0.0",
        "campaign_declaration_hash": declaration["declaration_hash"],
        "finalized_at_utc": iso(now),
        "repeat_count": 10,
        "repeat_hashes": hashes,
        "deterministic": len(set(hashes)) == 1,
        "status": "PASS" if passed else "FAIL",
        "evidence": evidence,
        "trading_actions": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"status": report["status"], "deterministic": report["deterministic"], "output": str(args.output)}))
    return 0 if passed else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=settings.database_url)
    parser.add_argument("--declaration", type=Path, default=ROOT / "artifacts/continuous_coverage/campaign_20260923T0951Z.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/continuous_coverage/final_20260923T0951Z.json")
    return asyncio.run(finalize(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
