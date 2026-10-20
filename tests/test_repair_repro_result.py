import json

import pytest

from src.repair_repro import ReproResult, ReproStatus


def test_round_trip_and_json_are_deterministic():
    result = ReproResult(
        case_id="case-1",
        status=ReproStatus.REPRODUCED,
        reason="reproduced offline",
        evidence_refs=("log.txt",),
    )
    rebuilt = ReproResult.from_dict(result.to_dict())
    assert rebuilt == result
    assert json.dumps(result.to_dict(), sort_keys=True) == json.dumps(
        rebuilt.to_dict(), sort_keys=True
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"case_id": ""},
        {"status": "REPRODUCED"},
        {"status": ReproStatus.REPRODUCED},
        {"status": ReproStatus.INSUFFICIENT_EVIDENCE},
        {"production_touched": True},
        {"real_process_calls": -1},
        {"real_process_calls": True},
        {"database_connections": -1},
        {"database_connections": False},
        {"reason": 1},
        {"evidence_refs": ["ref"]},
        {"evidence_refs": (1,)},
    ],
)
def test_rejects_invalid_constructor_values(kwargs):
    base = {
        "case_id": "case-1",
        "status": ReproStatus.NOT_REPRODUCED,
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        ReproResult(**base)


@pytest.mark.parametrize(
    "data",
    [
        {"status": "NOT_REPRODUCED"},
        {"case_id": "case-1"},
        {"case_id": "case-1", "status": "UNKNOWN"},
        {"case_id": "case-1", "status": 1},
        {"case_id": "case-1", "status": "NOT_REPRODUCED", "extra": 1},
        {"case_id": "case-1", "status": "NOT_REPRODUCED", "reason": 1},
        {
            "case_id": "case-1",
            "status": "NOT_REPRODUCED",
            "evidence_refs": "ref",
        },
        {
            "case_id": "case-1",
            "status": "NOT_REPRODUCED",
            "evidence_refs": [1],
        },
        {
            "case_id": "case-1",
            "status": "NOT_REPRODUCED",
            "production_touched": 0,
        },
        {
            "case_id": "case-1",
            "status": "NOT_REPRODUCED",
            "real_process_calls": True,
        },
        {
            "case_id": "case-1",
            "status": "NOT_REPRODUCED",
            "database_connections": -1,
        },
    ],
)
def test_from_dict_rejects_invalid_data(data):
    with pytest.raises(ValueError):
        ReproResult.from_dict(data)


def test_from_dict_rejects_non_mapping():
    with pytest.raises(ValueError):
        ReproResult.from_dict([])
