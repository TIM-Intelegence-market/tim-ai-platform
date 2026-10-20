import pytest

from src.repair_workflow import candidate


class FakeRepro:
    def __init__(self, status):
        self.status = status

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or "status" not in data:
            raise ValueError("bad")
        return cls(data["status"])


@pytest.fixture(autouse=True)
def fake_repro(monkeypatch):
    monkeypatch.setattr(candidate, "ReproResult", FakeRepro)


def make(**over):
    rec = {
        "incident_id": "inc-1",
        "task_id": "task-1",
        "reproduction": {"status": "REPRODUCED"},
        "diff_check": {"ok": True},
        "gate_decision": {"status": "PASS"},
    }
    rec.update(over)
    return rec


def test_ready_for_review():
    r = candidate.candidate_status(make())
    assert r["status"] == "READY_FOR_REVIEW"
    assert r["reasons"] == ["ready for review"]


def test_non_dict_is_blocked():
    for bad in (None, [], "x", 5):
        assert candidate.candidate_status(bad)["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "key", ["incident_id", "task_id", "reproduction", "diff_check", "gate_decision"]
)
def test_missing_key_is_blocked(key):
    rec = make()
    del rec[key]
    assert candidate.candidate_status(rec)["status"] == "BLOCKED"


def test_empty_incident_id_is_blocked():
    assert candidate.candidate_status(make(incident_id=""))["status"] == "BLOCKED"


def test_invalid_waiver_is_blocked():
    assert candidate.candidate_status(make(reproduction_waiver=""))["status"] == "BLOCKED"


def test_reproduction_rejected_by_from_dict_is_blocked():
    r = candidate.candidate_status(make(reproduction={}))
    assert r["status"] == "BLOCKED"


def test_safe_stop():
    r = candidate.candidate_status(make(gate_decision={"status": "SAFE_STOP"}))
    assert r["status"] == "SAFE_STOP"


def test_non_pass_gate_is_failed():
    r = candidate.candidate_status(make(gate_decision={"status": "FAIL"}))
    assert r["status"] == "FAILED"


def test_bad_diff_is_failed():
    assert candidate.candidate_status(make(diff_check={"ok": False}))["status"] == "FAILED"
    assert candidate.candidate_status(make(diff_check={}))["status"] == "FAILED"


def test_safe_stop_beats_bad_diff():
    r = candidate.candidate_status(
        make(gate_decision={"status": "SAFE_STOP"}, diff_check={"ok": False})
    )
    assert r["status"] == "SAFE_STOP"


def test_bad_diff_beats_not_reproduced():
    r = candidate.candidate_status(
        make(diff_check={"ok": False}, reproduction={"status": "NOT_REPRODUCED"})
    )
    assert r["status"] == "FAILED"


def test_not_reproduced_is_blocked():
    r = candidate.candidate_status(make(reproduction={"status": "NOT_REPRODUCED"}))
    assert r["status"] == "BLOCKED"


def test_insufficient_evidence_without_waiver_is_blocked():
    r = candidate.candidate_status(make(reproduction={"status": "INSUFFICIENT_EVIDENCE"}))
    assert r["status"] == "BLOCKED"


def test_insufficient_evidence_with_waiver_is_ready():
    r = candidate.candidate_status(
        make(
            reproduction={"status": "INSUFFICIENT_EVIDENCE"},
            reproduction_waiver="approved by owner",
        )
    )
    assert r["status"] == "READY_FOR_REVIEW"
    assert r["reasons"] == ["ready for review with reproduction waiver"]


def test_from_dict_unexpected_exception_does_not_raise(monkeypatch):
    class Boom:
        @classmethod
        def from_dict(cls, data):
            raise RuntimeError("x")

    monkeypatch.setattr(candidate, "ReproResult", Boom)
    assert candidate.candidate_status(make())["status"] == "BLOCKED"


def test_never_fixed_or_auto_merge():
    records = [
        None,
        make(),
        make(gate_decision={"status": "SAFE_STOP"}),
        make(gate_decision={"status": "FAIL"}),
        make(diff_check={"ok": False}),
        make(reproduction={"status": "NOT_REPRODUCED"}),
        make(reproduction={"status": "INSUFFICIENT_EVIDENCE"}, reproduction_waiver="w"),
    ]
    for rec in records:
        r = candidate.candidate_status(rec)
        assert r["fixed"] is False
        assert r["auto_merge"] is False
        assert r["reasons"] == sorted(r["reasons"])
        assert r["status"] in {"READY_FOR_REVIEW", "BLOCKED", "FAILED", "SAFE_STOP"}
