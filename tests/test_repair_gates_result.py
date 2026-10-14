import json

import pytest

from src.repair_gates import GateResult, GateStatus


def test_round_trip() -> None:
    result = GateResult(
        gate="lint",
        status=GateStatus.PASS,
        evidence_refs=("report.json",),
        git_sha="abc123",
        config_hash="cfg123",
    )
    assert GateResult.from_dict(result.to_dict()) == result


def test_equal_results_have_identical_json() -> None:
    left = GateResult("tests", GateStatus.PASS, evidence_refs=("a", "b"))
    right = GateResult("tests", GateStatus.PASS, evidence_refs=("a", "b"))
    assert json.dumps(left.to_dict(), sort_keys=True) == json.dumps(
        right.to_dict(), sort_keys=True
    )


@pytest.mark.parametrize(
    "data",
    [
        {"gate": "g", "status": "pass", "unexpected": 1},
        {"status": "pass"},
        {"gate": "", "status": "pass"},
        {"gate": "g", "status": "unknown"},
        {"gate": 1, "status": "pass"},
        {"gate": "g", "status": 1},
        {"gate": "g", "status": "pass", "reason": 1},
        {"gate": "g", "status": "pass", "evidence_refs": "ref"},
        {"gate": "g", "status": "pass", "evidence_refs": [1]},
        {"gate": "g", "status": "pass", "git_sha": 1},
        {"gate": "g", "status": "pass", "config_hash": 1},
        {"gate": "g", "status": "fail"},
        {"gate": "g", "status": "blocked", "reason": ""},
        {"gate": "g", "status": "skip", "reason": ""},
    ],
)
def test_from_dict_rejects_invalid_data(data: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        GateResult.from_dict(data)


def test_from_dict_rejects_non_mapping() -> None:
    with pytest.raises(ValueError):
        GateResult.from_dict([])
