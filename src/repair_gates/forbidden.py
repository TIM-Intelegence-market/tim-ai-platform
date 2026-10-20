"""Central list of forbidden repair actions and the bugfixer safety policy as gates (#18, P7.3)."""

from src.bugfixer.remediation import FORBIDDEN_ACTIONS
from src.bugfixer.safety import Policy, SafetyViolation

from .result import GateResult, GateStatus

ALLOWED_ACTIONS = frozenset({
    "observe", "bounded_reconnect", "review_log_path_permissions",
    "isolated_code_patch", "safe_stop_and_escalate",
})


def check_action(action: str) -> GateResult:
    """PASS only for an explicitly allowed action; forbidden or unknown actions FAIL."""
    if action in FORBIDDEN_ACTIONS:
        return GateResult("forbidden_actions", GateStatus.FAIL, f"forbidden repair action: {action}")
    if action not in ALLOWED_ACTIONS:
        return GateResult("forbidden_actions", GateStatus.FAIL, f"unknown repair action: {action!r}")
    return GateResult("forbidden_actions", GateStatus.PASS)


def check_policy(policy: Policy) -> GateResult:
    """PASS when the bugfixer policy verifies, FAIL when it raises SafetyViolation."""
    try:
        policy.verify()
    except SafetyViolation as exc:
        return GateResult("safety_policy", GateStatus.FAIL, str(exc))
    return GateResult("safety_policy", GateStatus.PASS)
