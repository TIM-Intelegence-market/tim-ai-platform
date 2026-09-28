import subprocess

from scripts.tim_power_state_telemetry import capture, parse_assertions


def test_parse_assertions_requires_the_idle_sleep_guard():
    assert parse_assertions("PreventUserIdleSystemSleep PreventSystemSleep") == {
        "prevent_idle_system_sleep": True,
        "prevent_system_sleep": True,
    }
    assert parse_assertions("no active assertions") == {
        "prevent_idle_system_sleep": False,
        "prevent_system_sleep": False,
    }


def test_capture_is_observe_only_and_fails_when_guard_is_absent():
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess([], 0, stdout="PreventSystemSleep", stderr="")

    result = capture(fake_run)
    assert result["mode"] == "OBSERVE"
    assert result["trading_actions"] == 0
    assert result["host_awake_observed"] is True
    assert result["status"] == "FAIL"
