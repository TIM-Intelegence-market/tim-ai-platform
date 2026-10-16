"""Bridge that asks diagnosis providers for a repair proposal.

Stdlib only, no network access. Providers are injected callables; every
provider is tried at most once, in list order. A proposal never grants
authority to mark a task as fixed.
"""
import hashlib
import json
import re

from src.repair_diagnosis.package import parse_response

_NAME_RE = re.compile(r"[a-z][a-z0-9_-]{0,39}")
_REQUEST_SCHEMA = "tim.diagnosis.request.v1"


class ProviderUnavailable(Exception):
    """Raised by a provider that cannot currently be used."""


def request_sha256(request: dict) -> str:
    payload = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def _validate_providers(providers) -> None:
    if not isinstance(providers, (list, tuple)) or not providers:
        raise ValueError("providers must be a non-empty list")
    seen = set()
    for item in providers:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("provider must be a (name, fn) tuple")
        name, fn = item
        if not isinstance(name, str) or _NAME_RE.fullmatch(name) is None:
            raise ValueError("invalid provider name")
        if name in seen:
            raise ValueError("duplicate provider name")
        if not callable(fn):
            raise ValueError("provider fn must be callable")
        seen.add(name)


def _request_ok(request) -> bool:
    if not isinstance(request, dict):
        return False
    if request.get("schema") != _REQUEST_SCHEMA:
        return False
    constraints = request.get("safety_constraints", [])
    if not isinstance(constraints, (list, tuple)):
        return False
    return "no_fixed_authority" in constraints


def request_diagnosis(request: dict, providers: list) -> dict:
    _validate_providers(providers)
    if not _request_ok(request):
        return {
            "outcome": "REQUEST_REJECTED",
            "provider": None,
            "attempts": [],
            "result": None,
            "can_mark_fixed": False,
            "next_action": "FIX_REQUEST",
        }

    attempts = []
    for name, fn in providers:
        try:
            raw = fn(json.dumps(request, sort_keys=True))
        except TimeoutError:
            attempts.append({"provider": name, "status": "timeout"})
            continue
        except ProviderUnavailable:
            attempts.append({"provider": name, "status": "unavailable"})
            continue
        except Exception:
            attempts.append({"provider": name, "status": "error"})
            continue
        if not isinstance(raw, (str, dict)):
            attempts.append({"provider": name, "status": "error"})
            continue
        try:
            parsed = parse_response(raw, request)
            status = parsed["status"]
        except Exception:
            attempts.append({"provider": name, "status": "error"})
            continue
        if status == "VALID":
            return {
                "outcome": "PROPOSAL",
                "provider": name,
                "attempts": attempts + [{"provider": name, "status": "VALID"}],
                "result": parsed,
                "can_mark_fixed": False,
                "next_action": "LOCAL_REPRODUCTION_AND_GATES",
            }
        attempts.append({"provider": name, "status": "INVALID"})

    return {
        "outcome": "PROVIDER_FAILED",
        "provider": None,
        "attempts": attempts,
        "result": None,
        "can_mark_fixed": False,
        "next_action": "MANUAL_BRIDGE",
    }
