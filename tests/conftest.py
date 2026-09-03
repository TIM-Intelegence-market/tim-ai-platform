from __future__ import annotations

import asyncpg
import pytest

from src.database.safety import DatabaseSafetyError, require_safe_test_database


def _dsn(args: tuple[object, ...], kwargs: dict[str, object]) -> str:
    value = args[0] if args else kwargs.get("dsn")
    if not isinstance(value, str):
        raise DatabaseSafetyError("tests must use an explicit PostgreSQL DSN")
    return value


@pytest.fixture(autouse=True)
def enforce_database_isolation(monkeypatch: pytest.MonkeyPatch):
    """Guard even direct asyncpg use, before any test opens a connection."""

    original_connect = asyncpg.connect
    original_create_pool = asyncpg.create_pool

    async def safe_connect(*args, **kwargs):
        require_safe_test_database(_dsn(args, kwargs))
        return await original_connect(*args, **kwargs)

    async def safe_create_pool(*args, **kwargs):
        require_safe_test_database(_dsn(args, kwargs))
        return await original_create_pool(*args, **kwargs)

    monkeypatch.setattr(asyncpg, "connect", safe_connect)
    monkeypatch.setattr(asyncpg, "create_pool", safe_create_pool)
