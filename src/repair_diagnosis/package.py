"""Proposal-only diagnosis request/response contract."""
import json
import math
import re

from src.bugfixer.processing import redact_text

REQUEST_SCHEMA = "tim.diagnosis.request.v1"
SAFETY_CONSTRAINTS = [
    "proposal_only",
    "no_fixed_authority",
    "no_live_trading",
    "no_production_mutation",
]
MAX_LIST_ITEMS = 20
MAX_ACTIONS = 10

_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
_RESPONSE_KEYS = frozenset({"incident_id", "hypothesis", "proposed_actions", "confidence"})
_FORBIDDEN_KEYS = ("status", "mark_fixed")


def _required_str(incident, key):
    value = incident.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _redact_value(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("reproduction keys must be strings")
            result[redact_text(key)] = _redact_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("reproduction contains an unsupported value type")


def _str_list(incident, key):
    value = incident.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return [redact_text(item) for item in value[:MAX_LIST_ITEMS]]


def _size(request):
    return len(json.dumps(request))


def _shorten(request, field, max_chars, keep_end, minimum):
    """Shorten request[field] to the longest slice that fits; False if none does."""
    text = request[field]

    def fits(length):
        request[field] = text[len(text) - length:] if keep_end else text[:length]
        return _size(request) <= max_chars

    if len(text) < minimum or not fits(minimum):
        return False
    low, high = minimum, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if fits(mid):
            low = mid
        else:
            high = mid - 1
    fits(low)
    return True


def build_request(incident, *, max_chars=20000):
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer")
    if not isinstance(incident, dict):
        raise ValueError("incident must be a dict")

    incident_id = _required_str(incident, "incident_id")
    category = _required_str(incident, "category")
    component = _required_str(incident, "component")
    normalized_error = _required_str(incident, "normalized_error")

    fingerprint = incident.get("fingerprint")
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ValueError("fingerprint must be 64 lowercase hex characters")

    stack = incident.get("stack")
    if stack is None:
        stack = ""
    if not isinstance(stack, str):
        raise ValueError("stack must be a string")

    reproduction = incident.get("reproduction")
    if reproduction is not None and not isinstance(reproduction, dict):
        raise ValueError("reproduction must be a dict or None")

    request = {
        "schema": REQUEST_SCHEMA,
        "incident_id": redact_text(incident_id),
        "category": redact_text(category),
        "component": redact_text(component),
        "fingerprint": fingerprint,
        "normalized_error": redact_text(normalized_error),
        "stack": redact_text(stack),
        "reproduction": None if reproduction is None else _redact_value(reproduction),
        "code_paths": _str_list(incident, "code_paths"),
        "tests": _str_list(incident, "tests"),
        "safety_constraints": list(SAFETY_CONSTRAINTS),
    }

    if _size(request) > max_chars:
        if not _shorten(request, "stack", max_chars, True, 0):
            if not _shorten(request, "normalized_error", max_chars, False, 1):
                raise ValueError("request does not fit into max_chars")
    return request


def _result(reasons, hypothesis=None, actions=None, confidence=None):
    return {
        "status": "INVALID" if reasons else "VALID",
        "authority": "PROPOSAL_ONLY",
        "can_mark_fixed": False,
        "reasons": reasons,
        "hypothesis": None if reasons else hypothesis,
        "proposed_actions": [] if reasons else actions,
        "confidence": None if reasons else confidence,
    }


def _parse(raw, request):
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return _result(["invalid_json"])
    if not isinstance(raw, dict):
        return _result(["response_not_object"])

    reasons = []
    if any(key in raw for key in _FORBIDDEN_KEYS):
        reasons.append("forbidden_key")
    if any(key not in _RESPONSE_KEYS and key not in _FORBIDDEN_KEYS for key in raw):
        reasons.append("unknown_keys")

    expected_id = request.get("incident_id") if isinstance(request, dict) else None
    incident_id = raw.get("incident_id")
    if not isinstance(incident_id, str) or incident_id != expected_id:
        reasons.append("incident_id_mismatch")

    hypothesis = raw.get("hypothesis")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        reasons.append("invalid_hypothesis")

    actions = raw.get("proposed_actions")
    if (
        not isinstance(actions, list)
        or len(actions) > MAX_ACTIONS
        or not all(isinstance(item, str) for item in actions)
    ):
        reasons.append("invalid_proposed_actions")

    confidence = raw.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        reasons.append("invalid_confidence")

    if reasons:
        return _result(reasons)
    return _result(
        [],
        redact_text(hypothesis),
        [redact_text(item) for item in actions],
        confidence,
    )


def parse_response(raw, request):
    try:
        return _parse(raw, request)
    except Exception:
        return _result(["unparseable_response"])
