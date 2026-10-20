"""ops/systemd: every unit points at real repo files, runs as tim, and carries no secret values.

The Qwen diagnosis unit (PR-2) is the one exception to "runs as tim": it runs as tim-agent without the env file,
credentials or journal group, and gets its own isolation test.
"""
from __future__ import annotations

import configparser
import json
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
# Runs as tim-agent, not tim: User=tim and EnvironmentFile are forbidden there (test_agent_unit_isolation).
AGENT_UNITS = {"tim-qwen-diagnose.service"}
# Optional extra write paths (leading "-": absent until the installer creates them).
EXTRA_WRITE = {"tim-checkup.service": {"-/var/lib/tim-agent/requests"}}
# Units added by the checkup plan: every path outside data/ and artifacts/ must be optional ("-").
NEW_UNITS = ("tim-checkup.service", "tim-qwen-diagnose.service")
PATH_KEYS = ("ReadWritePaths", "ReadOnlyPaths", "InaccessiblePaths", "ExecPaths", "NoExecPaths")
DROPIN = UNITS / "ollama.service.d/tim-limits.conf"
AGENT_HOME = "/var/lib/tim-agent"
CONFIG = json.loads((ROOT / "config/tim_checkup.json").read_text(encoding="utf-8"))


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
        "tim-checkup.service", "tim-checkup.timer",
        "tim-qwen-diagnose.service", "tim-qwen-diagnose.timer",
    } <= names
    assert (UNITS / "tim-checkup.path").is_file() and DROPIN.is_file()


@pytest.mark.parametrize("path", SERVICES, ids=lambda path: path.name)
def test_service_runs_repo_script_as_tim_with_hardening(path: Path) -> None:
    if path.name in AGENT_UNITS:
        pytest.skip("runs as tim-agent; see test_agent_unit_isolation")
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
    allowed |= EXTRA_WRITE.get(path.name, set())
    assert set(service["ReadWritePaths"].split()) == allowed


def test_checkup_unit_hardening() -> None:
    # The checkup holds the GitHub App key: it gets it only as a credential and runs tightly sandboxed.
    service = parse(UNITS / "tim-checkup.service")["Service"]
    assert service["ExecStart"].split() == [
        f"{SERVER_ROOT}/.venv/bin/python", f"{SERVER_ROOT}/scripts/tim_checkup.py", "run"]
    assert service["Type"] == "oneshot" and "Restart" not in service
    assert service["User"] == "tim" and service["Group"] == "tim"
    assert service["SupplementaryGroups"] == "systemd-journal"
    assert service["LoadCredential"].startswith("github-app-key:/etc/tim/")
    assert service["UMask"] == "0077"
    assert service["SystemCallFilter"] == "@system-service"
    assert service["SystemCallArchitectures"] == "native"
    assert service["ProtectProc"] == "invisible"
    assert service["CapabilityBoundingSet"] == ""
    for key in ("NoNewPrivileges", "PrivateTmp", "PrivateDevices", "ProtectHome", "ProtectKernelTunables",
                "ProtectKernelModules", "ProtectKernelLogs", "ProtectControlGroups", "ProtectClock",
                "ProtectHostname", "RestrictNamespaces", "RestrictRealtime", "RestrictSUIDSGID", "LockPersonality"):
        assert service[key] == "yes", key
    assert set(service["RestrictAddressFamilies"].split()) == {"AF_UNIX", "AF_INET", "AF_INET6"}
    assert 0 < int(service["TimeoutStartSec"]) <= 300
    assert service["MemoryMax"] and service["LimitFSIZE"] and service["CPUQuota"]
    assert "Environment" not in service or "TOKEN" not in service["Environment"].upper()
    timer = parse(UNITS / "tim-checkup.timer")["Timer"]
    assert timer["OnUnitActiveSec"] == "900s" and timer["Persistent"] == "false"


def test_bootstrap_never_enables_the_checkup() -> None:
    # bootstrap.sh copies tim-checkup.* and tim-qwen-diagnose.* by glob; only ops/debian/install_checkup.sh enables them.
    script = (ROOT / "ops/debian/bootstrap.sh").read_text(encoding="utf-8")
    enables = [line for line in script.replace("\\\n", " ").splitlines() if "systemctl enable" in line]
    assert enables and not any("tim-checkup" in line or "tim-qwen" in line or "*" in line for line in enables)
    assert "ollama" not in script.lower().replace("tim_enable_ollama", "")


