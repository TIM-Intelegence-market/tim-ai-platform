import pytest

from src.repair_gates import forbidden
from src.repair_recipes import reconnect


@pytest.fixture(autouse=True)
def fake_gate(monkeypatch):
    def fake_check_action(action):
        if action == "invent_data_gaps":
            return {"status": "FAIL", "reason": "forbidden action: invent_data_gaps"}
        return {"status": "PASS", "reason": ""}

    monkeypatch.setattr(forbidden, "check_action", fake_check_action)


def test_reconnect_delays_are_capped():
    delays = [reconnect.reconnect_step(a)["delay_seconds"] for a in range(8)]
    assert delays == [1, 2, 4, 8, 16, 30, 30, 30]


def test_reconnect_step_returns_reconnect_decision():
    assert reconnect.reconnect_step(0) == {"decision": "RECONNECT", "delay_seconds": 1}


def test_reconnect_step_budget_exhausted():
    assert reconnect.reconnect_step(8) == {
        "decision": "ESCALATED",
        "reason": "reconnect budget exhausted",
    }


@pytest.mark.parametrize("attempt", [-1, True, "3"])
def test_reconnect_step_rejects_invalid_attempt(attempt):
    assert reconnect.reconnect_step(attempt) == {
        "decision": "ESCALATED",
        "reason": "invalid attempt",
    }


def test_configuration_port_conflict_escalates():
    assert reconnect.plan("CONFIGURATION", "observe", 0) == {
        "decision": "ESCALATED",
        "reason": "no proven recipe",
    }


def test_terminal_blocked_safe_stops_even_with_reconnect_action():
    assert reconnect.plan("TERMINAL_BLOCKED", "bounded_reconnect", 0) == {
        "decision": "SAFE_STOP"
    }


def test_invariant_violation_safe_stops():
    assert reconnect.plan("INVARIANT_VIOLATION", "observe", 0) == {
        "decision": "SAFE_STOP"
    }


def test_forbidden_action_is_rejected():
    result = reconnect.plan("NETWORK", "invent_data_gaps", 0)
    assert result == {
        "decision": "REJECTED",
        "reason": "forbidden action: invent_data_gaps",
    }


def test_environment_needing_root_escalates():
    assert reconnect.plan("ENVIRONMENT", "requires_root", 0) == {
        "decision": "ESCALATED",
        "reason": "no proven recipe",
    }


def test_network_reconnect_returns_step():
    assert reconnect.plan("NETWORK", "bounded_reconnect", 3) == {
        "decision": "RECONNECT",
        "delay_seconds": 8,
    }


def test_network_at_budget_escalates():
    assert reconnect.plan("NETWORK", "bounded_reconnect", 8) == {
        "decision": "ESCALATED",
        "reason": "reconnect budget exhausted",
    }


@pytest.mark.parametrize("attempt", [-1, True, "3"])
def test_network_invalid_attempt_escalates(attempt):
    assert reconnect.plan("NETWORK", "bounded_reconnect", attempt) == {
        "decision": "ESCALATED",
        "reason": "invalid attempt",
    }


def test_plan_never_returns_fixed():
    for category in ("NETWORK", "CONFIGURATION", "TERMINAL_BLOCKED", "ENVIRONMENT"):
        for action in ("bounded_reconnect", "observe", "invent_data_gaps"):
            assert reconnect.plan(category, action, 0)["decision"] != "FIXED"
