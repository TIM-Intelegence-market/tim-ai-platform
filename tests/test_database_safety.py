from __future__ import annotations

import pytest

from src.database.connection import Database
from src.database.safety import DatabaseSafetyError, guard_database_connection, require_safe_test_database


PRODUCTION = "postgresql://tim:secret@127.0.0.1:5432/tim"
ISOLATED = "postgresql://tim:secret@127.0.0.1:55432/tim_governance_test"


def test_production_url_is_rejected_in_test_context() -> None:
    env = {"TIM_RUNTIME_ENV": "test", "TIM_DURABLE_TEST_DATABASE_URL": PRODUCTION}
    with pytest.raises(DatabaseSafetyError, match="production-like"):
        require_safe_test_database(PRODUCTION, env)


def test_missing_test_url_has_no_runtime_fallback() -> None:
    with pytest.raises(DatabaseSafetyError, match="runtime fallback is forbidden"):
        require_safe_test_database(PRODUCTION, {"TIM_RUNTIME_ENV": "test"})


def test_explicit_isolated_database_is_allowed() -> None:
    fingerprint = require_safe_test_database(
        ISOLATED, {"TIM_RUNTIME_ENV": "test", "TIM_DURABLE_TEST_DATABASE_URL": ISOLATED}
    )
    assert fingerprint.database == "tim_governance_test"


def test_runtime_database_path_is_unaffected() -> None:
    guard_database_connection(PRODUCTION, {"TIM_RUNTIME_ENV": "production"})


@pytest.mark.asyncio
async def test_connect_guard_fails_before_pool_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    async def forbidden_pool(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setenv("TIM_RUNTIME_ENV", "test")
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", PRODUCTION)
    monkeypatch.setattr("src.database.connection.asyncpg.create_pool", forbidden_pool)
    with pytest.raises(DatabaseSafetyError, match="production-like"):
        await Database(PRODUCTION).connect()
    assert called is False


@pytest.mark.asyncio
async def test_schema_guard_fails_before_read_or_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIM_RUNTIME_ENV", "test")
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", PRODUCTION)
    database = Database(PRODUCTION)
    with pytest.raises(DatabaseSafetyError, match="production-like"):
        await database.initialize_schema()


def test_migration_target_mismatch_is_rejected() -> None:
    env = {"TIM_RUNTIME_ENV": "test", "TIM_DURABLE_TEST_DATABASE_URL": ISOLATED}
    with pytest.raises(DatabaseSafetyError, match="does not match"):
        require_safe_test_database(PRODUCTION, env)


def test_runtime_url_identity_rejected_despite_test_like_name():
    target = 'postgresql://test:fixture@localhost:55432/tim_test'
    env = {'TIM_RUNTIME_ENV': 'test', 'TIM_DURABLE_TEST_DATABASE_URL': target,
           'TIM_DATABASE_URL': 'postgresql://runtime:other@127.0.0.1:55432/tim_test'}
    with pytest.raises(DatabaseSafetyError, match='runtime'):
        require_safe_test_database(target, env)


@pytest.mark.parametrize('query', ['host=production', 'dbname=tim', 'port=5432'])
def test_connection_override_query_rejected(query):
    url = ISOLATED + '?' + query
    with pytest.raises(DatabaseSafetyError):
        require_safe_test_database(url, {'TIM_DURABLE_TEST_DATABASE_URL': url})


def test_encoded_production_database_name_is_rejected():
    url = 'postgresql://role:fixture@localhost/%74im'
    with pytest.raises(DatabaseSafetyError):
        require_safe_test_database(url, {'TIM_DURABLE_TEST_DATABASE_URL': url})


def test_isolated_search_path_option_remains_supported():
    url = ISOLATED + '?options=-csearch_path%3Dtim_test_run'
    assert require_safe_test_database(url, {'TIM_DURABLE_TEST_DATABASE_URL': url}).database == 'tim_governance_test'


def test_zero_port_rejected():
    url = 'postgresql://role:fixture@localhost:0/tim_test'
    with pytest.raises(DatabaseSafetyError):
        require_safe_test_database(url, {'TIM_DURABLE_TEST_DATABASE_URL': url})
