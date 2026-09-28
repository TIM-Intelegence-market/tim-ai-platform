from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from typing import Any


def _safe(value: Any, fallback: str = "—") -> str:
    if value is None or value == "":
        return fallback
    return html.escape(str(value))


def _short(value: Any, size: int = 10) -> str:
    text = str(value or "")
    return text[:size] if text else "—"


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _duration(start: Any, end: Any) -> str:
    left, right = _parse_time(start), _parse_time(end)
    if not left or not right or right < left:
        return "—"
    seconds = int((right - left).total_seconds())
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"


def _age_seconds(value: Any) -> str:
    parsed = _parse_time(value)
    if not parsed:
        return f"MISSING:{value!s}" if value not in (None, "") else "MISSING:freshness_seconds"
    age = int((datetime.now(timezone.utc) - parsed).total_seconds())
    return "INVALID:FUTURE_TIMESTAMP" if age < 0 else str(age)


def _json_block(value: Any) -> str:
    return _safe(json.dumps(value if value is not None else {}, indent=2, ensure_ascii=False, sort_keys=True))


def _status(value: Any) -> str:
    normalized = str(value or "UNKNOWN").upper()
    if normalized in {"HEALTHY", "RUNNING", "CONNECTED", "PASS", "GREEN", "TRUE"}:
        return "GREEN"
    if normalized in {"WARNING", "DEGRADED", "PENDING", "WAITING", "MONITORING", "YELLOW", "OPEN_ISSUES", "NOT_READY_FOR_V2"}:
        return "YELLOW"
    return "RED"


def _required(field: str, value: Any) -> str:
    if value in (None, "", [], {}, ()):
        return f"MISSING:{field}"
    return str(value)


def _status_level(value: Any, severity: str = "WARNING") -> tuple[str, str]:
    normalized = str(value or "UNKNOWN").upper()
    if normalized in {"GREEN", "HEALTHY", "RUNNING", "CONNECTED", "PASS", "COMPLETE", "COMPLETED", "AVAILABLE", "TRUE"}:
        return "GREEN", "INFO"
    if normalized in {"YELLOW", "WARNING", "WAITING", "MONITORING", "DEGRADED", "PARTIAL", "NOT_READY_FOR_V2", "OPEN", "OPEN_ISSUES"}:
        return "YELLOW", severity
    return "RED", "CRITICAL" if severity in {"HIGH", "CRITICAL"} else severity
