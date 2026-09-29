"""Authenticated, bounded OpenMarket REST client (``GET /v1/points``).

- Explicit timeout, bounded retries with exponential backoff.
- 429 honours ``Retry-After`` up to a cap; a longer wait fails fast instead of
  sleeping for minutes.
- Status validation and a fixed error taxonomy (errors.py); no response body or
  secret ever reaches an exception message or a log.
- One persistent HTTPS connection per client (connection reuse).
- Effective limits come from the documented ``X-RateLimit-*`` headers; no
  account tier is assumed.

Base URL: the documented ``https://api.openmarket.xyz``; ``TIM_OPENMARKET_BASE_URL``
may override it (https only).
"""
from __future__ import annotations

import hashlib
import http.client
import os
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlsplit

from config.secrets import SecretValue

from .auth import OpenMarketSecretResolver
from .errors import OpenMarketError, OpenMarketErrorKind, classify_http_status
from .schemas import parse_json

POINTS_PATH = "/v1/points"
AUTH_HEADER = "X-OpenMarket-Key"
BASE_URL_ENV = "TIM_OPENMARKET_BASE_URL"
# Documented REST base URL (owner-verified official docs); the env var only overrides it.
DEFAULT_BASE_URL = "https://api.openmarket.xyz"
RATE_LIMIT_HEADERS = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Used", "X-RateLimit-Reset", "Retry-After")
USER_AGENT = "TIM-OpenMarket/1.0"
MAX_BODY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    headers: Mapping[str, str]
    body: bytes


# Header values may be SecretValue; transports resolve them via reveal_headers().
Transport = Callable[[str, str, Mapping[str, Any], float], HttpResult]


@dataclass(slots=True)
class RateLimitState:
    limit: str | None = None
    remaining: str | None = None
    used: str | None = None
    reset: str | None = None
    retry_after: str | None = None
    limited: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit, "remaining": self.remaining, "used": self.used,
            "reset": self.reset, "retry_after": self.retry_after, "limited": self.limited,
        }


@dataclass(frozen=True, slots=True)
class PointsResponse:
    payload: Any
    status: int
    request_path: str
    requested_at: datetime
    latency_seconds: float
    response_bytes: int
    body_sha256: str


def _header(headers: Mapping[str, str], name: str) -> str | None:
    lowered = {key.lower(): value for key, value in headers.items()}
    value = lowered.get(name.lower())
    return str(value)[:64] if value is not None else None


