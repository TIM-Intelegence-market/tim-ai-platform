from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_timctl():
    loader = importlib.machinery.SourceFileLoader("timctl_test_module", str(ROOT / "scripts/timctl"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module = load_timctl()
    plist_path = tmp_path / "com.tim.runtime.plist"
    with plist_path.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.tim.runtime",
                "ProgramArguments": [sys.executable, str(ROOT / "main.py"), "--init-schema"],
                "WorkingDirectory": str(ROOT),
                "KeepAlive": True,
                "RunAtLoad": True,
            },
            handle,
        )
    plist_path.chmod(0o600)
    monkeypatch.setenv("TIMCTL_TEST_MODE", "true")
    monkeypatch.setenv("TIMCTL_PLATFORM", "darwin")
    monkeypatch.setenv("TIMCTL_PLIST_PATH", str(plist_path))
    return module, module.RuntimeControl()


def completed(command: list[str], returncode: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, returncode, stdout, "")


def test_service_status_resolves_launchd_pid_without_hardcoding(control, monkeypatch: pytest.MonkeyPatch) -> None:
    module, instance = control
    output = "state = running\n\tpid = 4242\n"
    monkeypatch.setattr(module, "run", lambda command, **kwargs: completed(command, stdout=output))
    assert instance.service_status() == {"loaded": True, "state": "RUNNING", "pid": 4242}


def test_database_boundary_rejects_wildcard_and_accepts_loopback(control, monkeypatch: pytest.MonkeyPatch) -> None:
    _, instance = control
    monkeypatch.setattr(instance, "listeners", lambda port: {"status": "LISTENING", "addresses": ["*.5432"], "unsafe": True})
    with pytest.raises(Exception, match="exposed"):
        instance.database_boundary_gate()
    monkeypatch.setattr(
        instance,
        "listeners",
        lambda port: {"status": "LISTENING", "addresses": ["127.0.0.1.5432", "::1.5432"], "unsafe": False},
    )
    assert instance.database_boundary_gate()["status"] == "PASS"


def test_start_is_fail_closed_before_launchd_when_database_is_exposed(control, monkeypatch: pytest.MonkeyPatch) -> None:
    _, instance = control
    calls: list[str] = []
    monkeypatch.setattr(instance, "static_observe_gate", lambda: {"status": "PASS"})
    monkeypatch.setattr(instance, "secret_gate", lambda: {"status": "AVAILABLE"})
    monkeypatch.setattr(
        instance,
        "listeners",
        lambda port: {"status": "LISTENING", "addresses": ["*.5432"], "unsafe": True},
    )
    monkeypatch.setattr(instance, "_launchctl", lambda *args, **kwargs: calls.append(args[0]))
    with pytest.raises(Exception, match="exposed"):
        instance.start()
    assert calls == []


def test_safe_stop_is_fail_closed_before_bootout_without_secret(control, monkeypatch: pytest.MonkeyPatch) -> None:
    module, instance = control
    calls: list[str] = []
    monkeypatch.setattr(instance, "static_observe_gate", lambda: {"status": "PASS"})
    monkeypatch.setattr(
        instance,
        "secret_gate",
        lambda: (_ for _ in ()).throw(module.RuntimeControlError("secret unavailable")),
    )
    monkeypatch.setattr(instance, "_launchctl", lambda *args, **kwargs: calls.append(args[0]))
    with pytest.raises(module.RuntimeControlError, match="secret unavailable"):
        instance.safe_stop()
    assert calls == []


