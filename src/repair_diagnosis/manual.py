"""Manual export/import adapter for repair diagnosis proposals."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .package import build_request, parse_response
from src.repair_diagnosis.store import save_diagnosis

REQUEST_KIND = "TIM_DIAGNOSIS_REQUEST_V1"
MAX_RESPONSE_BYTES = 65536
RESPONSE_FIELDS = ("incident_id", "hypothesis", "proposed_actions", "confidence")

_INSTRUCTIONS = (
    "Answer with one JSON object with exactly these fields: incident_id, hypothesis, "
    "proposed_actions, confidence. The answer is a proposal only."
)


def request_hash(request: dict) -> str:
    payload = json.dumps(
        request, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def export_request(request: dict, path) -> Path:
    if request.get("schema") != "tim.diagnosis.request.v1":
        raise ValueError("invalid request schema")

    output = Path(path)
    document = {
        "kind": REQUEST_KIND,
        "request": request,
        "request_sha256": request_hash(request),
        "response_fields": list(RESPONSE_FIELDS),
        "instructions": _INSTRUCTIONS,
    }
    try:
        with output.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError("output already exists") from exc
    return output


def _invalid_response(reason: str) -> dict:
    return {
        "status": "INVALID",
        "authority": "PROPOSAL_ONLY",
        "can_mark_fixed": False,
        "reasons": [reason],
        "hypothesis": None,
        "proposed_actions": [],
        "confidence": None,
        "provider": "manual",
    }


def import_response(request_path, response_path) -> dict:
    with Path(request_path).open(encoding="utf-8") as handle:
        document = json.load(handle)

    if document.get("kind") != REQUEST_KIND:
        raise ValueError("invalid request kind")
    request = document.get("request")
    if not isinstance(request, dict) or document.get("request_sha256") != request_hash(request):
        raise ValueError("request integrity check failed")

    response_bytes = Path(response_path).read_bytes()
    if len(response_bytes) > MAX_RESPONSE_BYTES:
        return _invalid_response("response_too_large")

    text = response_bytes.decode("utf-8", errors="replace")
    result = parse_response(text, request)
    result["provider"] = "manual"
    return result


def import_and_save(request_path, response_path, directory, *, recorded_at: str) -> dict:
    """Import a manual response and persist it as PROPOSAL or INVALID_RESPONSE."""
    result = import_response(request_path, response_path)
    with Path(request_path).open(encoding="utf-8") as handle:
        request = json.load(handle)["request"]
    valid = result["status"] == "VALID"
    bridge_result = {
        "outcome": "PROPOSAL" if valid else "INVALID_RESPONSE",
        "provider": "manual",
        "attempts": [{"provider": "manual", "status": result["status"]}],
        "result": result if valid else None,
    }
    path = save_diagnosis(
        directory, request, bridge_result, recorded_at=recorded_at, provider_model="manual"
    )
    return {**result, "path": str(path)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export")
    export_parser.add_argument("--incident", required=True)
    export_parser.add_argument("--out", required=True)

    import_parser = subparsers.add_parser("import")
    import_parser.add_argument("--request", required=True)
    import_parser.add_argument("--response", required=True)
    import_parser.add_argument("--store")

    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            with Path(args.incident).open(encoding="utf-8") as handle:
                incident = json.load(handle)
            if not isinstance(incident, dict):
                raise ValueError("incident must be an object")
            request = build_request(incident)
            print(export_request(request, args.out))
            return 0

        if args.store:
            result = import_and_save(
                args.request,
                args.response,
                args.store,
                recorded_at=datetime.now(timezone.utc).isoformat(),
            )
        else:
            result = import_response(args.request, args.response)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status") == "VALID" else 2
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