def _retry_after_seconds(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def reveal_headers(headers: Mapping[str, Any]) -> dict[str, str]:
    """Only transports call this, as late as possible: callers pass a SecretValue."""
    return {name: value.reveal() if isinstance(value, SecretValue) else value for name, value in headers.items()}


class _PersistentHttpsTransport:
    """One reused ``HTTPSConnection``; reconnects once the server drops it."""

    def __init__(self, host: str, port: int | None) -> None:
        self.host, self.port = host, port
        self.connection: http.client.HTTPSConnection | None = None
        self.context = ssl.create_default_context()

    def __call__(self, method: str, path: str, headers: Mapping[str, Any], timeout: float) -> HttpResult:
        if self.connection is None:
            self.connection = http.client.HTTPSConnection(self.host, self.port, timeout=timeout, context=self.context)
        self.connection.timeout = timeout
        try:
            self.connection.request(method, path, headers=reveal_headers(headers))
            response = self.connection.getresponse()
            body = response.read(MAX_BODY_BYTES + 1)
            result = HttpResult(response.status, dict(response.getheaders()), body)
            if len(body) > MAX_BODY_BYTES:
                self.close()  # unread remainder must not poison the reused connection
            return result
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None


class OpenMarketClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        secrets: OpenMarketSecretResolver | None = None,
        transport: Transport | None = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        backoff_seconds: float = 0.5,
        max_retry_after_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        env: Mapping[str, str] | None = None,
    ) -> None:
        env = os.environ if env is None else env
        self.base_url = (base_url or env.get(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
        self.secrets = secrets or OpenMarketSecretResolver(env)
        self.timeout_seconds = max(1.0, min(timeout_seconds, 60.0))
        self.max_retries = max(0, min(max_retries, 5))
        self.backoff_seconds = max(0.0, min(backoff_seconds, 5.0))
        self.max_retry_after_seconds = max(0.0, min(max_retry_after_seconds, 60.0))
        self.sleep = sleep
        self.rate_limit = RateLimitState()
        self.last_success: str | None = None
        self.last_error: str | None = None
        self.reachable: bool | None = None
        self.authenticated: bool | None = None
        self._transport = transport
        self._path_prefix = ""

    def _resolve_transport(self) -> Transport:
        parts = urlsplit(self.base_url)
        if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
            raise OpenMarketError(OpenMarketErrorKind.NOT_CONFIGURED, f"{BASE_URL_ENV} must be an https base URL")
        self._path_prefix = parts.path.rstrip("/")
        if self._transport is None:
            self._transport = _PersistentHttpsTransport(parts.hostname, parts.port)
        return self._transport

    def close(self) -> None:
        closer = getattr(self._transport, "close", None)
        if callable(closer):
            closer()

    def health(self) -> dict[str, Any]:
        configured = bool(self.base_url) and self.secrets.configured()
        return {
            "provider": "openmarket",
            "configured": configured,
            "reachable": self.reachable,
            "authenticated": self.authenticated,
            "healthy": bool(configured and self.reachable and self.authenticated and self.last_error is None),
            "last_success": self.last_success,
            "last_error": self.last_error,
            "rate_limit_state": self.rate_limit.as_dict(),
        }

    def _record_rate_limit(self, headers: Mapping[str, str], status: int) -> None:
        self.rate_limit = RateLimitState(
            *(_header(headers, name) for name in RATE_LIMIT_HEADERS), limited=status == 429
        )

    def _fail(self, error: OpenMarketError) -> OpenMarketError:
        self.last_error = error.kind.value
        return error

    def get_points(self, params: Mapping[str, str | int]) -> PointsResponse:
        """One logical read with bounded retries. Raises ``OpenMarketError``."""
        transport = self._resolve_transport()
        # NO_SECRET fails closed before any request. The key stays wrapped in a
        # SecretValue here, so tracebacks with captured locals never show it.
        query = urlencode({name: str(value) for name, value in params.items()})
        path = f"{self._path_prefix}{POINTS_PATH}?{query}"
        headers = {AUTH_HEADER: self.secrets.api_key(), "Accept": "application/json", "User-Agent": USER_AGENT}
        attempt = 0
        while True:
            requested_at = datetime.now(timezone.utc)
            started = time.perf_counter()
            try:
                result = transport("GET", path, headers, self.timeout_seconds)
            except socket.gaierror:
                error = OpenMarketError(OpenMarketErrorKind.DNS_FAILURE, "DNS resolution failed")
            except ssl.SSLError:
                error = OpenMarketError(OpenMarketErrorKind.TLS_FAILURE, "TLS handshake failed")
            except (TimeoutError, socket.timeout):
                error = OpenMarketError(OpenMarketErrorKind.TIMEOUT, "request timed out")
            except (OSError, http.client.HTTPException, ValueError):
                # ValueError covers header encoding failures; its text is not reused.
                error = OpenMarketError(OpenMarketErrorKind.NETWORK_FAILURE, "network failure")
            else:
                latency = time.perf_counter() - started
                self.reachable = True
                self._record_rate_limit(result.headers, result.status)
                if result.status == 200:
                    if len(result.body) > MAX_BODY_BYTES:
                        raise self._fail(OpenMarketError(OpenMarketErrorKind.SCHEMA_MISMATCH, "response larger than 8 MiB"))
                    try:
                        payload = parse_json(result.body)
                    except OpenMarketError as parse_error:
                        raise self._fail(parse_error) from None
                    self.authenticated = True  # a parsable 200, not just any 200
                    self.last_success = requested_at.isoformat()
                    self.last_error = None
                    return PointsResponse(
                        payload, result.status, POINTS_PATH, requested_at, latency, len(result.body),
                        hashlib.sha256(result.body).hexdigest(),
                    )
                retry_after = _retry_after_seconds(_header(result.headers, "Retry-After"))
                error = classify_http_status(result.status, result.body, retry_after)
                if result.status == 401:
                    self.authenticated = False
                # Any other non-200 proves nothing about the key: an intercepting
                # proxy or gateway can answer 403/404 without OpenMarket seeing it.
            if not error.retryable or attempt >= self.max_retries:
                raise self._fail(error)
            if error.kind is OpenMarketErrorKind.RATE_LIMITED:
                wait = error.retry_after_seconds if error.retry_after_seconds is not None else self.backoff_seconds * 2 ** attempt
                if wait > self.max_retry_after_seconds:
                    raise self._fail(error)
            else:
                wait = self.backoff_seconds * 2 ** attempt
            attempt += 1
            self.sleep(wait)
