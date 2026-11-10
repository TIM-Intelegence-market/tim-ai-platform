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
    max_restarts: int = 3,
    restart_window_seconds: float = 1800.0,
    now: float | None = None,
) -> dict:
    """Fail closed: require repeatable runtime evidence before one restart.

    Restart budget (docs/MULTI_AGENTEN_SYSTEM.md, section 4, package P2): at most ``max_restarts``
    restarts within ``restart_window_seconds``. When a further restart would be needed, the watchdog
    holds instead: no more restarts until a check without restartable failures clears the hold.
    The hold is reported, never lifted by time alone, so a failure a restart cannot fix ends in a
    report and not in an endless restart loop.
    """
    failures = restartable_failures(report)
    prior = int(state.get("consecutive_restartable_red", 0) or 0)
    cycles = prior + 1 if failures else 0
    current = time.time() if now is None else now
    last_attempt = state.get("last_restart_attempt_epoch")
    elapsed = current - last_attempt if isinstance(last_attempt, (int, float)) else None
    if elapsed is not None and elapsed < 0:  # clock moved back: a restart "in the future" does not extend the cooldown
        elapsed = None
    cooldown_remaining = max(0.0, cooldown_seconds - elapsed) if elapsed is not None else 0.0
    history = state.get("restart_attempt_epochs")
    recent = sorted(
        value for value in (history if isinstance(history, list) else [])
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and 0 <= current - value <= restart_window_seconds
    )
    wanted = (
        report.get("mode") == "OBSERVE"
        and report.get("trading_actions") == 0
        and bool(failures)
        and cycles >= required_red_cycles
        and cooldown_remaining == 0.0
    )
    # Only a check without restartable failures clears an existing hold.
    hold = bool(state.get("restart_hold")) and bool(failures)
    newly_held = wanted and not hold and len(recent) >= max_restarts
    hold = hold or newly_held
    return {
        "restartable_failures": list(failures),
        "consecutive_restartable_red": cycles,
        "cooldown_remaining_seconds": round(cooldown_remaining, 3),
        "restarts_in_window": len(recent),
        "restart_attempt_epochs": recent,
        "restart_hold": hold,
        "restart_hold_new": newly_held,
        "eligible": wanted and not hold,
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


async def run(*, once: bool, interval: float, required_red_cycles: int, cooldown_seconds: float, restart_timeout: float,
              max_restarts: int = 3, restart_window_seconds: float = 1800.0) -> int:
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
    final_status: str | None = None
    while not stop.is_set():
        report = await watchdog.collect()
        previous_state = read_json(recovery_state_path)
        decision = restart_decision(
            report,
            previous_state,
            required_red_cycles=required_red_cycles,
            cooldown_seconds=cooldown_seconds,
            max_restarts=max_restarts,
            restart_window_seconds=restart_window_seconds,
        )
        recovery_state = {
            "consecutive_restartable_red": decision["consecutive_restartable_red"],
            "updated_at": report["checked_at"],
            "restart_attempt_epochs": decision["restart_attempt_epochs"],
            "restart_hold": decision["restart_hold"],
        }
        # Keep the last attempt across cycles; without it the cooldown ended after one check.
        for key in ("last_restart_attempt_epoch", "last_restart_attempt_at", "restart_hold_since"):
            if key in previous_state:
                recovery_state[key] = previous_state[key]
        if not decision["restart_hold"]:
            recovery_state.pop("restart_hold_since", None)
        report["restart_hold"] = decision["restart_hold"]
        if decision["eligible"]:
            restart = await controlled_restart(restart_timeout)
            report["restart_requested"] = True
            report["restart"] = restart
            attempt_epoch = time.time()
            recovery_state["last_restart_attempt_epoch"] = attempt_epoch
            recovery_state["last_restart_attempt_at"] = report["checked_at"]
            recovery_state["restart_attempt_epochs"] = decision["restart_attempt_epochs"] + [attempt_epoch]
            recovery_state["consecutive_restartable_red"] = 0
        else:
            report["restart_requested"] = False
            report["restart"] = {"requested": False, "decision": decision}
        if decision["restart_hold_new"]:
            recovery_state["restart_hold_since"] = report["checked_at"]
            log.write(
                "WATCHDOG_RESTART_HOLD",
                severity="ERROR",
                restarts_in_window=decision["restarts_in_window"],
                window_seconds=restart_window_seconds,
                restartable_failures=decision["restartable_failures"],
                reason="restart budget used up; no further restarts until a check without restartable failures",
            )
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
        if once:
            print(json.dumps(report, indent=2, sort_keys=True), flush=True)
        elif report["status"] != final_status or report.get("restart_requested") or decision["restart_hold_new"]:
            # The full report already goes to watchdog_status.json and the rotated
            # watchdog.jsonl. Repeating it on stdout every 30 s grew the
            # un-rotated launchd log by ~6 MB a day (log_growth YELLOW).
            print(json.dumps({"checked_at": report.get("checked_at"), "status": report["status"],
                              "previous_status": final_status, "restart_requested": report.get("restart_requested", False),
                              "restart_hold": report["restart_hold"]},
                             sort_keys=True), flush=True)
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
    parser.add_argument("--restart-max", type=int, default=3)
    parser.add_argument("--restart-window", type=float, default=1800.0)
    arguments = parser.parse_args()
    if (arguments.restart_after_red_cycles < 1 or arguments.restart_cooldown < 0 or arguments.restart_timeout < 1
            or arguments.restart_max < 1 or arguments.restart_window <= 0):
        parser.error("restart thresholds must be positive (cooldown may be zero)")
    return asyncio.run(
        run(
            once=arguments.once,
            interval=arguments.interval,
            required_red_cycles=arguments.restart_after_red_cycles,
            cooldown_seconds=arguments.restart_cooldown,
            restart_timeout=arguments.restart_timeout,
            max_restarts=arguments.restart_max,
            restart_window_seconds=arguments.restart_window,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
