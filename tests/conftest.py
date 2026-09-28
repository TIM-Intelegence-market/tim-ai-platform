from __future__ import annotations

import asyncpg
import pytest

from src.database.safety import DatabaseSafetyError, require_safe_test_database


def _dsn(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    value = args[0] if args else kwargs.get("dsn")
    if not isinstance(value, str):
        raise DatabaseSafetyError("tests must use an explicit PostgreSQL DSN")
    # asyncpg gives target kwargs precedence over the validated DSN. Keep one
    # source of truth, including for matching, empty, or multi-host overrides.
    if any(kwargs.get(key) is not None for key in ("host", "port", "database")):
        raise DatabaseSafetyError("test database target overrides are forbidden; use only the explicit DSN")
    for key in ("user", "password"):
        supplied = kwargs.get(key)
        if isinstance(supplied, str) and any(ord(char) < 32 or ord(char) == 127 for char in supplied):
            raise DatabaseSafetyError("test database credential overrides contain control characters")
    # Startup parameters are appended to the wire message after user/database.
    # A second database field (or embedded NUL) can evade a DSN-only check.
    settings = kwargs.get("server_settings")
    if settings is not None and settings != {} and settings != {"default_transaction_read_only": "on"}:
        raise DatabaseSafetyError("test database server_settings are restricted to read-only mode")
    return value


def _install_database_isolation(monkeypatch: pytest.MonkeyPatch):
    original_connect = asyncpg.connect
    original_create_pool = asyncpg.create_pool

    async def safe_connect(*args, **kwargs):
        require_safe_test_database(_dsn(args, kwargs))
        return await original_connect(*args, **kwargs)

    def safe_create_pool(*args, **kwargs):
        require_safe_test_database(_dsn(args, kwargs))
        return original_create_pool(*args, **kwargs)

    monkeypatch.setattr(asyncpg, "connect", safe_connect)
    monkeypatch.setattr(asyncpg, "create_pool", safe_create_pool)
    # Public aliases and pool reconnects converge here before asyncpg parses
    # configuration, reads credential files, resolves DNS, or opens a socket.
    connect_utils = getattr(asyncpg, "connect_utils", None)
    if connect_utils is not None:
        original_internal_connect = connect_utils._connect

        async def safe_internal_connect(*args, **kwargs):
            require_safe_test_database(_dsn(args, kwargs))
            return await original_internal_connect(*args, **kwargs)

        monkeypatch.setattr(connect_utils, "_connect", safe_internal_connect)


def pytest_configure(config):
    """Protect collection/imports and session fixtures, not only test bodies."""
    config.addinivalue_line(
        "markers",
        "local_env: needs files or a runtime that exist only on the developer machine "
        "(local artifacts, .venv-research, running Ollama); excluded in CI via -m 'not local_env'",
    )
    patch = pytest.MonkeyPatch()
    config._tim_database_patch = patch
    patch.setenv("TIM_RUNTIME_ENV", "test")
    patch.setenv("TIM_DATABASE_SECRET_PROVIDER", "url-env")
    patch.setenv("TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS", "true")
    _install_database_isolation(patch)


def pytest_unconfigure(config):
    patch = getattr(config, "_tim_database_patch", None)
    if patch is not None:
        patch.undo()


@pytest.fixture(autouse=True)
def enforce_database_isolation(monkeypatch: pytest.MonkeyPatch):
    """Reapply around test-local fakes while retaining the session guard."""
    _install_database_isolation(monkeypatch)
