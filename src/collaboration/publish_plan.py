"""Decide whether the live status snapshot should be committed and published."""
from __future__ import annotations

import json
from typing import Any

from src.collaboration.live_status import validate_live_status

SNAPSHOT_PATH = "artifacts/collaboration/live_status.json"
_IGNORED_KEYS = ("published_at_utc", "captured_at_utc")


def _plan(action: str, reasons: list[str], stage: list[str] | None = None, commit_message: str = "") -> dict:
    return {
        "action": action,
        "reasons": list(reasons),
        "stage": list(stage or []),
        "commit_message": commit_message,
    }


def _validation_errors(result: Any) -> list[str]:
    if result is None:
        return []
    if isinstance(result, bool):
        return [] if result else ["invalid live status"]
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], bool):
        if result[0]:
            return []
        errors = [str(e) for e in (result[1] or [])]
        return errors or ["invalid live status"]
    if isinstance(result, dict):
        errors = [str(e) for e in (result.get("errors") or [])]
        if errors:
            return errors
        if result.get("valid") is False or result.get("ok") is False:
            return ["invalid live status"]
        return []
    if isinstance(result, (list, tuple, set)):
        return [str(e) for e in result]
    return [str(result)]


def _stripped(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in _IGNORED_KEYS}


def _unchanged(new_doc: dict, previous_text: Any) -> bool:
    try:
        previous = json.loads(previous_text)
    except (TypeError, ValueError):
        return False
    if not isinstance(previous, dict):
        return False
    new_text = json.dumps(_stripped(new_doc), sort_keys=True, indent=2) + "\n"
    old_text = json.dumps(_stripped(previous), sort_keys=True, indent=2) + "\n"
    return new_text == old_text


def plan_publish(new_doc: Any, previous_text: Any, changed_paths: Any) -> dict:
    """Return a publish plan; never raises."""
    try:
        try:
            errors = _validation_errors(validate_live_status(new_doc))
        except Exception as exc:  # noqa: BLE001 - never raise
            errors = [f"validation failed: {type(exc).__name__}"]
        if not isinstance(new_doc, dict) and not errors:
            errors = ["live status is not an object"]
        if errors:
            return _plan("safe_stop", errors)

        paths = list(changed_paths or [])
        if any(p != SNAPSHOT_PATH for p in paths):
            return _plan("safe_stop", ["unexpected changed paths"])

        json.dumps(new_doc, sort_keys=True, indent=2)
        if _unchanged(new_doc, previous_text):
            return _plan("skip", ["no change besides timestamps"])

        message = "chore(collaboration): live status " + str(new_doc.get("captured_at_utc"))
        return _plan("publish", ["snapshot changed"], [SNAPSHOT_PATH], message)
    except Exception as exc:  # noqa: BLE001 - never raise
        return _plan("safe_stop", [f"planning failed: {type(exc).__name__}"])
