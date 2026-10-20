import json

import pytest

from src.repair_diagnosis.package import EXTENDED_KEYS, build_request, parse_response

OLD_KEYS = {
    "status",
    "authority",
    "can_mark_fixed",
    "reasons",
    "hypothesis",
    "proposed_actions",
    "confidence",
}
DEFAULTS = {"reproduction_proposal": None, "minimal_fix": None, "risks": [], "required_tests": []}
SECRET = "pass" + "word=" + "hunter2x"


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


@pytest.fixture
def base():
    return {"incident_id": "inc-1", "hypothesis": "h", "proposed_actions": ["a"], "confidence": 0.5}


def test_without_extended_has_exactly_old_keys(request_, base):
    result = parse_response(json.dumps(base), request_)
    assert result["status"] == "VALID"
    assert set(result) == OLD_KEYS


def test_extended_field_without_flag_is_unknown(request_, base):
    result = parse_response(json.dumps({**base, "risks": ["r"]}), request_)
    assert result["status"] == "INVALID"
    assert "unknown_keys" in result["reasons"]
    assert set(result) == OLD_KEYS


def test_old_answer_with_extended_gets_defaults(request_, base):
    result = parse_response(json.dumps(base), request_, extended=True)
    assert result["status"] == "VALID"
    assert set(result) == OLD_KEYS | set(EXTENDED_KEYS)
    assert {key: result[key] for key in EXTENDED_KEYS} == DEFAULTS
    assert result["can_mark_fixed"] is False


def test_full_extended_answer(request_, base):
    raw = {
        **base,
        "reproduction_proposal": "run x",
        "minimal_fix": "retry once",
        "risks": ["r1", "r2"],
        "required_tests": ["tests/test_x.py"],
    }
    result = parse_response(json.dumps(raw), request_, extended=True)
    assert result["status"] == "VALID"
    assert result["reproduction_proposal"] == "run x"
    assert result["minimal_fix"] == "retry once"
    assert result["risks"] == ["r1", "r2"]
    assert result["required_tests"] == ["tests/test_x.py"]
    assert result["can_mark_fixed"] is False


def test_risks_must_be_list(request_, base):
    result = parse_response(json.dumps({**base, "risks": "x"}), request_, extended=True)
    assert result["status"] == "INVALID"
    assert "invalid_risks" in result["reasons"]
    assert {key: result[key] for key in EXTENDED_KEYS} == DEFAULTS


def test_too_many_required_tests(request_, base):
    raw = {**base, "required_tests": [f"t{i}" for i in range(21)]}
    result = parse_response(json.dumps(raw), request_, extended=True)
    assert result["status"] == "INVALID"
    assert "invalid_required_tests" in result["reasons"]


def test_empty_minimal_fix(request_, base):
    result = parse_response(json.dumps({**base, "minimal_fix": ""}), request_, extended=True)
    assert result["status"] == "INVALID"
    assert "invalid_minimal_fix" in result["reasons"]


def test_secret_in_minimal_fix_is_redacted(request_, base):
    raw = {**base, "minimal_fix": "set " + SECRET}
    result = parse_response(json.dumps(raw), request_, extended=True)
    assert result["status"] == "VALID"
    assert "hunter2x" not in result["minimal_fix"]
    assert "hunter2x" not in json.dumps(result)


def test_invalid_json_with_extended_has_defaults(request_):
    result = parse_response("{bad", request_, extended=True)
    assert result["status"] == "INVALID"
    assert result["reasons"] == ["invalid_json"]
    assert {key: result[key] for key in EXTENDED_KEYS} == DEFAULTS


def test_not_object_with_extended_has_defaults(request_):
    result = parse_response("[1]", request_, extended=True)
    assert result["reasons"] == ["response_not_object"]
    assert {key: result[key] for key in EXTENDED_KEYS} == DEFAULTS


def test_forbidden_key_with_extended(request_, base):
    result = parse_response(json.dumps({**base, "status": "FIXED"}), request_, extended=True)
    assert result["status"] == "INVALID"
    assert "forbidden_key" in result["reasons"]
    assert result["can_mark_fixed"] is False
