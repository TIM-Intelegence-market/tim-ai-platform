"""Stable TIM error classes for OpenMarket.

Provider responses are mapped onto a small, fixed set of kinds. Messages are
built from fixed text plus documented provider codes only; response bodies are
never echoed, so a provider message can never carry a secret into a log.
"""
from __future__ import annotations

from enum import StrEnum


class OpenMarketErrorKind(StrEnum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    NO_SECRET = "NO_SECRET"
    INVALID_SECRET = "INVALID_SECRET"
    FORBIDDEN = "FORBIDDEN"
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    DNS_FAILURE = "DNS_FAILURE"
    TLS_FAILURE = "TLS_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    TIMEOUT = "TIMEOUT"
    API_FAILURE = "API_FAILURE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    UNKNOWN = "UNKNOWN"


# Documented provider error codes (owner-verified OpenMarket documentation,
# 2026-09-29). Only these tokens are ever copied out of a response body.
DOCUMENTED_ERROR_CODES = (
    "INVALID_PARAMS",
    "INVALID_EXCHANGE",
    "INVALID_SYMBOL",
    "INVALID_TIMEFRAME",
    "INVALID_API_KEY",
    "INTERNAL_ERROR",
    "TIMEOUT",
)

RETRYABLE_KINDS = frozenset(
    {
        OpenMarketErrorKind.RATE_LIMITED,
        OpenMarketErrorKind.NETWORK_FAILURE,
        OpenMarketErrorKind.TIMEOUT,
        OpenMarketErrorKind.API_FAILURE,
    }
)


class OpenMarketError(Exception):
    """A classified OpenMarket failure; safe to log (no secret, no raw body)."""

    def __init__(
        self,
        kind: OpenMarketErrorKind,
        message: str,
        *,
        http_status: int | None = None,
        provider_code: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.kind = kind
        self.http_status = http_status
        self.provider_code = provider_code
        self.retry_after_seconds = retry_after_seconds
        parts = [kind.value, message]
        if http_status is not None:
            parts.append(f"http_status={http_status}")
        if provider_code is not None:
            parts.append(f"provider_code={provider_code}")
        super().__init__(" ".join(parts))

    @property
    def retryable(self) -> bool:
        return self.kind in RETRYABLE_KINDS


def documented_code(body: bytes) -> str | None:
    """Return the first documented provider error code contained in a body."""
    text = body[:4096].decode("utf-8", errors="replace")
    for code in DOCUMENTED_ERROR_CODES:
        if code in text:
            return code
    return None


def classify_http_status(status: int, body: bytes, retry_after: float | None) -> OpenMarketError:
    code = documented_code(body)
    if status == 400:
        return OpenMarketError(OpenMarketErrorKind.INVALID_REQUEST, "request rejected", http_status=status, provider_code=code)
    if status == 401:
        return OpenMarketError(OpenMarketErrorKind.INVALID_SECRET, "API key rejected", http_status=status, provider_code=code)
    if status == 403:
        # Documented causes: type/tier, history depth, aggregation, max point count.
        return OpenMarketError(OpenMarketErrorKind.FORBIDDEN, "request not permitted for this key/tier", http_status=status, provider_code=code)
    if status == 404:
        return OpenMarketError(OpenMarketErrorKind.NOT_FOUND, "resource not found", http_status=status, provider_code=code)
    if status == 429:
        return OpenMarketError(
            OpenMarketErrorKind.RATE_LIMITED, "rate limited", http_status=status, provider_code=code,
            retry_after_seconds=retry_after,
        )
    if status == 504:
        return OpenMarketError(OpenMarketErrorKind.TIMEOUT, "provider timeout", http_status=status, provider_code=code)
    if status >= 500:
        return OpenMarketError(OpenMarketErrorKind.API_FAILURE, "provider error", http_status=status, provider_code=code)
    return OpenMarketError(OpenMarketErrorKind.UNKNOWN, "unexpected HTTP status", http_status=status, provider_code=code)
