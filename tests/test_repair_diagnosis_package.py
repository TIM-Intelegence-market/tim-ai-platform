import json

import pytest

from src.repair_diagnosis import package

SECRET = "SECRET-TOKEN-123"


@pytest.fixture(autouse=True)
def fake_redact(monkeypatch):
    monkeypatch.setattr(package, "redact_text", lambda text: text.replace(SECRET, "[REDACTED]"))


def make_incident(**overrides):
    incident = {
        "incident_id": "inc-1",
        "category": "test_failure",
        "component": "bugfixer",
        "fingerprint": "a" * 64,
        "normalized_error": "ValueError: boom",
        "stack": "line1\nline2",
        "reproduction": {"cmd": "pytest", "env": ["x"]},
        "code_paths": ["src/a.py"],
        "tests": ["tests/test_a.py"],
    }
    incident.update(overrides)
    return incident


def make_raw(**overrides):
    raw = {
        "incident_id": "inc-1",
        "hypothesis": "off by one",
        "proposed_actions": ["fix index"],
        "confidence": 0.5,
    }
    raw.update(overrides)
    return raw


def test_build_request_shape():
    request = package.build_request(make_incident())
    assert request["schema"] == "tim.diagnosis.request.v1"
    assert request["incident_id"] == "inc-1"
    assert request["reproduction"] == {"cmd": "pytest", "env": ["x"]}
    assert request["safety_constraints"] == [
        "proposal_only",
        "no_fixed_authority",
        "no_live_trading",
        "no_production_mutation",
    ]


def test_redacts_token_in_stack():
    request = package.build_request(make_incident(stack=f"token={SECRET}"))
    assert SECRET not in json.dumps(request)
    assert request["stack"] == "token=[REDACTED]"


def test_redacts_token_in_reproduction_and_lists():
    request = package.build_request(
        make_incident(reproduction={"k": [SECRET]}, code_paths=[SECRET], tests=[SECRET])
    )
    assert SECRET not in json.dumps(request)


def test_lists_limited_to_twenty():
    request = package.build_request(make_incident(code_paths=[f"p{i}" for i in range(30)]))
    assert len(request["code_paths"]) == 20


def test_truncation_keeps_stack_end():
    stack = "A" * 5000 + "THE-END"
    request = package.build_request(make_incident(stack=stack), max_chars=1000)
    assert request["stack"].endswith("THE-END")
    assert len(request["stack"]) < len(stack)
    assert len(json.dumps(request)) <= 1000


def test_truncation_shortens_normalized_error_after_stack():
    incident = make_incident(normalized_error="E" * 5000, stack="S" * 100)
    request = package.build_request(incident, max_chars=1000)
    assert request["stack"] == ""
    assert 0 < len(request["normalized_error"]) < 5000
    assert len(json.dumps(request)) <= 1000


def test_size_error_when_request_cannot_fit():
    with pytest.raises(ValueError):
        package.build_request(make_incident(), max_chars=50)


@pytest.mark.parametrize("key", ["incident_id", "category", "component", "normalized_error"])
@pytest.mark.parametrize("bad", [None, "", "  ", 5])
def test_required_fields_rejected(key, bad):
    with pytest.raises(ValueError):
        package.build_request(make_incident(**{key: bad}))


@pytest.mark.parametrize("bad", ["a" * 63, "A" * 64, "g" * 64, None, 5])
def test_invalid_fingerprint_rejected(bad):
    with pytest.raises(ValueError):
        package.build_request(make_incident(fingerprint=bad))


def test_invalid_reproduction_and_lists_rejected():
    with pytest.raises(ValueError):
        package.build_request(make_incident(reproduction="x"))
    with pytest.raises(ValueError):
        package.build_request(make_incident(tests=[1]))
    with pytest.raises(ValueError):
        package.build_request(make_incident(code_paths="a"))


def test_valid_round_trip_from_dict_and_json():
    request = package.build_request(make_incident())
    for raw in (make_raw(), json.dumps(make_raw())):
        result = package.parse_response(raw, request)
        assert result == {
            "status": "VALID",
            "authority": "PROPOSAL_ONLY",
            "can_mark_fixed": False,
            "reasons": [],
            "hypothesis": "off by one",
            "proposed_actions": ["fix index"],
            "confidence": 0.5,
        }


def test_response_strings_are_redacted():
    request = package.build_request(make_incident())
    result = package.parse_response(
        make_raw(hypothesis=f"leak {SECRET}", proposed_actions=[SECRET]), request
    )
    assert result["status"] == "VALID"
    assert result["hypothesis"] == "leak [REDACTED]"
    assert result["proposed_actions"] == ["[REDACTED]"]


@pytest.mark.parametrize(
    "raw",
    [
        "{not json",
        "[]",
        None,
        5,
        make_raw(incident_id="other"),
        make_raw(incident_id=None),
        make_raw(hypothesis=""),
        make_raw(hypothesis=3),
        make_raw(proposed_actions="fix"),
        make_raw(proposed_actions=[1]),
        make_raw(proposed_actions=["a"] * 11),
        make_raw(confidence=True),
        make_raw(confidence=1.5),
        make_raw(confidence=-0.1),
        make_raw(confidence="0.5"),
        make_raw(extra="x"),
        make_raw(status="FIXED"),
        make_raw(mark_fixed=True),
    ],
)
def test_invalid_responses(raw):
    request = package.build_request(make_incident())
    result = package.parse_response(raw, request)
    assert result["status"] == "INVALID"
    assert result["reasons"]
    assert result["authority"] == "PROPOSAL_ONLY"
    assert result["can_mark_fixed"] is False


def test_missing_keys_invalid():
    request = package.build_request(make_incident())
    result = package.parse_response({"incident_id": "inc-1"}, request)
    assert result["status"] == "INVALID"


def test_can_mark_fixed_always_false():
    request = package.build_request(make_incident())
    for raw in (make_raw(), make_raw(mark_fixed=True), "nope", None):
        assert package.parse_response(raw, request)["can_mark_fixed"] is False
