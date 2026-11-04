from __future__ import annotations

import importlib.machinery
import importlib.util
import json
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


def test_ingestion_gate_uses_the_runtime_plist_environment(control, monkeypatch: pytest.MonkeyPatch) -> None:
    module, instance = control
    instance.plist["EnvironmentVariables"] = {"TIM_DATABASE_SECRET_PROVIDER": "file", "TIM_DATABASE_SECRET_FILE": "/tmp/tim-secret"}
    instance.runtime_env.update(instance.plist["EnvironmentVariables"])
    captured = {}
    def fake_run(command, **kwargs):
        captured.update(kwargs.get("env") or {})
        return completed(command, stdout='{"status":"PASS","mode":"OBSERVE","trading_actions":0}')
    monkeypatch.setattr(module, "run", fake_run)
    assert instance.ingestion_gate("status")["status"] == "PASS"
    assert captured["TIM_DATABASE_SECRET_PROVIDER"] == "file"
    assert captured["TIM_DATABASE_SECRET_FILE"] == "/tmp/tim-secret"


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
    monkeypatch.setattr(instance, "dashboard_health", lambda: {"status": "PASS", "mode": "OBSERVE"})
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


def test_macos_listeners_fall_back_to_lsof_and_probes_without_netstat(control, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.v2_completion import mac_live

    module, instance = control
    ifconfig = "lo0: flags\n\tinet 127.0.0.1 netmask 0xff000000\nen0: flags\n\tinet 192.168.10.23 netmask 0xffffff00\n"
    lsof = "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\nPython 7 tim-user 5u IPv4 0x1 0t0 TCP 127.0.0.1:8765 (LISTEN)\n"

    def fake_run(command, **kwargs):
        name = Path(command[0]).name
        if name == "netstat":
            return completed(command, stdout="Active Internet connections (including servers)\n")
        if name == "lsof":
            return completed(command, stdout=lsof) if "-iTCP:8765" in command else completed(command, 1)
        return completed(command, stdout=ifconfig)

    monkeypatch.setattr(module, "run", fake_run)
    open_ports = {("127.0.0.1", 5432)}
    monkeypatch.setattr(mac_live, "reachable", lambda host, port, timeout=2.0: (host, port) in open_ports)
    assert instance.listeners(8765) == {"status": "LISTENING", "addresses": ["127.0.0.1:8765"], "unsafe": False}
    assert instance.listeners(5432) == {"status": "LISTENING", "addresses": ["127.0.0.1:5432"], "unsafe": False}
    assert instance.database_boundary_gate()["status"] == "PASS"
    open_ports.add(("192.168.10.23", 5432))
    assert instance.listeners(5432)["unsafe"] is True
    assert instance.listeners(6000) == {"status": "CLOSED", "addresses": [], "unsafe": False}


def _mac_dashboard(module, instance, monkeypatch, *, ifconfig_hosts, open_hosts, lsof_bind="127.0.0.1:8765",
                   serve_status='{"TCP": {"8765": {"HTTP": true}}}', cli=True):
    """Fake macOS probes for port 8765: lsof bindings, interface addresses, answering hosts, tailscale serve."""
    from src.v2_completion import mac_live

    cli_path = Path(module.__file__).parent / "tailscale-fake-cli-does-not-exist"
    if cli:
        cli_path = Path(os.environ["PYTEST_TMP_CLI"])
    monkeypatch.setattr(module, "TAILSCALE_CLI_CANDIDATES", (str(cli_path),))
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    ifconfig = "lo0: flags\n\tinet 127.0.0.1 netmask 0xff000000\n" + "".join(
        f"if{index}: flags\n\tinet {host} netmask 0xffffffff\n" for index, host in enumerate(ifconfig_hosts)
    )
    lsof = (
        "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
        f"Python 7 tim-user 5u IPv4 0x1 0t0 TCP {lsof_bind} (LISTEN)\n"
        if lsof_bind else ""
    )

    def fake_run(command, **kwargs):
        name = Path(command[0]).name
        if name == "netstat":
            return completed(command, stdout="Active Internet connections (including servers)\n")
        if name == "lsof":
            return completed(command, stdout=lsof) if lsof else completed(command, 1)
        if name == cli_path.name:
            return completed(command, stdout=serve_status)
        return completed(command, stdout=ifconfig)

    monkeypatch.setattr(module, "run", fake_run)
    answering = {("127.0.0.1", 8765), *((host, 8765) for host in open_hosts)}
    monkeypatch.setattr(mac_live, "reachable", lambda host, port, timeout=2.0: (host, port) in answering)


def _remote_view(tmp_path, monkeypatch, hosts, users=None):
    path = tmp_path / "dashboard-remote-view.json"
    if hosts is not None:
        path.write_text(json.dumps({"hosts": hosts, **({"users": users} if users else {})}), encoding="utf-8")
    monkeypatch.setenv("TIM_DASHBOARD_REMOTE_VIEW_FILE", str(path))


TAILNET = "100.89.59.102"


@pytest.fixture(autouse=True)
def _fake_tailscale_cli(tmp_path, monkeypatch):
    cli = tmp_path / "Tailscale"
    cli.write_text("", encoding="utf-8")
    monkeypatch.setenv("PYTEST_TMP_CLI", str(cli))


def test_tailnet_view_blocked_when_funnel_is_on_or_cli_missing(control, monkeypatch, tmp_path) -> None:
    module, instance = control
    _remote_view(tmp_path, monkeypatch, ["zeyirs-mac-mini.tailce31c7.ts.net"])
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=[TAILNET], open_hosts=[TAILNET],
                   serve_status='{"AllowFunnel": {"zeyirs-mac-mini.tailce31c7.ts.net:443": true}}')
    assert instance.tailnet_view_only(instance.listeners(8765)) is False
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=[TAILNET], open_hosts=[TAILNET], cli=False)
    assert instance.tailnet_view_only(instance.listeners(8765)) is False


