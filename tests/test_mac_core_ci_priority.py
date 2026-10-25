"""TIM Core and the CI runner share the Mac mini: launchd must rank TIM Core above CI."""

from __future__ import annotations

import plistlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _plist(label: str) -> dict:
    return plistlib.loads((ROOT / "ops/launchd" / f"{label}.plist").read_bytes())


def test_runtime_is_not_background_throttled() -> None:
    assert _plist("com.tim.runtime")["ProcessType"] == "Interactive"


def test_watchdog_and_gap_recovery_are_not_background_throttled() -> None:
    for label in ("com.tim.watchdog", "com.tim.history-recovery"):
        assert _plist(label)["ProcessType"] == "Standard", label


def test_ci_runner_and_ci_postgres_yield_to_tim_core() -> None:
    script = (ROOT / "ops/macos/setup_ci_runner.sh").read_text(encoding="utf-8")
    assert re.search(r"^CI_NICE=(\d+)$", script, re.MULTILINE)
    assert int(re.search(r"^CI_NICE=(\d+)$", script, re.MULTILINE).group(1)) >= 10
    plists = re.findall(r'cat > "\$(RUNNER_PLIST|PG_PLIST)" <<PLIST\n(.*?)\nPLIST\n', script, re.DOTALL)
    assert {name for name, _ in plists} == {"RUNNER_PLIST", "PG_PLIST"}
    for name, body in plists:
        assert "<key>Nice</key><integer>${CI_NICE}</integer>" in body, name
        assert "<key>ProcessType</key><string>Standard</string>" in body, name
        assert "Interactive" not in body, name
