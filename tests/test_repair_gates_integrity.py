import pytest

from src.repair_gates import integrity
from src.repair_gates.aggregate import decide
from src.repair_gates.integrity import (
    db_integrity,
    determinism,
    lookahead_safety,
    queue_integrity,
)
from src.repair_gates.result import GateResult, GateStatus

DIGEST = "a" * 64
OTHER = "b" * 64
CUTOFF = "2026-01-01T12:00:00+00:00"
TEST_DB = "postgresql://127.0.0.1:5432/tim_test"
RUNTIME_DB = "postgresql://127.0.0.1:5432/tim_runtime"


def _queue(pending=1, attempts=None):
    return {"pending": pending, "attempts": {"j1": 1} if attempts is None else attempts}


def _assert_pass(result, gate):
    assert isinstance(result, GateResult)
    assert result.gate == gate
    assert result.status is GateStatus.PASS


def _assert_fail(result, gate, fragment=""):
    assert isinstance(result, GateResult)
    assert result.gate == gate
    assert result.status is GateStatus.FAIL
    assert result.reason
    assert fragment in result.reason


# determinism

def test_determinism_pass_on_equal_digests():
    _assert_pass(determinism(DIGEST, DIGEST), "determinism")


def test_determinism_fail_on_different_digests():
    _assert_fail(determinism(DIGEST, OTHER), "determinism")


def test_determinism_fail_on_uppercase_hex():
    _assert_fail(determinism("A" * 64, "A" * 64), "determinism")


@pytest.mark.parametrize("digest", ["a" * 63, "a" * 65, "g" * 64, "", None, 42, b"a" * 64,
                                    "a" * 64 + "\n"])
def test_determinism_fail_on_invalid_digest(digest):
    _assert_fail(determinism(digest, digest), "determinism")
    _assert_fail(determinism(DIGEST, digest), "determinism")


# lookahead_safety

def test_lookahead_pass_when_all_events_at_or_before_cutoff():
    events = [{"timestamp": "2026-01-01T11:59:59+00:00"}, {"timestamp": CUTOFF}]
    _assert_pass(lookahead_safety(events, CUTOFF), "lookahead_safety")


def test_lookahead_pass_on_empty_events():
    _assert_pass(lookahead_safety([], CUTOFF), "lookahead_safety")


def test_lookahead_fail_names_number_of_late_events():
    events = [
        {"timestamp": "2026-01-01T11:00:00+00:00"},
        {"timestamp": "2026-01-01T12:00:01+00:00"},
        {"timestamp": "2026-01-01T13:00:00+01:00"},  # equal to cutoff, not late
        {"timestamp": "2026-01-02T00:00:00+00:00"},
    ]
    _assert_fail(lookahead_safety(events, CUTOFF), "lookahead_safety", "2")


@pytest.mark.parametrize("events", [None, "events", ({"timestamp": CUTOFF},), {"timestamp": CUTOFF}])
def test_lookahead_fail_on_non_list(events):
    _assert_fail(lookahead_safety(events, CUTOFF), "lookahead_safety")


@pytest.mark.parametrize("event", [{}, {"ts": CUTOFF}, "event", {"timestamp": None},
                                   {"timestamp": "not a time"},
                                   {"timestamp": "2026-01-01T11:00:00"}])
def test_lookahead_fail_on_invalid_event(event):
    _assert_fail(lookahead_safety([event], CUTOFF), "lookahead_safety")


@pytest.mark.parametrize("cutoff", ["2026-01-01T12:00:00", "garbage", None, 0])
def test_lookahead_fail_on_invalid_or_naive_cutoff(cutoff):
    events = [{"timestamp": "2026-01-01T11:00:00+00:00"}]
    _assert_fail(lookahead_safety(events, cutoff), "lookahead_safety")


# db_integrity

def test_db_integrity_pass_on_isolated_database():
    _assert_pass(db_integrity(TEST_DB, RUNTIME_DB), "db_integrity")


