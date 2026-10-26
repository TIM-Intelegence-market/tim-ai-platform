"""Mac live installation: rendered launchd agents, drift, launchctl state and gate variants."""
from __future__ import annotations

import plistlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.v2_completion import mac_live
from src.v2_completion import start_gate_checks as gates

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 20, 18, 0, tzinfo=UTC)
LIVE = Path("/Users/tim/TIM-live")
HOME = Path("/Users/tim")


def test_live_agents_render_for_the_live_checkout() -> None:
    for label in mac_live.LIVE_AGENTS:
        rendered = mac_live.render_plist((REPO / f"ops/launchd/{label}.plist").read_bytes(), LIVE, HOME)
        value = plistlib.loads(rendered)
        assert value["Label"] == label
        assert value["WorkingDirectory"] == str(LIVE)
        assert value["ProgramArguments"][0] == str(LIVE / ".venv/bin/python")
        assert "Documents/TIM/tim" not in rendered.decode()
        assert value["EnvironmentVariables"]["TIM_DATABASE_SECRET_PROVIDER"] == "file"
        assert "PASSWORD" not in value["EnvironmentVariables"]


def test_other_home_is_rendered_too() -> None:
    template = (REPO / "ops/launchd/com.tim.watchdog.plist").read_bytes()
    value = plistlib.loads(mac_live.render_plist(template, Path("/Users/x/TIM-live"), Path("/Users/x")))
    assert value["EnvironmentVariables"]["HOME"] == "/Users/x"
    assert value["EnvironmentVariables"]["TIM_DATABASE_SECRET_FILE"].startswith("/Users/x/Library/")


def test_template_user_name_becomes_the_home_owner() -> None:
    template = (REPO / "ops/launchd/com.tim.runtime.plist").read_bytes()
    assert b"<key>UserName</key><string>tim-user</string>" in template
    value = plistlib.loads(mac_live.render_plist(template, Path("/Users/x/TIM-live"), Path("/Users/x")))
    assert value["UserName"] == "x"
    assert b"tim-user" not in mac_live.render_plist(template, Path("/Users/x/TIM-live"), Path("/Users/x"))


def test_launchd_drift(tmp_path: Path) -> None:
    root = tmp_path / "live"
    (root / "ops/launchd").mkdir(parents=True)
    agents = tmp_path / "agents"
    agents.mkdir()
    for label in mac_live.LIVE_AGENTS:
        template = (REPO / f"ops/launchd/{label}.plist").read_bytes()
        (root / f"ops/launchd/{label}.plist").write_bytes(template)
        (agents / f"{label}.plist").write_bytes(mac_live.render_plist(template, root, tmp_path))
    assert mac_live.launchd_drift(root, agents, tmp_path) == []
    (agents / "com.tim.watchdog.plist").write_bytes(b"edited")
    (agents / "com.tim.qualification-daily.plist").unlink()
    assert mac_live.launchd_drift(root, agents, tmp_path) == ["com.tim.watchdog", "com.tim.qualification-daily"]
    assert mac_live.launchd_drift(tmp_path / "missing", agents, tmp_path) is None


def test_launchctl_state_and_interfaces() -> None:
    assert mac_live.launchctl_state("gui/501/com.tim.watchdog = {\n\tstate = running\n\tpid = 7\n}") == "active"
    assert mac_live.launchctl_state("\tstate = not running\n") == "not"
    assert mac_live.launchctl_state(None) is None
    ifconfig = ("lo0: flags\n\tinet 127.0.0.1 netmask 0xff000000\n\tinet6 ::1 prefixlen 128\n"
                "\tinet6 fe80::1%lo0 prefixlen 64\nen0: flags\n\tinet 192.168.10.23 netmask 0xffffff00\n"
                "\tinet6 fe80::abc%en0 prefixlen 64\nutun4: flags\n\tinet 100.64.1.2 --> 100.64.1.2\n")
    assert mac_live.interface_addresses(ifconfig) == ["100.64.1.2", "192.168.10.23"]


def test_postgresql_reachability_gate() -> None:
    passing = gates.check_postgresql_reachability("localhost", {"192.168.10.23": False}, port=5432)
    assert passing.status == "PASS" and passing.name == "postgresql_security"
    exposed = gates.check_postgresql_reachability("localhost", {"192.168.10.23": True}, port=5432)
    assert exposed.status == "FAIL" and "192.168.10.23:5432" in exposed.reasons[0]
    assert gates.check_postgresql_reachability("*", {}, port=5432).status == "FAIL"
    assert gates.check_postgresql_reachability(None, {}, port=5432).status == "PENDING"
    assert gates.check_postgresql_reachability("localhost", None, port=5432).status == "PENDING"


def test_in_process_log_rotation_gate(tmp_path: Path) -> None:
    fresh = {"queue.jsonl.1.gz": NOW - timedelta(minutes=20), "events.jsonl.1.gz": NOW - timedelta(days=30)}
    assert gates.check_log_rotation_in_process(fresh, [], NOW).status == "PASS"
    assert gates.check_log_rotation_in_process({"x.gz": NOW - timedelta(hours=27)}, [], NOW).status == "FAIL"
    assert gates.check_log_rotation_in_process({}, [], NOW).status == "FAIL"
    assert gates.check_log_rotation_in_process(fresh, ["queue.jsonl"], NOW).status == "FAIL"
    (tmp_path / "queue.jsonl.1.gz").write_bytes(b"x")
    (tmp_path / "queue.jsonl").write_bytes(b"x" * 10)
    archives, oversized = mac_live.log_rotation_evidence(tmp_path)
    assert list(archives) == ["queue.jsonl.1.gz"] and oversized == []


def test_runtime_check_reads_launchd_on_macos(monkeypatch) -> None:
    from scripts import tim_server_health as health

    monkeypatch.setattr(health, "command_output", lambda command: "\tstate = running\n\tpid = 9\n")
    assert health.runtime_check(health.launchd_runtime_output())["status"] == "GREEN"
    monkeypatch.setattr(health, "command_output", lambda command: None)
    assert health.runtime_check(health.launchd_runtime_output())["status"] == "RED"
