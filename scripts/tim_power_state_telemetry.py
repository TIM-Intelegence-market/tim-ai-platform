#!/usr/bin/env python3
"""Persist a bounded, read-only power-state observation for TIM's collector."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/operational/power_state_telemetry.json"


def parse_assertions(output: str) -> dict[str, bool]:
    """Return only the assertions relevant to preventing collection-time sleep."""
    return {
        "prevent_idle_system_sleep": "PreventUserIdleSystemSleep" in output,
        "prevent_system_sleep": "PreventSystemSleep" in output,
    }


def capture(run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> dict[str, object]:
    try:
        completed = run(
            ["/usr/bin/pmset", "-g", "assertions"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assertions = parse_assertions(completed.stdout)
        command_ok = completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        assertions = {"prevent_idle_system_sleep": False, "prevent_system_sleep": False}
        command_ok = False
    return {
        "observed_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "OBSERVE",
        "host_awake_observed": True,
        "pmset_command_ok": command_ok,
        "sleep_prevention": assertions,
        "status": "PASS" if command_ok and assertions["prevent_idle_system_sleep"] else "FAIL",
        "trading_actions": 0,
    }


def atomic_write(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = capture()
    atomic_write(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
