from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import parse_qsl, unquote, urlsplit


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
        port = parsed.port if parsed.port is not None else 5432
        database = unquote(parsed.path.removeprefix("/"))
        # asyncpg's IPv6 host parser accepts a prefix match; urllib may find a
        # later port in a malformed suffix. Require the full host authority.
        authority = parsed.netloc.rpartition("@")[2]
        if (parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname
                or not database or "/" in database or parsed.fragment or not 1 <= port <= 65535
                or parsed.netloc.count("@") > 1
                or (authority.startswith("[") and not re.fullmatch(r"\[[^\]]+\](?::[0-9]*)?", authority))
                or any(ord(char) < 32 or ord(char) == 127 for value in
                       (url, database, unquote(parsed.username or ""), unquote(parsed.password or ""))
                       for char in value)):
            raise ValueError()
        # A driver may honor query overrides for host/database/port. Authorize
        # only our isolated schema option, never a second connection target.
        parameters = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        if parameters:
            if len(parameters) != 1 or parameters[0][0] != "options":
                raise ValueError()
            match = re.fullmatch(r"-csearch_path=([a-z][a-z0-9_]{2,62})", parameters[0][1])
            if not match or match[1] in {"public", "pg_catalog", "information_schema"}:
                raise ValueError()
        host = parsed.hostname.lower().rstrip(".")
        if host in _LOOPBACK_HOSTS:
            host = "127.0.0.1"
        return DatabaseFingerprint(host, port, database)
    except (ValueError, TypeError, AttributeError):
        # Do not echo credential-bearing URLs or driver parser exceptions.
        raise DatabaseSafetyError("database URL is invalid or ambiguous") from None


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
    # asyncpg may use PGPORT for a portless DSN. Validate the actual connection
    # target without depending on inherited process configuration.
    if urlsplit(url).port is None:
        raise DatabaseSafetyError("explicit URL port is required for test database connections")
    approved = database_fingerprint(explicit)
    if requested != approved:
        raise DatabaseSafetyError(
            f"test database target {requested.safe_label()} does not match explicit isolated target {approved.safe_label()}"
        )
    for key in ("TIM_DATABASE_URL", "TIM_RUNTIME_DATABASE_URL", "DATABASE_URL"):
        runtime_url = values.get(key)
        if runtime_url:
            runtime = database_fingerprint(runtime_url)
            if urlsplit(runtime_url).port is None and values.get("PGPORT", "") not in {"", "5432"}:
                raise DatabaseSafetyError("runtime database URL needs an explicit port to exclude PGPORT ambiguity")
            if approved == runtime:
                raise DatabaseSafetyError("test database target is the runtime database")
    runtime_database = values.get("TIM_DATABASE_NAME", "tim").strip().lower()
    if approved.host not in _LOOPBACK_HOSTS or approved.database.lower() == runtime_database:
        raise DatabaseSafetyError(f"production-like database target rejected in test context: {approved.safe_label()}")
    if not _TEST_DATABASE_NAME.search(approved.database):
        raise DatabaseSafetyError("isolated test database name must contain test, pytest, or isolated")
    return approved


def guard_database_connection(url: str, env: Mapping[str, str] | None = None) -> None:
    if is_test_context(env):
        require_safe_test_database(url, env)
