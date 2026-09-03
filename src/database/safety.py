from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit


TEST_DATABASE_URL_ENV = "TIM_DURABLE_TEST_DATABASE_URL"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_TEST_DATABASE_NAME = re.compile(r"(?:^|_)(?:test|pytest|isolated)(?:_|$)", re.IGNORECASE)


class DatabaseSafetyError(RuntimeError):
    """Raised before a test can connect to a non-isolated database."""


@dataclass(frozen=True, slots=True)
class DatabaseFingerprint:
    host: str
    port: int
    database: str

    def safe_label(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"


def database_fingerprint(url: str) -> DatabaseFingerprint:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 5432
    except ValueError as exc:
        raise DatabaseSafetyError("database URL is invalid") from exc
    database = parsed.path.lstrip("/").split("/", 1)[0]
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not database:
        raise DatabaseSafetyError("database URL is not a complete PostgreSQL target")
    return DatabaseFingerprint(parsed.hostname.lower(), port, database)


def is_test_context(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return (
        values.get("TIM_ENV", "").lower() == "test"
        or values.get("TIM_RUNTIME_ENV", "").lower() == "test"
        or "PYTEST_CURRENT_TEST" in values
    )


def require_safe_test_database(url: str, env: Mapping[str, str] | None = None) -> DatabaseFingerprint:
    """Authorize one explicit, loopback, recognizably isolated test database."""

    values = os.environ if env is None else env
    explicit = values.get(TEST_DATABASE_URL_ENV, "")
    if not explicit:
        raise DatabaseSafetyError(f"{TEST_DATABASE_URL_ENV} is required in test context; runtime fallback is forbidden")
    requested = database_fingerprint(url)
    approved = database_fingerprint(explicit)
    if requested != approved:
        raise DatabaseSafetyError(
            f"test database target {requested.safe_label()} does not match explicit isolated target {approved.safe_label()}"
        )
    runtime_database = values.get("TIM_DATABASE_NAME", "tim").strip().lower()
    if approved.host not in _LOOPBACK_HOSTS or approved.database.lower() == runtime_database:
        raise DatabaseSafetyError(f"production-like database target rejected in test context: {approved.safe_label()}")
    if not _TEST_DATABASE_NAME.search(approved.database):
        raise DatabaseSafetyError("isolated test database name must contain test, pytest, or isolated")
    return approved


def guard_database_connection(url: str, env: Mapping[str, str] | None = None) -> None:
    if is_test_context(env):
        require_safe_test_database(url, env)
