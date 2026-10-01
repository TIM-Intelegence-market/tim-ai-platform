"""ops/systemd: every unit points at real repo files, runs as tim, and carries no secret values."""
from __future__ import annotations

import configparser
import plistlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UNITS = ROOT / "ops/systemd"
SERVER_ROOT = "/opt/tim"
SERVICES = sorted(UNITS.glob("*.service"))
TIMERS = sorted(UNITS.glob("*.timer"))
# Only the backup units may write outside the checkout's data directories.
BACKUP_UNITS = {"tim-backup.service", "tim-restore-test.service"}


def parse(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=True, interpolation=None)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def test_expected_units_exist() -> None:
    names = {path.name for path in SERVICES + TIMERS}
    assert {
        "tim-runtime.service", "tim-watchdog.service",
        "tim-candle-finalizer.service", "tim-candle-finalizer.timer",
        "tim-rolling-liveness.service", "tim-rolling-liveness.timer",
        "tim-maintenance.service", "tim-maintenance.timer",
        "tim-coverage-worker.service", "tim-coverage-worker.timer",
        "tim-backup.service", "tim-backup.timer",
        "tim-restore-test.service", "tim-restore-test.timer",
        "tim-server-health.service", "tim-server-health.timer",
    } <= names


@pytest.mark.parametrize("path", SERVICES, ids=lambda path: path.name)
def test_service_runs_repo_script_as_tim_with_hardening(path: Path) -> None:
    service = parse(path)["Service"]
    arguments = service["ExecStart"].split()
    assert arguments[0] == f"{SERVER_ROOT}/.venv/bin/python"
    script = arguments[1]
    assert script.startswith(f"{SERVER_ROOT}/")
    assert (ROOT / script.removeprefix(f"{SERVER_ROOT}/")).is_file(), script
    assert service["User"] == "tim"
    assert service["WorkingDirectory"] == SERVER_ROOT
    assert service["EnvironmentFile"] == "/etc/tim/tim.env"
    assert service["NoNewPrivileges"] == "yes"
    assert service["ProtectSystem"] == "strict"
    allowed = {f"{SERVER_ROOT}/data", f"{SERVER_ROOT}/artifacts"}
    if path.name in BACKUP_UNITS:
        allowed.add("/var/backups/tim")
    assert set(service["ReadWritePaths"].split()) == allowed


@pytest.mark.parametrize("path", SERVICES, ids=lambda path: path.name)
def test_service_has_no_mac_paths_or_secret_values(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "/Users/" not in text and "homebrew" not in text and "Library/" not in text
    assert not re.search(r"(PASSWORD|TOKEN|SECRET)\s*=", text, re.IGNORECASE)
    assert "postgresql://" not in text


@pytest.mark.parametrize("path", TIMERS, ids=lambda path: path.name)
def test_every_timer_has_a_oneshot_service(path: Path) -> None:
    timer = parse(path)
    assert timer["Timer"].get("OnUnitActiveSec") or timer["Timer"].get("OnCalendar", "").endswith("UTC")
    assert timer["Install"]["WantedBy"] == "timers.target"
    service = parse(path.with_suffix(".service"))["Service"]
    assert service["Type"] == "oneshot"


def test_runtime_and_watchdog_restart_on_their_own() -> None:
    for name in ("tim-runtime.service", "tim-watchdog.service"):
        service = parse(UNITS / name)["Service"]
        assert service["Restart"] == "always"
        assert parse(UNITS / name)["Install"]["WantedBy"] == "multi-user.target"


def launchd_arguments(label: str) -> list[str]:
    with (ROOT / f"ops/launchd/{label}.plist").open("rb") as handle:
        arguments = plistlib.load(handle)["ProgramArguments"]
    return [item.replace("/Users/tim/Documents/TIM/tim", SERVER_ROOT) for item in arguments]


@pytest.mark.parametrize(
    ("unit", "label"),
    [
        ("tim-runtime.service", "com.tim.runtime"),
        ("tim-watchdog.service", "com.tim.watchdog"),
        ("tim-candle-finalizer.service", "com.tim.closed-candle-finalizer"),
        ("tim-rolling-liveness.service", "com.tim.rolling-liveness"),
        ("tim-maintenance.service", "com.tim.maintenance"),
    ],
)
def test_service_runs_the_same_command_as_its_launchd_counterpart(unit: str, label: str) -> None:
    assert parse(UNITS / unit)["Service"]["ExecStart"].split() == launchd_arguments(label)


def test_env_example_names_the_file_provider_without_a_secret() -> None:
    lines = [
        line for line in (UNITS / "tim.env.example").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    values = dict(line.split("=", 1) for line in lines)
    assert values["TIM_DATABASE_SECRET_PROVIDER"] == "file"
    assert values["TIM_DATABASE_SECRET_FILE"].startswith("/etc/tim/")
    assert set(values) == {"TIM_DATABASE_SECRET_PROVIDER", "TIM_DATABASE_SECRET_FILE", "TIM_ENABLE_OLLAMA"}


def test_polkit_rule_is_limited_to_the_runtime_unit_and_tim() -> None:
    rule = (UNITS / "50-tim-runtime.rules").read_text(encoding="utf-8")
    assert '"tim-runtime.service"' in rule and 'subject.user == "tim"' in rule
    assert 'action.lookup("verb")' in rule


def test_backup_timers_run_in_utc_and_catch_up_after_downtime() -> None:
    for name in ("tim-backup.timer", "tim-restore-test.timer"):
        timer = parse(UNITS / name)["Timer"]
        assert timer["OnCalendar"].endswith("UTC")
        assert timer["Persistent"] == "true"


def test_bootstrap_starts_nothing_without_flag_and_never_prints_the_secret() -> None:
    script = (ROOT / "ops/debian/bootstrap.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in script
    start_block = script.split('if [[ "$START" == true ]]; then', 1)
    assert "systemctl enable --now tim-runtime.service" in start_block[1]
    assert "systemctl enable --now tim-" not in start_block[0]
    assert not re.search(r"(echo|printf|cat)[^\n]*\$(PASSWORD|\{PASSWORD\})", script)
    assert 'cat "$SECRET"' in script and "<<SQL" in script  # password reaches psql via stdin only
    for unit in sorted(path.name for path in SERVICES + TIMERS):
        assert unit.startswith("tim-")


def test_bootstrap_reuses_an_existing_tim_group() -> None:
    # On tim-core-01 the group tim already exists; plain `useradd tim` would fail there.
    script = (ROOT / "ops/debian/bootstrap.sh").read_text(encoding="utf-8")
    assert "getent group tim >/dev/null || groupadd --system tim" in script
    assert "useradd --system --gid tim" in script


def test_bootstrap_refuses_to_run_next_to_another_tim_before_changing_anything() -> None:
    # tim-core-01 already ran TIM from /srv/tim; bootstrap reset the shared DB password.
    script = (ROOT / "ops/debian/bootstrap.sh").read_text(encoding="utf-8")
    preflight, rest = script.split('step "packages"', 1)
    assert "/srv/tim" in preflight and "systemd/user" in preflight and "sport = :8765" in preflight
    assert "refusing to replace its password" in preflight and "exit 6" in preflight
    assert "apt-get" not in preflight and "ALTER ROLE" not in preflight
