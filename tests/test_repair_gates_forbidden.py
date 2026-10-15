import pytest

from src.bugfixer.safety import Policy
from src.repair_gates.forbidden import ALLOWED_ACTIONS, check_action, check_policy
from src.repair_gates.result import GateStatus


@pytest.mark.parametrize("action", [
    "test_production_database", "clear_queue", "clear_outbox", "reset_attempts", "skip_events",
    "disable_determinism", "disable_lookahead_safety", "enable_live_trading", "enable_execution",
])
def test_forbidden_actions_fail(action):
    result = check_action(action)
    assert result.gate == "forbidden_actions"
    assert result.status is GateStatus.FAIL
    assert action in result.reason


def test_unknown_action_fails():
    result = check_action("drop_everything")
    assert result.status is GateStatus.FAIL
    assert "unknown" in result.reason


@pytest.mark.parametrize("action", sorted(ALLOWED_ACTIONS))
def test_allowed_actions_pass(action):
    assert check_action(action).status is GateStatus.PASS


@pytest.mark.parametrize("policy", [Policy(live_trading=True), Policy(determinism=False)])
def test_unsafe_policy_fails(policy):
    result = check_policy(policy)
    assert result.gate == "safety_policy"
    assert result.status is GateStatus.FAIL
    assert result.reason


def test_default_policy_passes():
    assert check_policy(Policy()).status is GateStatus.PASS
