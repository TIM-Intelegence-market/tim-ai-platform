from datetime import datetime

from src.bugfixer import safety


_ISOLATED = "isolated"
_NOT_ISOLATED = "database not isolated"
_INVALID = "invalid database guard input"


def database_guard(test_url: str, runtime_url: str) -> tuple[bool, str]:
    if not isinstance(test_url, str) or not isinstance(runtime_url, str):
        return False, _INVALID
    try:
        safety.require_isolated_database(test_url, runtime_url)
    except safety.SafetyViolation:
        return False, _NOT_ISOLATED
    except Exception:
        return False, _INVALID
    return True, _ISOLATED


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def cutoff_filter(events: list[dict], cutoff: str) -> list[dict]:
    cutoff_time = _parse_timestamp(cutoff)
    filtered = []
    for event in events:
        if not isinstance(event, dict) or "timestamp" not in event:
            raise ValueError("event must contain timestamp")
        if _parse_timestamp(event["timestamp"]) <= cutoff_time:
            filtered.append(event)
    return filtered
