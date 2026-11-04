"""dashboard_refresh keeps timctl's BLOCKED reason so a rollback says why."""
from __future__ import annotations

import json
import subprocess

from src.operational.dashboard_refresh import timctl_reason


def _done(code: int, stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["timctl"], code, stdout, "")


def test_reason_is_taken_from_blocked_json() -> None:
    stdout = json.dumps({"status": "BLOCKED", "reason": "TIM dashboard is not proven loopback-only (x)"}, indent=2)
    assert timctl_reason(_done(2, stdout)) == {"reason": "TIM dashboard is not proven loopback-only (x)"}


def test_reason_is_empty_on_success_and_falls_back_to_last_line() -> None:
    assert timctl_reason(_done(0, '{"status": "PASS"}')) == {}
    assert timctl_reason(_done(1, "Traceback ...\nValueError: boom\n")) == {"reason": "ValueError: boom"}
    assert timctl_reason(_done(2, "")) == {}
