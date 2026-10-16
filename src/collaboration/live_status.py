"""Validation of the collaboration live-status document (observe-only)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.bugfixer import processing

SCHEMA_VERSION = "tim.collaboration.live_status.v1"

REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "published_at_utc",
        "captured_at_utc",
        "collectors",
        "queue",
        "coverage",
        "quality",
        "safety",
    }
)
SECTION_KEYS = ("collectors", "queue", "coverage", "quality")
FORBIDDEN_KEYS = frozenset({"trades", "raw_trades", "rows", "exception"})
FORBIDDEN_PATH_PREFIXES = ("/Users/", "/home/", "/root/", "C:\\")
FORBIDDEN_DSN_PREFIXES = ("postgres://", "postgresql://")
TRACEBACK_MARKER = "Traceback (most recent call last)"
MAX_LIST_ITEMS = 100
MAX_SECTION_DEPTH = 2
MAX_WALK_DEPTH = 12

_SCALARS = (str, int, float, bool, type(None))


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    if not (value.endswith("Z") or value.endswith("+00:00")):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _check_text(text: str, where: str, errors: set[str]) -> None:
    try:
        if processing.redact_text(text) != text:
            errors.add(f"{where}: contains redactable content")
    except Exception:
        errors.add(f"{where}: redaction check failed")
    if TRACEBACK_MARKER in text:
        errors.add(f"{where}: contains traceback")
    stripped = text.lstrip()
    if stripped.startswith(FORBIDDEN_PATH_PREFIXES):
        errors.add(f"{where}: contains local path")
    if stripped.lower().startswith(FORBIDDEN_DSN_PREFIXES):
        errors.add(f"{where}: contains database DSN")


def _walk(value: Any, where: str, errors: set[str], depth: int = 0) -> None:
    if depth > MAX_WALK_DEPTH:
        errors.add(f"{where}: nesting too deep")
        return
    if isinstance(value, str):
        _check_text(value, where, errors)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                errors.add(f"{where}: non-string key")
                continue
            child = f"{where}.{key}"
            if key.lower() in FORBIDDEN_KEYS:
                errors.add(f"{child}: forbidden key")
            _check_text(key, f"{child} (key)", errors)
            _walk(item, child, errors, depth + 1)
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk(item, f"{where}[{index}]", errors, depth + 1)


def _check_list(value: Any, where: str, errors: set[str]) -> None:
    if len(value) > MAX_LIST_ITEMS:
        errors.add(f"{where}: list longer than {MAX_LIST_ITEMS}")
    if not all(isinstance(item, _SCALARS) for item in value):
        errors.add(f"{where}: list must contain only scalars")


def _check_section(value: Any, where: str, errors: set[str], level: int = 1) -> None:
    if not isinstance(value, dict):
        errors.add(f"{where}: must be an object")
        return
    for key, item in value.items():
        child = f"{where}.{key}"
        if isinstance(item, _SCALARS):
            continue
        if isinstance(item, list):
            _check_list(item, child, errors)
        elif isinstance(item, dict):
            if level >= MAX_SECTION_DEPTH:
                errors.add(f"{child}: nesting deeper than {MAX_SECTION_DEPTH}")
            else:
                _check_section(item, child, errors, level + 1)
        else:
            errors.add(f"{child}: unsupported value type")


def _check_safety(value: Any, errors: set[str]) -> None:
    if not isinstance(value, dict):
        errors.add("safety: must be an object")
        return
    if set(value.keys()) != {"observe_only", "trading_actions_emitted"}:
        errors.add("safety: keys must be exactly observe_only and trading_actions_emitted")
    if value.get("observe_only") is not True:
        errors.add("safety.observe_only: must be True")
    actions = value.get("trading_actions_emitted")
    if isinstance(actions, bool) or not isinstance(actions, int) or actions != 0:
        errors.add("safety.trading_actions_emitted: must be 0")


def _validate(doc: Any, errors: set[str]) -> None:
    if not isinstance(doc, dict):
        errors.add("document must be an object")
        return
    keys = set(doc.keys())
    for key in sorted(REQUIRED_KEYS - keys):
        errors.add(f"{key}: missing required key")
    for key in keys - REQUIRED_KEYS:
        errors.add(f"{key!s}: unexpected top-level key")

    if "schema_version" in doc and doc["schema_version"] != SCHEMA_VERSION:
        errors.add("schema_version: unsupported value")

    parsed: dict[str, datetime] = {}
    for name in ("published_at_utc", "captured_at_utc"):
        if name in doc:
            moment = _parse_utc(doc[name])
            if moment is None:
                errors.add(f"{name}: must be ISO-8601 UTC ending in Z or +00:00")
            else:
                parsed[name] = moment
    if len(parsed) == 2 and parsed["captured_at_utc"] > parsed["published_at_utc"]:
        errors.add("captured_at_utc: must not be after published_at_utc")

    for name in SECTION_KEYS:
        if name in doc:
            _check_section(doc[name], name, errors)
    if "safety" in doc:
        _check_safety(doc["safety"], errors)

    _walk(doc, "doc", errors)


def validate_live_status(doc: Any) -> dict:
    """Validate a live-status document. Never raises."""
    errors: set[str] = set()
    try:
        _validate(doc, errors)
    except Exception:
        errors.add("validation failed unexpectedly")
    return {"ok": not errors, "errors": sorted(errors)}
