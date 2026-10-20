from src.repair_gates.aggregate import CRITICAL_GATES, decide
from src.repair_gates.result import GateResult, GateStatus


def _gate(name, status):
    result = GateResult.__new__(GateResult)
    object.__setattr__(result, "gate", name)
    object.__setattr__(result, "status", status)
    return result


def _ok(name):
    return _gate(name, GateStatus.PASS)


def test_critical_gates_constant():
    assert CRITICAL_GATES == frozenset(
        {"determinism", "lookahead_safety", "db_integrity", "queue_integrity"}
    )


def test_pass_when_all_required_pass():
    out = decide({"a", "b"}, [_ok("a"), _ok("b")])
    assert out == {"status": "PASS", "escalate": False, "reasons": []}


def test_missing_required_gate_fails():
    out = decide({"a", "b"}, [_ok("a")])
    assert out["status"] == "FAIL"
    assert out["escalate"] is False
    assert any("b" in r for r in out["reasons"])


def test_duplicate_required_gate_fails():
    out = decide({"a"}, [_ok("a"), _ok("a")])
    assert out["status"] == "FAIL"
    assert any("a" in r for r in out["reasons"])


def test_skip_required_gate_fails():
    out = decide({"a"}, [_gate("a", GateStatus.SKIP)])
    assert out["status"] == "FAIL"


def test_blocked_required_gate_fails():
    out = decide({"a"}, [_gate("a", GateStatus.BLOCKED)])
    assert out["status"] == "FAIL"


def test_unexpected_gate_fails():
    out = decide({"a"}, [_ok("a"), _ok("extra")])
    assert out["status"] == "FAIL"
    assert any("extra" in r for r in out["reasons"])


def test_critical_failure_gives_safe_stop_and_escalates():
    out = decide({"determinism", "a"}, [_gate("determinism", GateStatus.FAIL), _ok("a")])
    assert out["status"] == "SAFE_STOP"
    assert out["escalate"] is True


def test_critical_failure_wins_over_plain_failure():
    out = decide(
        {"db_integrity", "a"},
        [_gate("db_integrity", GateStatus.FAIL), _gate("a", GateStatus.FAIL)],
    )
    assert out["status"] == "SAFE_STOP"
    assert out["escalate"] is True


def test_non_critical_failure_does_not_escalate():
    out = decide({"a"}, [_gate("a", GateStatus.FAIL)])
    assert out["status"] == "FAIL"
    assert out["escalate"] is False


def test_empty_required_fails():
    out = decide(set(), [])
    assert out["status"] == "FAIL"


def test_non_gate_result_item_fails_without_raising():
    out = decide({"a"}, [_ok("a"), object(), None])
    assert out["status"] == "FAIL"


def test_bad_inputs_do_not_raise():
    assert decide(None, None)["status"] == "FAIL"
    assert decide(5, 7)["status"] == "FAIL"


def test_reasons_are_sorted():
    out = decide({"z", "a", "m"}, [])
    assert out["reasons"] == sorted(out["reasons"])


def test_cannot_mark_fixed_when_required_gates_fail():
    out = decide({"a", "b"}, [_ok("a"), _gate("b", GateStatus.FAIL)])
    assert out["status"] != "PASS"
