from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorClass(StrEnum):
    TRANSIENT = "TRANSIENT"
    RETRYABLE = "RETRYABLE"
    DATA_QUALITY = "DATA_QUALITY"
    TERMINAL_BLOCKED = "TERMINAL_BLOCKED"
    CONFIGURATION = "CONFIGURATION"
    CREDENTIAL = "CREDENTIAL"
    DATABASE = "DATABASE"
    NETWORK = "NETWORK"
    INVARIANT_VIOLATION = "INVARIANT_VIOLATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ErrorPolicy:
    category: ErrorClass
    retry: bool
    max_attempts: int
    backoff_seconds: tuple[int, ...]
    quarantine: bool
    safe_stop: bool


_POLICIES = {
    ErrorClass.TRANSIENT: ErrorPolicy(ErrorClass.TRANSIENT, True, 3, (1, 5, 30), False, False),
    ErrorClass.RETRYABLE: ErrorPolicy(ErrorClass.RETRYABLE, True, 5, (5, 30, 120, 300, 900), True, False),
    ErrorClass.DATA_QUALITY: ErrorPolicy(ErrorClass.DATA_QUALITY, False, 0, (), True, False),
    ErrorClass.TERMINAL_BLOCKED: ErrorPolicy(ErrorClass.TERMINAL_BLOCKED, False, 0, (), True, True),
    ErrorClass.CONFIGURATION: ErrorPolicy(ErrorClass.CONFIGURATION, False, 0, (), False, True),
    ErrorClass.CREDENTIAL: ErrorPolicy(ErrorClass.CREDENTIAL, False, 0, (), False, True),
    ErrorClass.DATABASE: ErrorPolicy(ErrorClass.DATABASE, True, 3, (5, 30, 120), False, True),
    ErrorClass.NETWORK: ErrorPolicy(ErrorClass.NETWORK, True, 5, (1, 5, 30, 120, 300), False, False),
    ErrorClass.INVARIANT_VIOLATION: ErrorPolicy(ErrorClass.INVARIANT_VIOLATION, False, 0, (), False, True),
    ErrorClass.UNKNOWN: ErrorPolicy(ErrorClass.UNKNOWN, False, 0, (), True, True),
}


def classify_error(error: BaseException | str) -> ErrorPolicy:
    """Conservatively classify an error; UNKNOWN is never retried blindly."""
    text = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
    lowered = text.lower()
    if "out-of-order" in lowered or "terminal_blocked" in lowered:
        category = ErrorClass.TERMINAL_BLOCKED
    elif any(term in lowered for term in ("invariant", "hash mismatch", "duplicate side effect")):
        category = ErrorClass.INVARIANT_VIOLATION
    elif any(term in lowered for term in ("credential", "password", "authentication", "keychain", "secret")):
        category = ErrorClass.CREDENTIAL
    elif any(term in lowered for term in ("configuration", "config", "ex_config", "missing environment")):
        category = ErrorClass.CONFIGURATION
    elif any(term in lowered for term in ("deadlock", "database", "postgres", "asyncpg", "connection pool")):
        category = ErrorClass.DATABASE
    elif any(term in lowered for term in ("network", "websocket", "dns", "connection refused", "timeout")):
        category = ErrorClass.NETWORK
    elif any(term in lowered for term in ("invalid price", "invalid volume", "future timestamp", "data quality", "candle gap")):
        category = ErrorClass.DATA_QUALITY
    elif any(term in lowered for term in ("temporarily unavailable", "rate limit", "try again")):
        category = ErrorClass.TRANSIENT
    else:
        category = ErrorClass.UNKNOWN
    return _POLICIES[category]
