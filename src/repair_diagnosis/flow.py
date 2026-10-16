"""Glue from a stored incident to a saved diagnosis.

Stdlib only, no network access. The incident row is only read; providers are
injected callables. Every bridge outcome, including PROVIDER_FAILED, is saved
so a failed attempt stays visible as a resumable blocker.
"""
import json

from src.repair_diagnosis.bridge import request_diagnosis, request_sha256
from src.repair_diagnosis.package import build_request
from src.repair_diagnosis.store import save_diagnosis


def request_from_incident(incident, *, code_paths=None, tests=None, max_chars=20000) -> dict:
    exception = incident.get("exception_class") or ""
    message = incident["normalized_message"]
    return build_request(
        {
            "incident_id": incident["id"],
            "category": incident["category"],
            "component": incident["component"],
            "fingerprint": incident["id"],
            "normalized_error": f"{exception}: {message}" if exception else message,
            "stack": json.loads(incident["evidence"]).get("stack", ""),
            "reproduction": None,
            "code_paths": list(code_paths or []),
            "tests": list(tests or []),
        },
        max_chars=max_chars,
    )


def diagnose_incident(
    store,
    incident_id,
    providers,
    directory,
    *,
    recorded_at,
    provider_model="",
    code_paths=None,
    tests=None,
) -> dict:
    request = request_from_incident(
        store.inspect(incident_id), code_paths=code_paths, tests=tests
    )
    result = request_diagnosis(request, providers)
    path = save_diagnosis(
        directory, request, result, recorded_at=recorded_at, provider_model=provider_model
    )
    return {
        "outcome": result["outcome"],
        "path": str(path),
        "request_sha256": request_sha256(request),
        "can_mark_fixed": False,
    }
