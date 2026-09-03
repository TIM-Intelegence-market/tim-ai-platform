from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.operational.logging import StructuredLog
from src.operational.watchdog import IndependentWatchdog


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


async def run(*, once: bool, interval: float) -> int:
    status_path = ROOT / "data/operational/watchdog_status.json"
    log = StructuredLog(ROOT / "data/operational/watchdog.jsonl")
    try:
        watchdog = IndependentWatchdog(ROOT, settings.database_url, symbol=settings.symbol)
    except Exception as error:
        report = {
            "status": "RED",
            "mode": "OBSERVE",
            "trading_actions": None,
            "checks": {
                "secret_provider": {
                    "status": "RED",
                    "value": None,
                    "reason": f"database secret provider unavailable ({type(error).__name__})",
                }
            },
        }
        atomic_json(status_path, report)
        log.write("WATCHDOG_START_FAILED", severity="ERROR", **report)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 2
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            loop.add_signal_handler(getattr(signal, name), stop.set)
    final_status = "RED"
    while not stop.is_set():
        report = await watchdog.collect()
        atomic_json(status_path, report)
        log.write(
            "WATCHDOG_CHECK",
            severity="ERROR" if report["status"] == "RED" else "WARNING" if report["status"] == "YELLOW" else "INFO",
            status=report["status"],
            checks=report["checks"],
            mode="OBSERVE",
            trading_actions=report.get("trading_actions"),
        )
        print(json.dumps(report, indent=2, sort_keys=True), flush=True)
        final_status = report["status"]
        if once:
            break
        try:
            await asyncio.wait_for(stop.wait(), timeout=max(5.0, min(interval, 300.0)))
        except TimeoutError:
            pass
    return 0 if final_status == "GREEN" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Independent read-only TIM watchdog")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=30.0)
    arguments = parser.parse_args()
    return asyncio.run(run(once=arguments.once, interval=arguments.interval))


if __name__ == "__main__":
    raise SystemExit(main())
