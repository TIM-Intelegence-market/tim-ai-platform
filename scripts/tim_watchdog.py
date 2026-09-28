from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.operational.logging import StructuredLog
from src.operational.watchdog import IndependentWatchdog, restartable_failures


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


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def restart_decision(
    report: dict,
    state: dict,
    *,
    required_red_cycles: int,
    cooldown_seconds: float,
    now: float | None = None,
) -> dict:
    """Fail closed: require repeatable runtime evidence before one restart."""
    failures = restartable_failures(report)
    prior = int(state.get("consecutive_restartable_red", 0) or 0)
    cycles = prior + 1 if failures else 0
    current = time.time() if now is None else now
    last_attempt = state.get("last_restart_attempt_epoch")
    elapsed = current - last_attempt if isinstance(last_attempt, (int, float)) else None
    cooldown_remaining = max(0.0, cooldown_seconds - elapsed) if elapsed is not None else 0.0
    eligible = (
        report.get("mode") == "OBSERVE"
        and report.get("trading_actions") == 0
        and bool(failures)
        and cycles >= required_red_cycles
        and cooldown_remaining == 0.0
    )
    return {
        "restartable_failures": list(failures),
        "consecutive_restartable_red": cycles,
        "cooldown_remaining_seconds": round(cooldown_remaining, 3),
        "eligible": eligible,
    }


async def controlled_restart(timeout: float) -> dict:
    """Delegate to TIM's guarded OBSERVE-only lifecycle controller."""
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(ROOT / "scripts/timctl"),
            "restart",
            cwd=ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        try:
            payload = json.loads(stdout)
        except ValueError:
            payload = {"status": "BLOCKED", "reason": "timctl returned invalid JSON"}
        return {
            "requested": True,
            "completed": process.returncode == 0 and payload.get("status") == "PASS",
            "result": payload,
        }
    except (OSError, asyncio.TimeoutError):
        return {"requested": True, "completed": False, "result": {"status": "BLOCKED", "reason": "controlled restart unavailable"}}


async def run(*, once: bool, interval: float, required_red_cycles: int, cooldown_seconds: float, restart_timeout: float) -> int:
    status_path = ROOT / "data/operational/watchdog_status.json"
    recovery_state_path = ROOT / "data/operational/watchdog_recovery_state.json"
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
        decision = restart_decision(
            report,
            read_json(recovery_state_path),
            required_red_cycles=required_red_cycles,
            cooldown_seconds=cooldown_seconds,
        )
        recovery_state = {
            "consecutive_restartable_red": decision["consecutive_restartable_red"],
            "updated_at": report["checked_at"],
        }
        if decision["eligible"]:
            restart = await controlled_restart(restart_timeout)
            report["restart_requested"] = True
            report["restart"] = restart
            recovery_state["last_restart_attempt_epoch"] = time.time()
            recovery_state["last_restart_attempt_at"] = report["checked_at"]
            recovery_state["consecutive_restartable_red"] = 0
        else:
            report["restart_requested"] = False
            report["restart"] = {"requested": False, "decision": decision}
        atomic_json(recovery_state_path, recovery_state)
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
    parser.add_argument("--restart-after-red-cycles", type=int, default=3)
    parser.add_argument("--restart-cooldown", type=float, default=300.0)
    parser.add_argument("--restart-timeout", type=float, default=90.0)
    arguments = parser.parse_args()
    if arguments.restart_after_red_cycles < 1 or arguments.restart_cooldown < 0 or arguments.restart_timeout < 1:
        parser.error("restart thresholds must be positive (cooldown may be zero)")
    return asyncio.run(
        run(
            once=arguments.once,
            interval=arguments.interval,
            required_red_cycles=arguments.restart_after_red_cycles,
            cooldown_seconds=arguments.restart_cooldown,
            restart_timeout=arguments.restart_timeout,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
