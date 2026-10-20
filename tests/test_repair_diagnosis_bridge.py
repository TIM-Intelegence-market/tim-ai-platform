import json

import pytest

from src.repair_diagnosis import bridge
from src.repair_diagnosis.package import build_request


def _request():
    return build_request({
        "incident_id": "inc-1",
        "category": "network",
        "component": "collector",
        "fingerprint": "a" * 64,
        "normalized_error": "TimeoutError: network timeout",
        "stack": "line 1",
        "reproduction": None,
        "code_paths": [],
        "tests": [],
    })


@pytest.fixture(autouse=True)
def _fake_parse(monkeypatch):
    # Isolate the bridge from the response schema: valid iff JSON object with 'hypothesis'.
    def fake_parse(raw, request):
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            return {"status": "INVALID"}
        if isinstance(data, dict) and "hypothesis" in data:
            return {"status": "VALID", "data": data}
        return {"status": "INVALID"}

    monkeypatch.setattr(bridge, "parse_response", fake_parse)


def _good(_payload):
    return json.dumps({"hypothesis": "retry budget too low"})


def _timeout(_payload):
    raise TimeoutError("slow")


def test_second_provider_proposal_after_timeout():
    result = bridge.request_diagnosis(_request(), [("a", _timeout), ("b", _good)])
    assert result["outcome"] == "PROPOSAL"
    assert result["provider"] == "b"
    assert [x["status"] for x in result["attempts"]] == ["timeout", "VALID"]
    assert result["next_action"] == "LOCAL_REPRODUCTION_AND_GATES"
    assert result["can_mark_fixed"] is False


def test_all_providers_fail():
    def unavailable(_p):
        raise bridge.ProviderUnavailable()

    def boom(_p):
        raise RuntimeError("x")

    providers = [
        ("p1", unavailable),
        ("p2", boom),
        ("p3", lambda _p: "not json"),
        ("p4", lambda _p: 42),
    ]
    result = bridge.request_diagnosis(_request(), providers)
    assert result["outcome"] == "PROVIDER_FAILED"
    assert result["next_action"] == "MANUAL_BRIDGE"
    assert result["provider"] is None
    assert [x["status"] for x in result["attempts"]] == [
        "unavailable", "error", "INVALID", "error",
    ]


def test_exception_text_not_stored():
    secret = "tok" + "en=abc"

    def leaky(_p):
        raise RuntimeError(secret)

    result = bridge.request_diagnosis(_request(), [("p1", leaky)])
    assert secret not in repr(result)


def test_rejects_changed_schema_without_calling_provider():
    calls = []
    request = _request()
    request["schema"] = "other"
    result = bridge.request_diagnosis(request, [("p1", lambda p: calls.append(p))])
    assert result["outcome"] == "REQUEST_REJECTED"
    assert result["next_action"] == "FIX_REQUEST"
    assert result["attempts"] == []
    assert calls == []


def test_empty_provider_list_raises():
    with pytest.raises(ValueError):
        bridge.request_diagnosis(_request(), [])


def test_bad_provider_name_raises():
    with pytest.raises(ValueError):
        bridge.request_diagnosis(_request(), [("Bad Name", _good)])


def test_request_sha256_stable_for_key_order():
    assert bridge.request_sha256({"a": 1, "b": 2}) == bridge.request_sha256({"b": 2, "a": 1})


def test_fixed_claim_never_grants_fixed_authority():
    def claims(_p):
        return json.dumps({"hypothesis": "task is FIXED"})

    result = bridge.request_diagnosis(_request(), [("p1", claims)])
    assert result["outcome"] == "PROPOSAL"
    assert result["can_mark_fixed"] is False