HARDENING_YES = ("NoNewPrivileges", "PrivateTmp", "PrivateDevices", "ProtectHome", "ProtectKernelTunables",
                 "ProtectKernelModules", "ProtectKernelLogs", "ProtectControlGroups", "ProtectClock",
                 "ProtectHostname", "RestrictNamespaces", "RestrictRealtime", "RestrictSUIDSGID", "LockPersonality")
PRIVATE_NETS = ("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
                "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
                "::1/128", "fc00::/7", "fe80::/10", "ff00::/8")


def _endpoint() -> tuple[str, str]:
    match = re.fullmatch(r"http://(127\.0\.0\.2):(\d+)", CONFIG["agent"]["endpoint"])
    assert match, CONFIG["agent"]["endpoint"]
    return match.group(1), match.group(2)


def test_agent_unit_isolation() -> None:
    # Qwen reads code and writes untrusted advice: no secret, no journal, no TIM data, no private network, no DB.
    unit = parse(UNITS / "tim-qwen-diagnose.service")
    service = unit["Service"]
    assert service["ExecStart"].split() == [
        f"{SERVER_ROOT}/.venv/bin/python", f"{SERVER_ROOT}/scripts/tim_checkup.py", "diagnose"]
    assert service["Type"] == "oneshot" and "Restart" not in service
    # Identity: its own user and group, nothing else.
    assert service["User"] == "tim-agent" and service["Group"] == "tim-agent"
    for key in ("EnvironmentFile", "LoadCredential", "LoadCredentialEncrypted", "SetCredential", "SupplementaryGroups",
                "PassEnvironment", "DynamicUser", "AmbientCapabilities"):
        assert key not in service, key
    environment = dict(item.split("=", 1) for item in service["Environment"].split())
    assert environment == {"PYTHONDONTWRITEBYTECODE": "1", "HOME": AGENT_HOME, "GIT_OPTIONAL_LOCKS": "0"}
    assert service["WorkingDirectory"] == SERVER_ROOT
    assert service["UMask"] == "0027"
    # File system: writes only results/ and log/, never sees secrets, TIM data, backups, the DB or the journal.
    assert service["ProtectSystem"] == "strict"
    assert set(service["ReadWritePaths"].split()) == {f"-{AGENT_HOME}/results", f"-{AGENT_HOME}/log"}
    hidden = {path.lstrip("-") for path in service["InaccessiblePaths"].split()}
    assert {"/etc/tim", "/opt/tim/data", "/opt/tim/artifacts", "/var/backups/tim", "/var/lib/postgresql",
            "/run/postgresql", "/var/log", "/run/credentials", "/srv/tim"} <= hidden
    for key in HARDENING_YES:
        assert service[key] == "yes", key
    assert service["ProtectProc"] == "invisible"
    assert service["SystemCallFilter"] == "@system-service" and service["SystemCallArchitectures"] == "native"
    assert service["CapabilityBoundingSet"] == ""
    assert set(service["RestrictAddressFamilies"].split()) == {"AF_UNIX", "AF_INET", "AF_INET6"}
    # Network: loopback and private nets denied; only Ollama's own address is allowed. No resolver line before P0.
    denied = service["IPAddressDeny"].split()
    assert set(PRIVATE_NETS) <= set(denied) and "any" not in denied
    host, _ = _endpoint()
    # Before P0 (resolver null or "public") only Ollama; a private resolver from P0 adds exactly its own /32.
    resolver = CONFIG["agent"].get("resolver")
    extra = [] if resolver in (None, "public") else [f"{resolver}/32"]
    assert service["IPAddressAllow"].split() == [f"{host}/32", *extra]
    assert "127.0.0.1" not in service["IPAddressAllow"]
    # Limits.
    assert int(service["Nice"]) >= 10
    assert service["MemoryMax"] == "1G" and service["LimitFSIZE"] and service["CPUQuota"] and service["TasksMax"]
    timeout = int(service["TimeoutStartSec"])
    assert CONFIG["agent"]["deadline_seconds"] < timeout <= 1200
    assert "ollama.service" in unit["Unit"]["After"].split()
    assert "Install" not in unit  # started only by its timer


