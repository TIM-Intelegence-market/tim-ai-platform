"""Watchdog restart budget (docs/MULTI_AGENTEN_SYSTEM.md, section 4, package P2)."""
import asyncio
import json
from pathlib import Path

import pytest

from scripts import tim_watchdog
from scripts.tim_watchdog import restart_decision

RED = {"mode": "OBSERVE", "trading_actions": 0, "status": "RED",
       "checks": {"runtime_process": {"status": "RED"}}}
GREEN = {"mode": "OBSERVE", "trading_actions": 0, "status": "GREEN",
         "checks": {"runtime_process": {"status": "GREEN"}}}
NOW = 10_000.0


def _decide(report, state, **kwargs):
    return restart_decision(report, state, required_red_cycles=3, cooldown_seconds=300, now=NOW, **kwargs)


def test_restart_allowed_below_budget():
    decision = _decide(RED, {"consecutive_restartable_red": 2, "restart_attempt_epochs": [NOW - 900, NOW - 600]})
    assert decision["eligible"] and not decision["restart_hold"]
    assert decision["restarts_in_window"] == 2


def test_fourth_restart_in_window_becomes_hold():
    state = {"consecutive_restartable_red": 2, "restart_attempt_epochs": [NOW - 1500, NOW - 1000, NOW - 500]}
    decision = _decide(RED, state)
    assert not decision["eligible"]
    assert decision["restart_hold"] and decision["restart_hold_new"]


def test_hold_survives_old_restarts_leaving_the_window():
    decision = _decide(RED, {"consecutive_restartable_red": 9, "restart_hold": True, "restart_attempt_epochs": []})
    assert decision["restart_hold"] and not decision["restart_hold_new"] and not decision["eligible"]


def test_check_without_restartable_failure_clears_hold():
    decision = _decide(GREEN, {"restart_hold": True, "restart_attempt_epochs": [NOW - 100] * 3})
    assert not decision["restart_hold"] and not decision["eligible"]
    assert decision["consecutive_restartable_red"] == 0


def test_restarts_outside_window_and_junk_do_not_count():
    state = {"consecutive_restartable_red": 2,
             "restart_attempt_epochs": [NOW - 1801, NOW - 3600, "x", True, None, NOW + 60]}
    decision = _decide(RED, state)
    assert decision["restarts_in_window"] == 0 and decision["eligible"]


def test_cooldown_and_red_cycles_still_apply():
    assert not _decide(RED, {"consecutive_restartable_red": 0})["eligible"]
    cooling = _decide(RED, {"consecutive_restartable_red": 5, "last_restart_attempt_epoch": NOW - 100})
    assert not cooling["eligible"] and cooling["cooldown_remaining_seconds"] == 200


def test_custom_budget():
    state = {"consecutive_restartable_red": 2, "restart_attempt_epochs": [NOW - 10]}
    assert _decide(RED, state, max_restarts=1)["restart_hold"]
    assert _decide(RED, state, max_restarts=2)["eligible"]


def _run_loop(monkeypatch, tmp_path: Path, reports, restarts):
    queue = iter(reports)

    class FakeWatchdog:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def collect(self) -> dict:
            try:
                report = dict(next(queue))
            except StopIteration:
                stop_event.set()
                return dict(GREEN, checked_at="end")
            report["checked_at"] = f"t{len(restarts)}"
            return report

    async def fake_restart(timeout):
        restarts.append(timeout)
        return {"requested": True, "completed": True, "result": {"status": "PASS"}}

    async def no_wait(awaitable, timeout):
        awaitable.close()
        raise TimeoutError

    stop_event = asyncio.Event()
    monkeypatch.setattr(tim_watchdog, "ROOT", tmp_path)
    monkeypatch.setattr(tim_watchdog, "IndependentWatchdog", FakeWatchdog)
    monkeypatch.setattr(tim_watchdog, "controlled_restart", fake_restart)
    monkeypatch.setattr(tim_watchdog, "settings", type("S", (), {"database_url": "postgresql://test", "symbol": "BTCUSDT"})())
    monkeypatch.setattr(tim_watchdog.asyncio, "Event", lambda: stop_event)
    monkeypatch.setattr(tim_watchdog.asyncio, "wait_for", no_wait)
    (tmp_path / "data/operational").mkdir(parents=True, exist_ok=True)
    return asyncio.run(tim_watchdog.run(once=False, interval=0.0, required_red_cycles=1, cooldown_seconds=0,
                                        restart_timeout=1, max_restarts=3, restart_window_seconds=1800))


def test_loop_stops_restarting_after_budget_and_logs_hold(monkeypatch, tmp_path, capsys):
    restarts: list = []
    assert _run_loop(monkeypatch, tmp_path, [RED] * 10, restarts) == 0
    assert len(restarts) == 3
    state = json.loads((tmp_path / "data/operational/watchdog_recovery_state.json").read_text())
    events = [json.loads(line) for line in (tmp_path / "data/operational/watchdog.jsonl").read_text().splitlines()]
    holds = [event for event in events if event.get("event") == "WATCHDOG_RESTART_HOLD"]
    assert len(holds) == 1
    # The final GREEN check cleared the hold but the attempts stay in the window.
    assert state["restart_hold"] is False and len(state["restart_attempt_epochs"]) == 3
    assert any(json.loads(line).get("restart_hold") for line in capsys.readouterr().out.splitlines() if line.strip())


def test_loop_keeps_last_attempt_so_cooldown_spans_cycles(monkeypatch, tmp_path):
    restarts: list = []
    _run_loop(monkeypatch, tmp_path, [RED, RED], restarts)
    state = json.loads((tmp_path / "data/operational/watchdog_recovery_state.json").read_text())
    assert "last_restart_attempt_epoch" in state


@pytest.mark.parametrize("flag", [["--restart-max", "0"], ["--restart-window", "0"]])
def test_cli_rejects_empty_budget(monkeypatch, flag):
    monkeypatch.setattr("sys.argv", ["tim_watchdog.py", "--once", *flag])
    with pytest.raises(SystemExit):
        tim_watchdog.main()


def test_clock_moved_back_does_not_extend_cooldown():
    decision = _decide(RED, {"consecutive_restartable_red": 5, "last_restart_attempt_epoch": NOW + 3600})
    assert decision["eligible"] and decision["cooldown_remaining_seconds"] == 0
