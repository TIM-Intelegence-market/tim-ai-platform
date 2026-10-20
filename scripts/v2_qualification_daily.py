#!/usr/bin/env python3
"""Write one immutable qualification manifest per complete UTC day since the campaign start.

Run by tim-qualification-daily.timer as user ``tim``. Read-only against PostgreSQL. Catches
up on missed days, never rewrites an existing manifest, and exits 0 with NOT_ACTIVE when no
campaign has been started.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.campaign import daily_metrics, day_window, pending_days
from src.v2_completion.qualification import build_daily_manifest, write_immutable_json
from src.v2_completion.start_gate_checks import (
    check_postgresql_security,
    parse_time,
    read_json,
)

DEFAULT_DIR = ROOT / "data/qualification"


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def collect_day(campaign_start: datetime, window_end: datetime, symbol: str) -> tuple[dict, dict]:
    from config.settings import settings
    from scripts.v2_readiness_audit import collect
    from scripts.v2_start_gates_check import database_evidence, run

    audit = await collect(argparse.Namespace(start=iso(campaign_start), end=iso(window_end), downtime_evidence=None,
                                             database_url=settings.database_url, case_from=campaign_start))
    db = await database_evidence(symbol)
    security = check_postgresql_security(run(["ss", "-ltnH"]), db.get("listen_addresses")).to_dict()
    return audit, {"security": {"status": security["status"], "reasons": security["reasons"],
                                "listeners": security["evidence"].get("listeners")},
                   "open_gaps": db.get("open_gaps")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args(argv)
    campaign = read_json(args.dir / "qualification_campaign.json")
    if campaign is None or campaign.get("campaign_status") != "ACTIVE":
        print(json.dumps({"status": "NOT_ACTIVE", "manifests_written": 0}))
        return 0
    start = parse_time(campaign["start_utc"])
    daily_dir = args.dir / "daily"
    written = {path.stem for path in daily_dir.glob("*.json")} if daily_dir.exists() else set()
    results = []
    for day in pending_days(start, datetime.now(UTC), written):
        window = day_window(start, day)
        audit, live = asyncio.run(collect_day(start, window[1], args.symbol.upper()))
        metrics = daily_metrics(day=day, window=window, coverage=audit["coverage"], gaps=audit["gaps"],
                                cases=audit["cases"]["current_cutoff_audit"],
                                health=read_json(ROOT / "data/operational/server_health.json"),
                                security=live["security"], open_gap_incidents=live["open_gaps"])
        manifest = build_daily_manifest(campaign, day=window[0], metrics=metrics)
        status = write_immutable_json(daily_dir / f"{day.isoformat()}.json", manifest)
        results.append({"day": day.isoformat(), "status": status, "coverage": metrics["coverage"],
                        "gaps": metrics["gap_count"], "independent_cases": metrics["independent_case_count"],
                        "security": metrics["security_status"]["status"]})
    print(json.dumps({"status": "ACTIVE", "start_utc": campaign["start_utc"], "manifests": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
