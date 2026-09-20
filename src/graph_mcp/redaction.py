"""Secret redaction (STEP 25): nothing credential-like enters the graph."""
from __future__ import annotations

import re
from typing import Any

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(sk-|Bearer\s+)[A-Za-z0-9._-]{16,}"),
    re.compile(r"\b[A-Fa-f0-9]{64}\b"),  # raw private-key / token material
    re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S+"),
)
REDACTED = "[REDACTED]"
_SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|token|api_?key|private_key)")


def redact_text(value: str) -> str:
    for pattern in SECRET_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def redact(value: Any) -> Any:
    """Recursively redact strings inside metadata structures."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: (REDACTED if _SECRET_KEY.search(k) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def contains_secret(value: Any) -> bool:
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in SECRET_PATTERNS)
    if isinstance(value, dict):
        return any(_SECRET_KEY.search(k) or contains_secret(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_secret(item) for item in value)
    return False
