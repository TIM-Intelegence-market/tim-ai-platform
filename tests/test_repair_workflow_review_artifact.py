import copy
import hashlib
import json

import pytest

from src.repair_workflow.review_artifact import build_review_artifact


BASE = {
    "incident_id": "INC-1",
    "task_id": "TASK-1",
    "reproduction_ref": {"status": "REPRODUCED", "ref": "case-1"},
    "patch_sha256": "a" * 64,
    "diff_check": {"ok": True},
    "test_reports": {"unit": "PASS"},
    "gate_decision": {"status": "PASS"},
}


def build(**changes):
    values = copy.deepcopy(BASE)
    values.update(changes)
    return build_review_artifact(**values)


def test_ready_artifact_has_expected_verdict_and_hash():
    artifact = build()

    assert artifact["schema_version"] == 1
    assert artifact["verdict"] == "READY_FOR_HUMAN_REVIEW"
    expected = dict(artifact)
    del expected["artifact_sha256"]
    encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    assert artifact["artifact_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()


def test_not_reproduced_is_blocked():
    assert build(reproduction_ref={"status": "NOT_REPRODUCED"})["verdict"] == "BLOCKED"


def test_failed_diff_is_blocked():
    assert build(diff_check={"ok": False})["verdict"] == "BLOCKED"


def test_failing_test_report_is_blocked():
    assert build(test_reports={"unit": "FAIL"})["verdict"] == "BLOCKED"


def test_failed_gate_is_blocked():
    assert build(gate_decision={"status": "FAIL"})["verdict"] == "BLOCKED"


@pytest.mark.parametrize(
    "changes",
    [
        {"incident_id": ""},
        {"task_id": ""},
        {"patch_sha256": "A" * 64},
        {"patch_sha256": "a" * 63},
        {"reproduction_ref": {}},
        {"reproduction_ref": {"status": ""}},
        {"diff_check": {}},
        {"diff_check": {"ok": "true"}},
        {"test_reports": {}},
        {"test_reports": {"unit": False}},
        {"gate_decision": {}},
        {"gate_decision": {"status": 1}},
    ],
)
def test_invalid_input_raises_value_error(changes):
    with pytest.raises(ValueError):
        build(**changes)


def test_equal_inputs_are_deterministic():
    assert build() == build()


@pytest.mark.parametrize(
    "field, value",
    [
        ("incident_id", "INC-2"),
        ("task_id", "TASK-2"),
        ("reproduction_ref", {"status": "REPRODUCED", "ref": "case-2"}),
        ("patch_sha256", "b" * 64),
        ("diff_check", {"ok": False}),
        ("test_reports", {"unit": "FAIL"}),
        ("gate_decision", {"status": "FAIL"}),
    ],
)
def test_changed_input_changes_artifact_hash(field, value):
    assert build(**{field: value})["artifact_sha256"] != build()["artifact_sha256"]


def test_verdict_is_never_fixed():
    assert build()["verdict"] != "FIXED"
    assert build(reproduction_ref={"status": "NOT_REPRODUCED"})["verdict"] != "FIXED"


def test_inputs_are_not_mutated():
    values = copy.deepcopy(BASE)
    original = copy.deepcopy(values)

    build_review_artifact(**values)

    assert values == original
