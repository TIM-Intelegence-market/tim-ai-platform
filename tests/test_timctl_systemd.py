"""scripts/timctl on Linux: the same gates, with systemd and ss instead of launchd and netstat."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.test_v2_completion_runtime_control import ROOT, completed, load_timctl


def unit_text(*, exec_start: str | None = None, working_directory: str | None = None) -> str:
    exec_start = exec_start or f"{sys.executable} {ROOT / 'main.py'} --init-schema"
    working_directory = working_directory or str(ROOT)
    return (
        "[Unit]\nDescription=TIM\n\n[Service]\n"
        f"ExecStart={exec_start}\nWorkingDirectory={working_directory}\nRestart=always\n"
    )


def make_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str | None = None, mode: int = 0o644):
    module = load_timctl()
    unit = tmp_path / "tim-runtime.service"
    unit.write_text(text or unit_text(), encoding="utf-8")
    unit.chmod(mode)
    monkeypatch.setenv("TIMCTL_TEST_MODE", "true")
    monkeypatch.setenv("TIMCTL_PLATFORM", "linux")
    monkeypatch.setenv("TIMCTL_UNIT_PATH", str(unit))
    return module, module.RuntimeControl()


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    return make_control(tmp_path, monkeypatch)


def test_linux_uses_systemd_and_reads_python_from_unit(control) -> None:
    _, instance = control
    assert instance.service_manager == "systemd"
    assert instance.target == "systemd/tim-runtime.service"
    assert instance.runtime_python == sys.executable


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (unit_text(exec_start="/usr/bin/python3 /opt/other/main.py"), "not the TIM runtime"),
        (unit_text(working_directory="/tmp"), "wrong working directory"),
        ("[Service]\nWorkingDirectory=/opt/tim\n", "not the TIM runtime"),
    ],
)
def test_unit_that_is_not_the_tim_runtime_is_rejected(tmp_path, monkeypatch, text, match) -> None:
    # make_control loads its own copy of timctl, so match on the message.
    with pytest.raises(Exception, match=match):
        make_control(tmp_path, monkeypatch, text)


def test_group_or_world_writable_unit_is_rejected(tmp_path, monkeypatch) -> None:
    with pytest.raises(Exception, match="permissions are unsafe"):
        make_control(tmp_path, monkeypatch, mode=0o664)


def test_missing_unit_is_rejected(tmp_path, monkeypatch) -> None:
    module = load_timctl()
    monkeypatch.setenv("TIMCTL_TEST_MODE", "true")
    monkeypatch.setenv("TIMCTL_PLATFORM", "linux")
    monkeypatch.setenv("TIMCTL_UNIT_PATH", str(tmp_path / "absent.service"))
    with pytest.raises(module.RuntimeControlError, match="missing or invalid"):
        module.RuntimeControl()


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=4242\n",
         {"loaded": True, "state": "RUNNING", "pid": 4242}),
        ("LoadState=loaded\nActiveState=inactive\nSubState=dead\nMainPID=0\n",
         {"loaded": False, "state": "STOPPED", "pid": None}),
        ("LoadState=loaded\nActiveState=failed\nSubState=failed\nMainPID=0\n",
         {"loaded": False, "state": "STOPPED", "pid": None}),
        ("LoadState=loaded\nActiveState=activating\nSubState=auto-restart\nMainPID=0\n",
         {"loaded": True, "state": "ACTIVATING", "pid": None}),
        ("LoadState=not-found\nActiveState=inactive\nSubState=dead\nMainPID=0\n",
         {"loaded": False, "state": "STOPPED", "pid": None}),
    ],
)
def test_service_status_maps_systemd_states(control, monkeypatch, stdout, expected) -> None:
    module, instance = control
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "run", lambda command, **kwargs: calls.append(command) or completed(command, stdout=stdout))
    assert instance.service_status() == expected
    assert calls[0][1:3] == ["show", "tim-runtime.service"]


def test_service_status_is_stopped_when_systemctl_fails(control, monkeypatch) -> None:
    module, instance = control
    monkeypatch.setattr(module, "run", lambda command, **kwargs: completed(command, returncode=1))
    assert instance.service_status() == {"loaded": False, "state": "STOPPED", "pid": None}


SS_OUTPUT = (
    "LISTEN 0      4096       127.0.0.1:5432       0.0.0.0:*\n"
    "LISTEN 0      4096           [::1]:5432          [::]:*\n"
    "LISTEN 0      128        127.0.0.1:8765       0.0.0.0:*\n"
)


def test_listeners_parse_ss_and_accept_loopback(control, monkeypatch) -> None:
    module, instance = control
    calls: list[list[str]] = []
    monkeypatch.setattr(module, "run", lambda command, **kwargs: calls.append(command) or completed(command, stdout=SS_OUTPUT))
    result = instance.listeners(5432)
    assert calls[0][1:] == ["-H", "-ltn"]
    assert result == {"status": "LISTENING", "addresses": ["127.0.0.1:5432", "[::1]:5432"], "unsafe": False}
    assert instance.database_boundary_gate()["status"] == "PASS"


@pytest.mark.parametrize("local", ["*:5432", "0.0.0.0:5432", "[::]:5432"])
def test_listeners_flag_wildcard_ss_bindings(control, monkeypatch, local) -> None:
    module, instance = control
    output = f"LISTEN 0 4096 {local} *:*\n"
    monkeypatch.setattr(module, "run", lambda command, **kwargs: completed(command, stdout=output))
    assert instance.listeners(5432)["unsafe"] is True
    with pytest.raises(module.RuntimeControlError, match="exposed"):
        instance.database_boundary_gate()


def test_start_runs_gates_before_systemctl_start(control, monkeypatch) -> None:
    module, instance = control
    events: list[str] = []
    service = {"loaded": False, "state": "STOPPED", "pid": None}
    monkeypatch.setattr(instance, "static_observe_gate", lambda: events.append("observe") or {"status": "PASS"})
    monkeypatch.setattr(instance, "secret_gate", lambda: events.append("secret") or {"status": "AVAILABLE"})
    monkeypatch.setattr(instance, "database_boundary_gate", lambda: events.append("database") or {"status": "PASS"})
    monkeypatch.setattr(
        instance,
        "ingestion_gate",
        lambda command, **kwargs: events.append(f"ingestion-{command}")
        or {"status": "PASS", "mode": "OBSERVE", "trading_actions": 0},
    )
    monkeypatch.setattr(instance, "service_status", lambda: service.copy())

    def systemctl(*args, **kwargs):
        events.append(" ".join(args))
        service.update({"loaded": True, "state": "RUNNING", "pid": 5252})
        return completed(list(args))

    monkeypatch.setattr(instance, "_systemctl", systemctl)
    monkeypatch.setattr(instance, "listeners", lambda port: {"status": "LISTENING", "addresses": [f"127.0.0.1:{port}"], "unsafe": False})
    monkeypatch.setattr(instance, "dashboard_health", lambda: {"status": "PASS", "mode": "OBSERVE"})
    monkeypatch.setattr(instance, "_wait", lambda predicate, timeout: predicate())
    monkeypatch.setattr(instance, "verify_running", lambda: {"status": "PASS", "mode": "OBSERVE"})
    monkeypatch.setattr(module, "atomic_json", lambda path, payload: events.append("manifest"))
    assert instance.start()["status"] == "PASS"
    assert events == ["observe", "secret", "database", "ingestion-bootstrap", "start tim-runtime.service", "manifest"]


def test_start_does_not_call_systemctl_when_database_is_exposed(control, monkeypatch) -> None:
    module, instance = control
    calls: list[tuple] = []
    monkeypatch.setattr(instance, "static_observe_gate", lambda: {"status": "PASS"})
    monkeypatch.setattr(instance, "secret_gate", lambda: {"status": "AVAILABLE"})
    monkeypatch.setattr(instance, "listeners", lambda port: {"status": "LISTENING", "addresses": ["*:5432"], "unsafe": True})
    monkeypatch.setattr(instance, "_systemctl", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(module.RuntimeControlError, match="exposed"):
        instance.start()
    assert calls == []


def test_safe_stop_stops_unit_before_durable_checkpoint(control, monkeypatch) -> None:
    module, instance = control
    events: list[str] = []
    service = {"loaded": True, "state": "RUNNING", "pid": 4242}
    monkeypatch.setattr(instance, "static_observe_gate", lambda: {"status": "PASS", "mode": "OBSERVE"})
    monkeypatch.setattr(instance, "secret_gate", lambda: {"status": "AVAILABLE", "provider": "file"})
    monkeypatch.setattr(instance, "service_status", lambda: service.copy())
    monkeypatch.setattr(instance, "dashboard_health", lambda: {"operational": {"queue_depth": 0}})

    def systemctl(*args, **kwargs):
        events.append(" ".join(args))
        service.update({"loaded": False, "state": "STOPPED", "pid": None})
        return completed(list(args))

    monkeypatch.setattr(instance, "_systemctl", systemctl)
    monkeypatch.setattr(instance, "listeners", lambda port: {"status": "CLOSED", "addresses": [], "unsafe": False})
    monkeypatch.setattr(instance, "_wait", lambda predicate, timeout: predicate())
    monkeypatch.setattr(instance, "verify_stopped", lambda **kwargs: {"status": "PASS"})
    monkeypatch.setattr(
        instance,
        "ingestion_gate",
        lambda command, **kwargs: events.append(command) or {"status": "PASS", "mode": "OBSERVE", "trading_actions": 0},
    )
    monkeypatch.setattr(module, "atomic_json", lambda path, payload: events.append("manifest"))
    result = instance.safe_stop()
    assert result["status"] == "PASS"
    assert result["service_manager"] == "systemd"
    assert result["prior_runtime_pid_resolved_from_launchd"] == 4242
    assert events.index("stop tim-runtime.service") < events.index("checkpoint") < events.index("manifest")


def test_status_reports_service_manager_for_watchdog(control, monkeypatch) -> None:
    module, instance = control
    output = "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=77\n"

    def fake_run(command, **kwargs):
        return completed(command, stdout=output if "show" in command else SS_OUTPUT)

    monkeypatch.setattr(module, "run", fake_run)
    payload = instance.status()
    assert payload["service_manager"] == "systemd"
    assert payload["service"]["pid"] == 77
    assert payload["launchd_target"] == "systemd/tim-runtime.service"


def test_macos_default_is_unchanged(tmp_path, monkeypatch) -> None:
    module = load_timctl()
    monkeypatch.setenv("TIMCTL_TEST_MODE", "true")
    monkeypatch.setenv("TIMCTL_PLATFORM", "darwin")
    monkeypatch.setenv("TIMCTL_PLIST_PATH", str(tmp_path / "absent.plist"))
    with pytest.raises(module.RuntimeControlError, match="launchd plist"):
        module.RuntimeControl()


def test_parse_systemd_service_reads_only_the_service_section() -> None:
    module = load_timctl()
    text = "[Unit]\nExecStart=/wrong\n# comment\n[Service]\nExecStart=/a b\nExecStart=/c d\n[Install]\nWantedBy=x\n"
    assert module.parse_systemd_service(text) == {"ExecStart": "/c d"}


def test_shipped_runtime_unit_passes_timctl_validation_when_root_matches(tmp_path, monkeypatch) -> None:
    shipped = (ROOT / "ops/systemd/tim-runtime.service").read_text(encoding="utf-8")
    localized = shipped.replace("/opt/tim", str(ROOT))
    _, instance = make_control(tmp_path, monkeypatch, localized)
    assert instance.runtime_python == str(ROOT / ".venv/bin/python")
