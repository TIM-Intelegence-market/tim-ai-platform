import json

import pytest

from src.repair_diagnosis.bridge import request_diagnosis
from src.repair_diagnosis.package import build_request
from src.repair_diagnosis.store import load_diagnosis, save_diagnosis

RECORDED_AT = "2026-09-09T00:00:00+00:00"
SECRET = "pass" + "word=" + "hunter2x"
BASE = {"incident_id": "inc-1", "hypothesis": "h", "proposed_actions": ["a"], "confidence": 0.5}
EXTENDED = {
    **BASE,
    "minimal_fix": "retry once",
    "risks": ["r"],
    "required_tests": ["tests/test_x.py"],
    "reproduction_proposal": "run x",
}


@pytest.fixture
def request_():
    return build_request(
        {
            "incident_id": "inc-1",
            "category": "network",
            "component": "collector",
            "fingerprint": "a" * 64,
            "normalized_error": "TimeoutError: x",
        }
    )


def provider_for(answer):
    def provider(payload):
        return json.dumps(answer)

    return provider


def test_extended_answer_without_flag_fails(request_):
    result = request_diagnosis(request_, [("fake", provider_for(EXTENDED))])
    assert result["outcome"] == "PROVIDER_FAILED"
    assert result["attempts"] == [{"provider": "fake", "status": "INVALID"}]
    assert result["can_mark_fixed"] is False


def test_extended_answer_with_flag_is_proposal(request_):
    result = request_diagnosis(request_, [("fake", provider_for(EXTENDED))], extended=True)
    assert result["outcome"] == "PROPOSAL"
    assert result["result"]["minimal_fix"] == "retry once"
    assert result["can_mark_fixed"] is False


def test_extended_fields_are_saved_and_loaded(tmp_path, request_):
    result = request_diagnosis(request_, [("fake", provider_for(EXTENDED))], extended=True)
    path = save_diagnosis(tmp_path, request_, result, recorded_at=RECORDED_AT)
    body = load_diagnosis(path)
    assert body["minimal_fix"] == "retry once"
    assert body["risks"] == ["r"]
    assert body["required_tests"] == ["tests/test_x.py"]
    assert body["reproduction_proposal"] == "run x"
    assert body["can_mark_fixed"] is False


def test_plain_answer_body_has_no_extended_fields(tmp_path, request_):
    result = request_diagnosis(request_, [("fake", provider_for(BASE))])
    assert result["outcome"] == "PROPOSAL"
    body = load_diagnosis(save_diagnosis(tmp_path, request_, result, recorded_at=RECORDED_AT))
    for key in ("minimal_fix", "risks", "required_tests", "reproduction_proposal"):
        assert key not in body
    assert body["can_mark_fixed"] is False


def test_secret_in_risks_is_not_saved(tmp_path, request_):
    answer = {**EXTENDED, "risks": ["leaks " + SECRET]}
    result = request_diagnosis(request_, [("fake", provider_for(answer))], extended=True)
    assert result["outcome"] == "PROPOSAL"
    path = save_diagnosis(tmp_path, request_, result, recorded_at=RECORDED_AT)
    assert b"hunter2x" not in path.read_bytes()
    assert load_diagnosis(path)["can_mark_fixed"] is False


def test_store_redacts_extended_fields_directly(tmp_path, request_):
    bridge_result = {
        "outcome": "PROPOSAL",
        "provider": "fake",
        "attempts": [{"provider": "fake", "status": "VALID"}],
        "result": {**EXTENDED, "risks": [SECRET], "minimal_fix": SECRET},
    }
    path = save_diagnosis(tmp_path, request_, bridge_result, recorded_at=RECORDED_AT)
    assert b"hunter2x" not in path.read_bytes()