def test_tailscale_serve_proxy_counts_as_tailnet_view_only_with_owner_file(control, monkeypatch, tmp_path) -> None:
    module, instance = control
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=["192.168.10.23", TAILNET], open_hosts=[TAILNET])
    _remote_view(tmp_path, monkeypatch, ["zeyirs-mac-mini.tailce31c7.ts.net"])
    listener = instance.listeners(8765)
    assert listener["unsafe"] is True  # the raw probe still reports the exposure
    assert instance.tailnet_view_only(listener) is True


@pytest.mark.parametrize(
    ("hosts", "open_hosts", "lsof_bind"),
    [
        (None, [TAILNET], "127.0.0.1:8765"),  # phone access not switched on by the owner
        (["example.com"], [TAILNET], "127.0.0.1:8765"),  # only *.ts.net names count
        (["mac.tailce31c7.ts.net"], [TAILNET, "192.168.10.23"], "127.0.0.1:8765"),  # LAN answers too
        (["mac.tailce31c7.ts.net"], [TAILNET], "*:8765"),  # dashboard bound to every interface
        (["mac.tailce31c7.ts.net"], [TAILNET], None),  # binding not proven by lsof
    ],
)
def test_tailnet_view_stays_blocked_outside_the_narrow_case(control, monkeypatch, tmp_path, hosts, open_hosts, lsof_bind) -> None:
    module, instance = control
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=["192.168.10.23", TAILNET],
                   open_hosts=open_hosts, lsof_bind=lsof_bind)
    _remote_view(tmp_path, monkeypatch, hosts)
    listener = instance.listeners(8765)
    assert listener["unsafe"] is True
    assert instance.tailnet_view_only(listener) is False


def test_verify_running_passes_with_tailscale_serve_and_blocks_without_owner_file(control, monkeypatch, tmp_path) -> None:
    module, instance = control
    for gate in ("static_observe_gate", "secret_gate", "database_boundary_gate"):
        monkeypatch.setattr(instance, gate, lambda: {"status": "PASS"})
    monkeypatch.setattr(instance, "ingestion_gate", lambda command, **kwargs: {"status": "PASS"})
    monkeypatch.setattr(instance, "service_status", lambda: {"loaded": True, "state": "RUNNING", "pid": 42})
    monkeypatch.setattr(instance, "dashboard_health", lambda: {"status": "PASS", "mode": "OBSERVE"})
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=["192.168.10.23", TAILNET], open_hosts=[TAILNET])

    _remote_view(tmp_path, monkeypatch, ["zeyirs-mac-mini.tailce31c7.ts.net"])
    result = instance.verify_running()
    assert result["status"] == "PASS" and result["dashboard_tailnet_view"] == [TAILNET]

    _remote_view(tmp_path / "off", monkeypatch, None)
    with pytest.raises(module.RuntimeControlError, match="not proven loopback-only"):
        instance.verify_running()


def test_blocked_tailnet_view_names_the_failed_condition(control, monkeypatch, tmp_path) -> None:
    module, instance = control
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=[TAILNET], open_hosts=[TAILNET], cli=False)
    _remote_view(tmp_path, monkeypatch, ["zeyirs-mac-mini.tailce31c7.ts.net"])
    assert instance.tailnet_view_block_reason(instance.listeners(8765)) == "tailscale cli not found"
    _remote_view(tmp_path / "off", monkeypatch, None)
    assert instance.tailnet_view_block_reason(instance.listeners(8765)) == "no remote-view file with a *.ts.net host"


HOST = "zeyirs-mac-mini.tailce31c7.ts.net"


def test_serve_status_with_a_notice_before_the_json_is_read(control, monkeypatch, tmp_path) -> None:
    module, instance = control
    _remote_view(tmp_path, monkeypatch, [HOST])
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=[TAILNET], open_hosts=[TAILNET],
                   serve_status='Warning: client version differs\n{"TCP": {"8765": {"HTTP": true}}}\n')
    assert instance.tailnet_view_block_reason(instance.listeners(8765)) is None


def test_unreadable_serve_status_needs_login_check_in_owner_file(control, monkeypatch, tmp_path) -> None:
    module, instance = control
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=[TAILNET], open_hosts=[TAILNET],
                   serve_status="The Tailscale GUI is not running")
    _remote_view(tmp_path, monkeypatch, [HOST])
    reason = instance.tailnet_view_block_reason(instance.listeners(8765))
    assert reason.startswith("tailscale serve status is not JSON") and "GUI is not running" in reason
    _remote_view(tmp_path, monkeypatch, [HOST], users=["owner@example.com"])
    assert instance.tailnet_view_block_reason(instance.listeners(8765)) is None


def test_funnel_on_blocks_even_with_login_check(control, monkeypatch, tmp_path) -> None:
    module, instance = control
    _remote_view(tmp_path, monkeypatch, [HOST], users=["owner@example.com"])
    _mac_dashboard(module, instance, monkeypatch, ifconfig_hosts=[TAILNET], open_hosts=[TAILNET],
                   serve_status='{"AllowFunnel": {"%s:443": true}}' % HOST)
    assert instance.tailnet_view_block_reason(instance.listeners(8765)) == "tailscale funnel is on"
