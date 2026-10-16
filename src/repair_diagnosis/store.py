"""Bounded, tamper-evident local storage for repair diagnoses."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.bugfixer.processing import redact
from src.repair_diagnosis.bridge import request_sha256


MAX_RECORD_BYTES = 65536


class DiagnosisStoreError(ValueError):
    """Raised when a diagnosis cannot be safely stored or loaded."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def save_diagnosis(
    directory: str | os.PathLike[str],
    request: dict,
    bridge_result: dict,
    *,
    recorded_at: str,
    provider_model: str = "",
) -> Path:
    try:
        directory_path = Path(directory)
        if directory_path.is_symlink():
            raise DiagnosisStoreError("diagnosis directory must not be a symlink")
        parsed = datetime.fromisoformat(recorded_at)
        if parsed.tzinfo is None:
            raise DiagnosisStoreError("recorded_at must include a timezone")
        if "outcome" not in bridge_result or "attempts" not in bridge_result:
            raise DiagnosisStoreError("bridge result is incomplete")

        result = bridge_result.get("result") or {}
        fields = {
            "schema_version": 1,
            "incident_id": request["incident_id"],
            "request_sha256": request_sha256(request),
            "provider": bridge_result.get("provider"),
            "provider_model": provider_model,
            "recorded_at": recorded_at,
            "outcome": bridge_result["outcome"],
            "hypothesis": result.get("hypothesis"),
            "proposed_actions": result.get("proposed_actions"),
            "confidence": result.get("confidence"),
            "attempts": bridge_result["attempts"],
            "can_mark_fixed": False,
        }
        if "minimal_fix" in result:
            fields.update(
                reproduction_proposal=result.get("reproduction_proposal"),
                minimal_fix=result.get("minimal_fix"),
                risks=result.get("risks", []),
                required_tests=result.get("required_tests", []),
            )
        body = redact(fields)
        envelope = {
            "body": body,
            "sha256": hashlib.sha256(_canonical_json(body)).hexdigest(),
        }
        encoded = _canonical_json(envelope)
        if len(encoded) > MAX_RECORD_BYTES:
            raise DiagnosisStoreError("diagnosis record is too large")

        directory_path.mkdir(parents=True, exist_ok=True)
        if directory_path.is_symlink():
            raise DiagnosisStoreError("diagnosis directory must not be a symlink")
        filename = f"{body['request_sha256']}-{envelope['sha256'][:16]}.json"
        destination = directory_path / filename
        fd, temporary_name = tempfile.mkstemp(dir=directory_path)
        try:
            with os.fdopen(fd, "wb") as temporary:
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, destination)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return destination
    except DiagnosisStoreError:
        raise
    except Exception as exc:
        raise DiagnosisStoreError("could not save diagnosis") from exc


def load_diagnosis(path: str | os.PathLike[str]) -> dict:
    try:
        with Path(path).open("rb") as handle:
            encoded = handle.read(MAX_RECORD_BYTES + 1)
        if len(encoded) > MAX_RECORD_BYTES:
            raise DiagnosisStoreError("diagnosis record is too large")
        envelope = json.loads(encoded.decode("utf-8"))
        if not isinstance(envelope, dict) or set(envelope) != {"body", "sha256"}:
            raise DiagnosisStoreError("invalid diagnosis envelope")
        body = envelope["body"]
        digest = envelope["sha256"]
        if not isinstance(body, dict) or not isinstance(digest, str):
            raise DiagnosisStoreError("invalid diagnosis envelope")
        expected = hashlib.sha256(_canonical_json(body)).hexdigest()
        if digest != expected or body.get("can_mark_fixed") is not False:
            raise DiagnosisStoreError("invalid diagnosis integrity")
        return body
    except DiagnosisStoreError:
        raise
    except Exception as exc:
        raise DiagnosisStoreError("could not load diagnosis") from exc


def list_diagnoses(
    directory: str | os.PathLike[str], incident_id: str
) -> list[dict]:
    directory_path = Path(directory)
    if not directory_path.exists():
        return []
    diagnoses = []
    for path in directory_path.glob("*.json"):
        body = load_diagnosis(path)
        if body.get("incident_id") == incident_id:
            diagnoses.append(body)
    diagnoses.sort(key=lambda item: (item["recorded_at"], item["request_sha256"]))
    return diagnoses
