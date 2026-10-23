from __future__ import annotations

from pathlib import Path

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


# Parallel runs (pytest-xdist, used in CI):
# - Every module that talks to the shared PostgreSQL test database runs on one worker, so two workers
#   never touch the same tables at the same time (mark xdist_group, needs `--dist loadgroup`).
# - Modules that scan the real repository or its runtime files get the mark `serial`. They expect no
#   other process to write there during the scan; CI runs them in a second, non-parallel step.
# Without xdist both marks change nothing.
_POSTGRES_GROUP = "postgres-test-db"
_POSTGRES_HINT = "TIM_DURABLE_TEST_DATABASE_URL"
_SERIAL_DIRS = ("tim_manager", "graph_mcp")
_SERIAL_HINTS = ("scan_project", "refresh_runtime_readonly")


def _module_text(path, cache: dict) -> str:
    if path not in cache:
        try:
            cache[path] = path.read_text(encoding="utf-8")
        except OSError:
            cache[path] = ""
    return cache[path]


# tryfirst: xdist reads the group mark in its own collection hook, so the mark must already be set.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    tests_root = Path(__file__).resolve().parent
    cache: dict = {}
    for item in items:
        text = _module_text(item.path, cache)
        if _POSTGRES_HINT in text:
            item.add_marker(pytest.mark.xdist_group(_POSTGRES_GROUP))
        try:
            parts = item.path.resolve().relative_to(tests_root).parts
        except ValueError:
            parts = ()
        if (parts and parts[0] in _SERIAL_DIRS) or any(hint in text for hint in _SERIAL_HINTS):
            item.add_marker(pytest.mark.serial)
