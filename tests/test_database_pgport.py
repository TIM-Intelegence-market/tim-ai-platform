from __future__ import annotations

import pytest

from src.database.connection import Database
from src.database.safety import DatabaseSafetyError, require_safe_test_database
from tests.test_database_target_overrides import ISOLATED, guarded_driver


PORTLESS = "postgresql://fixture:synthetic@127.0.0.1/tim_override_test"


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword_dsn", [False, True], ids=["positional-dsn", "keyword-dsn"])
@pytest.mark.parametrize("pgport", ["6543", "5432", "", None], ids=["conflict", "matching", "empty", "unset"])
async def test_portless_pgport_fails_before_driver(guarded_driver, monkeypatch, keyword_dsn, pgport):
    driver, calls, _ = guarded_driver
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", PORTLESS)
    if pgport is None:
        monkeypatch.delenv("PGPORT", raising=False)
    else:
        monkeypatch.setenv("PGPORT", pgport)
    args, kwargs = ((), {"dsn": PORTLESS}) if keyword_dsn else ((PORTLESS,), {})
    with pytest.raises(DatabaseSafetyError, match="explicit URL port is required"):
        await driver(*args, **kwargs)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword_dsn", [False, True], ids=["positional-dsn", "keyword-dsn"])
async def test_explicit_port_with_pgport_reaches_fake_driver(guarded_driver, monkeypatch, keyword_dsn):
    driver, calls, result = guarded_driver
    monkeypatch.setenv("PGPORT", "6543")
    args, kwargs = ((), {"dsn": ISOLATED}) if keyword_dsn else ((ISOLATED,), {})
    assert await driver(*args, **kwargs) is result
    assert calls == [(args, kwargs)]


@pytest.mark.parametrize("authority", ["127.0.0.1:", "[::1]", "localhost"])
def test_portless_url_forms_are_rejected(authority):
    url = f"postgresql://fixture:synthetic@{authority}/tim_override_test"
    with pytest.raises(DatabaseSafetyError, match="explicit URL port is required"):
        require_safe_test_database(url, {"TIM_DURABLE_TEST_DATABASE_URL": url, "PGPORT": "6543"})


def test_explicit_connection_port_matches_portless_allowlist():
    url = PORTLESS.replace("127.0.0.1/", "127.0.0.1:5432/")
    approved = require_safe_test_database(url, {"TIM_DURABLE_TEST_DATABASE_URL": PORTLESS, "PGPORT": "6543"})
    assert approved.port == 5432


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["connect", "initialize_schema"])
async def test_database_rejects_portless_url_before_io(monkeypatch, tmp_path, operation):
    for key in ("TIM_DATABASE_URL", "TIM_RUNTIME_DATABASE_URL", "DATABASE_URL", "TIM_DATABASE_NAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TIM_RUNTIME_ENV", "test")
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", PORTLESS)
    monkeypatch.setenv("PGPORT", "6543")
    calls = []

    async def forbidden_pool(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("pool must not be called")

    monkeypatch.setattr("src.database.connection.asyncpg.create_pool", forbidden_pool)
    database = Database(PORTLESS)
    args = (tmp_path / "must-not-be-read.sql",) if operation == "initialize_schema" else ()
    with pytest.raises(DatabaseSafetyError, match="explicit URL port is required"):
        await getattr(database, operation)(*args)
    assert calls == []