def test_safe_stop_boots_out_before_durable_checkpoint(control, monkeypatch: pytest.MonkeyPatch) -> None:
    module, instance = control
    events: list[str] = []
    service = {"loaded": True, "state": "RUNNING", "pid": 4242}
    monkeypatch.setattr(instance, "static_observe_gate", lambda: {"status": "PASS", "mode": "OBSERVE"})
    monkeypatch.setattr(instance, "secret_gate", lambda: {"status": "AVAILABLE", "provider": "keychain"})
    monkeypatch.setattr(instance, "service_status", lambda: service.copy())
    monkeypatch.setattr(instance, "dashboard_health", lambda: {"operational": {"queue_depth": 0}})

    def bootout(*args, **kwargs):
        events.append("bootout")
        service.update({"loaded": False, "state": "STOPPED", "pid": None})
        return completed(list(args))

    monkeypatch.setattr(instance, "_launchctl", bootout)
    monkeypatch.setattr(instance, "listeners", lambda port: {"status": "CLOSED", "addresses": [], "unsafe": False})
    monkeypatch.setattr(instance, "_caffeinate_for_pid", lambda pid: [])
    monkeypatch.setattr(instance, "_wait", lambda predicate, timeout: predicate())
    monkeypatch.setattr(instance, "verify_stopped", lambda **kwargs: {"status": "PASS"})

    def ingestion(command: str, **kwargs):
        events.append(command)
        return {"status": "PASS", "mode": "OBSERVE", "trading_actions": 0, "checkpoint_safe": True}

    monkeypatch.setattr(instance, "ingestion_gate", ingestion)
    monkeypatch.setattr(module, "atomic_json", lambda path, payload: events.append("manifest"))
    result = instance.safe_stop()
    assert result["status"] == "PASS"
    assert events.index("bootout") < events.index("checkpoint") < events.index("manifest")
    assert result["prior_runtime_pid_resolved_from_launchd"] == 4242


def test_start_validates_secret_boundary_and_durable_state_before_bootstrap(
    control, monkeypatch: pytest.MonkeyPatch
) -> None:
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

    def launchctl(*args, **kwargs):
        events.append(args[0])
        service.update({"loaded": True, "state": "RUNNING", "pid": 5252})
        return completed(list(args))

    monkeypatch.setattr(instance, "_launchctl", launchctl)
    monkeypatch.setattr(instance, "listeners", lambda port: {"status": "LISTENING", "addresses": [f"127.0.0.1.{port}"], "unsafe": False})
    monkeypatch.setattr(instance, "_wait", lambda predicate, timeout: predicate())
    monkeypatch.setattr(instance, "verify_running", lambda: {"status": "PASS", "mode": "OBSERVE"})
    monkeypatch.setattr(module, "atomic_json", lambda path, payload: events.append("manifest"))
    assert instance.start()["status"] == "PASS"
    assert events[:5] == ["observe", "secret", "database", "ingestion-bootstrap", "bootstrap"]


def test_verify_running_includes_all_security_and_durable_gates(control, monkeypatch: pytest.MonkeyPatch) -> None:
    _, instance = control
    events: list[str] = []
    monkeypatch.setattr(instance, "static_observe_gate", lambda: events.append("observe") or {"status": "PASS"})
    monkeypatch.setattr(instance, "secret_gate", lambda: events.append("secret") or {"status": "AVAILABLE"})
    monkeypatch.setattr(instance, "database_boundary_gate", lambda: events.append("database") or {"status": "PASS"})
    monkeypatch.setattr(
        instance,
        "ingestion_gate",
        lambda command, **kwargs: events.append(f"ingestion-{command}") or {"status": "PASS"},
    )
    monkeypatch.setattr(instance, "service_status", lambda: {"loaded": True, "state": "RUNNING", "pid": 42})
    monkeypatch.setattr(
        instance,
        "listeners",
        lambda port: {"status": "LISTENING", "addresses": [f"127.0.0.1.{port}"], "unsafe": False},
    )
    monkeypatch.setattr(instance, "dashboard_health", lambda: {"status": "PASS", "mode": "OBSERVE"})
    assert instance.verify_running()["status"] == "PASS"
    assert events == ["observe", "secret", "database", "ingestion-status"]


def test_verify_stopped_detects_keepalive_restart_port_or_guard(control, monkeypatch: pytest.MonkeyPatch) -> None:
    _, instance = control
    monkeypatch.setattr(instance, "service_status", lambda: {"loaded": True, "state": "RUNNING", "pid": 1})
    monkeypatch.setattr(instance, "listeners", lambda port: {"status": "LISTENING", "addresses": [], "unsafe": False})
    monkeypatch.setattr(instance, "_caffeinate_for_pid", lambda pid: [99])
    with pytest.raises(Exception, match="not fully stopped"):
        instance.verify_stopped(prior_pid=1)


def test_timctl_source_has_no_hardcoded_pid_or_secret() -> None:
    source = (ROOT / "scripts/timctl").read_text(encoding="utf-8")
    assert not re_search(r"\bpid\s*=\s*\d{2,}\b", source)
    assert "tim_" + "local_only" not in source
    assert "sudo" not in source


def re_search(pattern: str, value: str) -> bool:
    import re

    return re.search(pattern, value) is not None