def test_db_integrity_fail_on_same_database():
    _assert_fail(db_integrity(RUNTIME_DB, RUNTIME_DB), "db_integrity", "database not isolated")


def test_db_integrity_fail_on_invalid_input():
    _assert_fail(db_integrity(None, RUNTIME_DB), "db_integrity", "invalid database guard input")


def test_db_integrity_follows_database_guard(monkeypatch):
    monkeypatch.setattr(integrity, "database_guard", lambda *_: (False, "guard says no"))
    _assert_fail(db_integrity(TEST_DB, RUNTIME_DB), "db_integrity", "guard says no")
    monkeypatch.setattr(integrity, "database_guard", lambda *_: (True, "isolated"))
    _assert_pass(db_integrity("x", "y"), "db_integrity")


# queue_integrity

def test_queue_pass_when_attempts_kept_or_grown():
    before = _queue(pending=3, attempts={"j1": 1, "j2": 0})
    after = _queue(pending=2, attempts={"j1": 2, "j2": 0, "j3": 1})
    _assert_pass(queue_integrity(before, after), "queue_integrity")


def test_queue_pass_when_empty_queue_stays_empty():
    _assert_pass(queue_integrity(_queue(0, {}), _queue(0, {})), "queue_integrity")


def test_queue_fail_when_cleared_globally():
    _assert_fail(queue_integrity(_queue(5), _queue(0)), "queue_integrity",
                 "queue cleared globally")


def test_queue_fail_when_attempt_id_missing():
    _assert_fail(queue_integrity(_queue(attempts={"j1": 1, "j2": 1}), _queue(attempts={"j1": 1})),
                 "queue_integrity", "attempts reset")


def test_queue_fail_when_attempt_count_lower():
    _assert_fail(queue_integrity(_queue(attempts={"j1": 3}), _queue(attempts={"j1": 2})),
                 "queue_integrity", "attempts reset")


@pytest.mark.parametrize("snapshot", [
    None,
    [],
    {"attempts": {}},
    {"pending": 1},
    _queue(pending=True),
    _queue(pending=-1),
    _queue(pending=1.0),
    _queue(pending="1"),
    {"pending": 1, "attempts": []},
    _queue(attempts={"j1": True}),
    _queue(attempts={"j1": -1}),
    _queue(attempts={"j1": 1.5}),
    _queue(attempts={1: 1}),
])
def test_queue_fail_on_invalid_shape(snapshot):
    _assert_fail(queue_integrity(snapshot, _queue()), "queue_integrity", "invalid")
    _assert_fail(queue_integrity(_queue(), snapshot), "queue_integrity", "invalid")


# aggregate

def _all_passing():
    return [
        determinism(DIGEST, DIGEST),
        lookahead_safety([{"timestamp": CUTOFF}], CUTOFF),
        db_integrity(TEST_DB, RUNTIME_DB),
        queue_integrity(_queue(), _queue()),
    ]


GATES = ["determinism", "lookahead_safety", "db_integrity", "queue_integrity"]


def test_aggregate_pass_when_all_integrity_gates_pass():
    assert decide(GATES, _all_passing())["status"] == "PASS"


@pytest.mark.parametrize("index,failing", [
    (0, lambda: determinism(DIGEST, OTHER)),
    (1, lambda: lookahead_safety([{"timestamp": "2027-01-01T00:00:00+00:00"}], CUTOFF)),
    (2, lambda: db_integrity(RUNTIME_DB, RUNTIME_DB)),
    (3, lambda: queue_integrity(_queue(2), _queue(0))),
])
def test_aggregate_safe_stop_when_one_integrity_gate_fails(index, failing):
    results = _all_passing()
    results[index] = failing()
    verdict = decide(GATES, results)
    assert verdict["status"] == "SAFE_STOP"
    assert verdict["escalate"] is True