def test_qwen_timer() -> None:
    timer = parse(UNITS / "tim-qwen-diagnose.timer")
    assert timer["Timer"]["OnBootSec"] == "600s" and timer["Timer"]["OnUnitActiveSec"] == "300s"
    assert timer["Timer"]["Persistent"] == "false" and timer["Timer"]["AccuracySec"] == "30s"
    assert timer["Install"]["WantedBy"] == "timers.target"


@pytest.mark.parametrize("name", NEW_UNITS)
def test_new_units_optional_paths_have_dash(name: str) -> None:
    # Paths outside /opt/tim/data and /opt/tim/artifacts may be absent: without "-" the unit would fail to start.
    service = parse(UNITS / name)["Service"]
    seen = 0
    for key in PATH_KEYS:
        for path in service.get(key, "").split():
            seen += 1
            if path.removeprefix("-") in (f"{SERVER_ROOT}/data", f"{SERVER_ROOT}/artifacts"):
                continue
            assert path.startswith("-/"), (key, path)
    assert seen


def test_ollama_dropin_limits() -> None:
    # The drop-in may only limit Ollama: no ExecStart, no user, no model path, and never AllowedCPUs (installer only).
    dropin = parse(DROPIN)
    assert dropin.sections() == ["Service"]
    service = dropin["Service"]
    assert "AllowedCPUs" not in service
    assert set(service) == {"Nice", "CPUWeight", "CPUQuota", "IOSchedulingClass", "MemoryMax", "MemorySwapMax",
                            "OOMScoreAdjust", "IPAddressAllow", "IPAddressDeny", "Environment"}
    assert int(service["Nice"]) >= 10 and int(service["CPUWeight"]) <= 50
    assert service["CPUQuota"] == "300%" and service["IOSchedulingClass"] == "idle"
    assert service["MemoryMax"] == "28G" and service["MemorySwapMax"] == "0"
    assert int(service["OOMScoreAdjust"]) > 0
    assert service["IPAddressDeny"] == "any" and service["IPAddressAllow"] == "localhost"
    environment = dict(item.split("=", 1) for item in service["Environment"].split())
    host, port = _endpoint()
    assert environment == {"OLLAMA_HOST": f"{host}:{port}", "OLLAMA_NUM_PARALLEL": "1",
                           "OLLAMA_MAX_LOADED_MODELS": "1", "OLLAMA_KEEP_ALIVE": "10m", "OLLAMA_NO_CLOUD": "1"}
    assert "AllowedCPUs" not in "\n".join(line for line in DROPIN.read_text(encoding="utf-8").splitlines()
                                           if not line.startswith("#"))


def test_checkup_path_unit() -> None:
    unit = parse(UNITS / "tim-checkup.path")
    assert dict(unit["Path"]) == {"PathChanged": f"{AGENT_HOME}/results", "Unit": "tim-checkup.service",
                                  "TriggerLimitIntervalSec": "1h", "TriggerLimitBurst": "12"}
    assert unit["Install"]["WantedBy"] == "paths.target"
    assert set(unit.sections()) == {"Unit", "Path", "Install"}


@pytest.mark.parametrize("path", SERVICES, ids=lambda path: path.name)
def test_service_has_no_mac_paths_or_secret_values(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert "/Users/" not in text and "homebrew" not in text and "Library/" not in text
    assert not re.search(r"(PASSWORD|TOKEN|SECRET)\s*=", text, re.IGNORECASE)
    assert "postgresql://" not in text


@pytest.mark.parametrize("path", TIMERS, ids=lambda path: path.name)
def test_every_timer_has_a_oneshot_service(path: Path) -> None:
    timer = parse(path)
    assert (timer["Timer"].get("OnUnitActiveSec") or timer["Timer"].get("OnUnitInactiveSec")
            or timer["Timer"].get("OnCalendar", "").endswith("UTC"))
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
