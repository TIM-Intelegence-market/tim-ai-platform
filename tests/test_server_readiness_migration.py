import json

import pytest

from src.server_readiness.migration import STAGES, migration_progress


EVIDENCE = "sha256:" + "a" * 64


def receipt(stage, status="PASS", evidence_ref=EVIDENCE):
    return {"stage": stage, "status": status, "evidence_ref": evidence_ref}


def all_pass():
    return [receipt(stage) for stage in STAGES]


def test_stages_are_s0_to_s11():
    assert STAGES == tuple(f"S{n}" for n in range(12))


def test_empty_input_is_blocked_at_s0():
    assert migration_progress([]) == {
        "status": "BLOCKED",
        "completed": [],
        "next_stage": "S0",
        "reasons": ["no receipts"],
        "cutover_authorized": False,
    }


def test_s0_only():
    result = migration_progress([receipt("S0")])
    assert result == {
        "status": "BLOCKED",
        "completed": ["S0"],
        "next_stage": "S1",
        "reasons": ["S1: missing receipt"],
        "cutover_authorized": False,
    }


def test_unordered_all_pass():
    result = migration_progress(list(reversed(all_pass())))
    assert result == {
        "status": "PASS",
        "completed": list(STAGES),
        "next_stage": None,
        "reasons": [],
        "cutover_authorized": False,
    }
    assert json.loads(json.dumps(result)) == result


def test_missing_s0_with_s1_pass():
    result = migration_progress([receipt("S1")])
    assert result["status"] == "BLOCKED"
    assert result["completed"] == []
    assert result["next_stage"] == "S0"
    assert result["reasons"] == ["S0: missing receipt", "S1: PASS not counted, prerequisite S0 not passed"]


@pytest.mark.parametrize("status", ["PARTIAL", "FAIL"])
def test_partial_or_fail_mid_chain(status):
    receipts = all_pass()
    receipts[4] = receipt("S4", status)
    result = migration_progress(receipts)
    assert result["status"] == "BLOCKED"
    assert result["completed"] == ["S0", "S1", "S2", "S3"]
    assert result["next_stage"] == "S4"
    assert f"S4: status {status}" in result["reasons"]
    for stage in STAGES[5:]:
        assert f"{stage}: PASS not counted, prerequisite S4 not passed" in result["reasons"]
    assert result["reasons"] == sorted(result["reasons"])


def test_later_pass_after_gap_is_skipped():
    result = migration_progress([receipt("S0"), receipt("S1"), receipt("S3"), receipt("S7")])
    assert result["completed"] == ["S0", "S1"]
    assert result["next_stage"] == "S2"
    assert result["reasons"] == [
        "S2: missing receipt",
        "S3: PASS not counted, prerequisite S2 not passed",
        "S7: PASS not counted, prerequisite S2 not passed",
    ]


def test_safe_stop_takes_precedence_and_keeps_prefix():
    # Choice: SAFE_STOP wins the status, but completed/next_stage still describe
    # the consecutive PASS prefix exactly as they would without the SAFE_STOP.
    receipts = all_pass()
    receipts[6] = receipt("S6", "SAFE_STOP")
    result = migration_progress(list(reversed(receipts)))
    assert result["status"] == "SAFE_STOP"
    assert result["completed"] == ["S0", "S1", "S2", "S3", "S4", "S5"]
    assert result["next_stage"] == "S6"
    assert "S6: status SAFE_STOP" in result["reasons"]
    assert result["cutover_authorized"] is False


def test_safe_stop_beyond_gap_still_wins():
    result = migration_progress([receipt("S0"), receipt("S1", "FAIL"), receipt("S9", "SAFE_STOP")])
    assert result["status"] == "SAFE_STOP"
    assert result["completed"] == ["S0"]
    assert result["next_stage"] == "S1"
    assert result["reasons"] == ["S1: status FAIL", "S9: status SAFE_STOP"]


def test_safe_stop_at_s0():
    result = migration_progress([receipt("S0", "SAFE_STOP")])
    assert result["status"] == "SAFE_STOP"
    assert result["completed"] == []
    assert result["next_stage"] == "S0"


def blocked_shape(result):
    return (
        result["status"] == "BLOCKED"
        and result["completed"] == []
        and result["next_stage"] == "S0"
        and result["cutover_authorized"] is False
    )


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "S0",
        {"stage": "S0"},
        [None],
        ["S0"],
        [{"stage": "S0", "status": "PASS"}],
        [{**receipt("S0"), "extra": 1}],
        [receipt("S0", "pass")],
        [receipt("S0", None)],
        [receipt(0)],
        [receipt(["S0"])],
    ],
)
def test_malformed_input_is_blocked(bad):
    assert blocked_shape(migration_progress(bad))


def test_duplicate_stage_is_blocked():
    result = migration_progress(all_pass() + [receipt("S3")])
    assert blocked_shape(result)
    assert result["reasons"] == ["S3: duplicate receipt"]


@pytest.mark.parametrize("stage", ["S12", "s0", "S-1", "", "S01"])
def test_unknown_stage_is_blocked(stage):
    result = migration_progress(all_pass() + [receipt(stage)])
    assert blocked_shape(result)
    assert result["reasons"] == ["unknown stage"]


@pytest.mark.parametrize(
    "evidence",
    ["a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 65, "sha256:", None, 1],
)
def test_invalid_evidence_is_blocked(evidence):
    receipts = all_pass()
    receipts[2]["evidence_ref"] = evidence
    result = migration_progress(receipts)
    assert blocked_shape(result)
    assert result["reasons"] == ["S2: invalid evidence_ref"]


def test_cutover_is_never_authorized():
    cases = [
        migration_progress(all_pass()),
        migration_progress([]),
        migration_progress(None),
        migration_progress([receipt("S0", "SAFE_STOP")]),
        migration_progress([receipt("S0")]),
    ]
    assert all(result["cutover_authorized"] is False for result in cases)
