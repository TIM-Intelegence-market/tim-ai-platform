#!/usr/bin/env python3
"""Seal hashes of the implementation used by the active coverage campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=ROOT / "artifacts/continuous_coverage/campaign_20260923T0951Z.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/continuous_coverage/implementation_20260923T0951Z.json")
    args = parser.parse_args()
    files = {
        "campaign": args.campaign.resolve(),
        "campaign_checker": ROOT / "scripts/continuous_coverage_campaign.py",
        "finalizer": ROOT / "scripts/finalize_continuous_coverage.py",
        "launch_agent": ROOT / "ops/launchd/com.tim.continuous-coverage.plist",
        "integrity_guard": ROOT / "scripts/continuous_coverage_integrity_guard.py",
        "integrity_guard_agent": ROOT / "ops/launchd/com.tim.continuous-coverage-integrity.plist",
        "raw_candle_finalizer": ROOT / "scripts/finalize_closed_1m_candles.py",
        "raw_candle_finalizer_agent": ROOT / "ops/launchd/com.tim.closed-candle-finalizer.plist",
        "power_state_telemetry": ROOT / "scripts/tim_power_state_telemetry.py",
        "power_state_telemetry_agent": ROOT / "ops/launchd/com.tim.power-state-telemetry.plist",
        "sleep_prevention_agent": ROOT / "ops/launchd/com.tim.awake.plist",
        "watchdog": ROOT / "scripts/tim_watchdog.py",
        "watchdog_agent": ROOT / "ops/launchd/com.tim.watchdog.plist",
        "watchdog_policy": ROOT / "src/operational/watchdog.py",
        "runtime_agent": ROOT / "ops/launchd/com.tim.runtime.plist",
        "runtime_entrypoint": ROOT / "main.py",
        "websocket_collector": ROOT / "src/data_ingestion/binance_ws.py",
        "durable_ingress": ROOT / "src/data_ingestion/ingress.py",
        "durable_store": ROOT / "src/data_ingestion/durable.py",
        "recovery": ROOT / "src/data_ingestion/recovery.py",
    }
    payload = {
        "schema_version": "1.0.0",
        "sealed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": {name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)} for name, path in files.items()},
    }
    payload["manifest_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"output": str(args.output), "manifest_hash": payload["manifest_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
