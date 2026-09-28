"""Offline regressions for the Phase-0 database isolation boundary.

Every driver used here is an in-memory stand-in. No database or socket is used.
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

from src.database.safety import DatabaseSafetyError, require_safe_test_database
from tests import conftest as isolation
from tests.test_database_target_overrides import ISOLATED, guarded_driver


@pytest.mark.parametrize("url", [
    pytest.param(ISOLATED.replace("/tim_override_test", "//tim_override_test"), id="double-slash"),
    pytest.param(ISOLATED.replace("/tim_override_test", "///tim_override_test"), id="triple-slash"),
    pytest.param(ISOLATED.replace("/tim_override_test", "/%2Ftim_override_test"), id="encoded-slash"),
    pytest.param(ISOLATED.replace("synthetic@", "synthetic@production.invalid@"), id="multiple-at"),
    pytest.param(ISOLATED.replace("synthetic@", "synthetic@%2Ftmp%2Fforeign@"), id="encoded-socket-before-at"),
    pytest.param(ISOLATED.replace("fixture:", "fixture%00database%00tim:"), id="nul-username"),
    pytest.param(ISOLATED.replace("synthetic@", "synthetic%00database%00tim@"), id="nul-password"),
    pytest.param(ISOLATED.replace("tim_override_test", "tim%00application_name%00isolated_test"), id="nul-database"),
    pytest.param(ISOLATED.replace("tim_override_test", "tim\x00application_name\x00isolated_test"), id="literal-nul-database"),
    pytest.param(ISOLATED.replace("127.0.0.1", "%31%32%37.0.0.1"), id="encoded-host"),
    pytest.param(ISOLATED.replace(":55432/", ":%35%35%34%33%32/"), id="encoded-port"),
    pytest.param(ISOLATED.replace("127.0.0.1", "127.0.0.1,production.invalid"), id="multiple-hosts"),
    pytest.param(ISOLATED.replace("127.0.0.1", "[::1]ignored"), id="ipv6-suffix-before-port"),
    pytest.param(ISOLATED.replace("127.0.0.1", "[::1]:5432:ignored"), id="ipv6-extra-port-suffix"),
    pytest.param(ISOLATED + "?options=-csearch_path%3Dpublic", id="protected-search-path"),
    pytest.param(ISOLATED + "?database=tim", id="startup-database-query"),
])
def test_ambiguous_target_is_rejected_even_when_explicitly_allowlisted(url):
    with pytest.raises(DatabaseSafetyError):
        require_safe_test_database(url, {"TIM_DURABLE_TEST_DATABASE_URL": url})


def test_encoded_credentials_preserve_the_explicit_database_target():
    url = ISOLATED.replace("fixture:synthetic", "fixture%40test:synthetic%40secret")
    assert require_safe_test_database(url, {"TIM_DURABLE_TEST_DATABASE_URL": url}).database == "tim_override_test"


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [
    pytest.param({"database": "tim"}, id="startup-database"),
    pytest.param({"user": "runtime"}, id="startup-user"),
    pytest.param({"options": "-csearch_path=public"}, id="options-search-path"),
    pytest.param({"search_path": "public"}, id="direct-search-path"),
    pytest.param({"application_name\x00database": "tim"}, id="nul-setting-key"),
    pytest.param({"application_name": "fixture\x00database\x00tim"}, id="nul-setting-value"),
    pytest.param({"default_transaction_read_only": "off"}, id="read-only-disabled"),
    pytest.param({"default_transaction_read_only": "on", "database": "tim"}, id="allowed-setting-with-injection"),
])
async def test_startup_overrides_fail_before_either_driver(guarded_driver, settings):
    driver, calls, _ = guarded_driver
    with pytest.raises(DatabaseSafetyError):
        await driver(ISOLATED, server_settings=settings)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("settings", [None, {}, {"default_transaction_read_only": "on"}])
async def test_read_only_startup_settings_remain_supported(guarded_driver, settings):
    driver, calls, result = guarded_driver
    assert await driver(ISOLATED, server_settings=settings) is result
    assert calls == [((ISOLATED,), {"server_settings": settings})]


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    pytest.param({"user": "fixture\x00database\x00tim"}, id="nul-user"),
    pytest.param({"password": "synthetic\x00database\x00tim"}, id="nul-password"),
    pytest.param({"user": "fixture\n"}, id="newline-user"),
    pytest.param({"password": "synthetic\x7f"}, id="delete-password"),
])
async def test_credential_control_characters_fail_before_driver(guarded_driver, overrides):
    driver, calls, _ = guarded_driver
    with pytest.raises(DatabaseSafetyError):
        await driver(ISOLATED, **overrides)
    assert calls == []


@pytest.fixture
def configured_memory_driver(monkeypatch):
    """Call the real session hooks around fake driver entrypoints only."""
    for key in ("TIM_DATABASE_URL", "TIM_RUNTIME_DATABASE_URL", "DATABASE_URL", "TIM_DATABASE_NAME",
                "TIM_RUNTIME_ENV", "TIM_ENV", "PYTEST_CURRENT_TEST"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", ISOLATED)
    monkeypatch.setenv("TIM_DATABASE_SECRET_PROVIDER", "keychain")
    monkeypatch.setenv("TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS", "false")
    calls = []
    pool_calls = []
    result = object()

    async def memory_backend(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    backend = SimpleNamespace(_connect=memory_backend)

    async def memory_connect(dsn=None, **kwargs):
        # asyncpg.connection.connect forwards default target kwargs as None.
        kwargs = {"host": None, "port": None, "database": None, **kwargs}
        return await backend._connect(dsn=dsn, **kwargs)

    class MemoryPool:
        def __init__(self):
            self.entered = False
            self.exited = False

        def __await__(self):
            async def initialized():
                return self
            return initialized().__await__()

        async def __aenter__(self):
            self.entered = True
            return self

        async def __aexit__(self, *args):
            self.exited = True

    pool = MemoryPool()

    def memory_create_pool(*args, **kwargs):
        pool_calls.append((args, kwargs))
        return pool

    fake = SimpleNamespace(connect=memory_connect, create_pool=memory_create_pool, connect_utils=backend)
    cached_connect = fake.connect
    monkeypatch.setattr(isolation, "asyncpg", fake)
    config = SimpleNamespace()
    isolation.pytest_configure(config)
    try:
        yield SimpleNamespace(driver=fake, cached_connect=cached_connect, calls=calls,
                              pool_calls=pool_calls, pool=pool, result=result,
                              configured_without_current_test="PYTEST_CURRENT_TEST" not in os.environ,
                              configured_runtime_env=os.environ.get("TIM_RUNTIME_ENV"),
                              configured_secret_provider=os.environ.get("TIM_DATABASE_SECRET_PROVIDER"),
                              configured_url_gate=os.environ.get("TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS"))
    finally:
        isolation.pytest_unconfigure(config)
        assert os.environ["TIM_DATABASE_SECRET_PROVIDER"] == "keychain"
        assert os.environ["TIM_ALLOW_DATABASE_URL_ENV_FOR_TESTS"] == "false"


@pytest.mark.asyncio
@pytest.mark.parametrize("entrypoint", ["public", "cached-before-configure", "backend"])
@pytest.mark.parametrize("kwargs", [
    pytest.param({"host": "production.invalid"}, id="target-override"),
    pytest.param({"server_settings": {"database": "tim"}}, id="startup-override"),
])
async def test_session_guard_rejects_cached_and_backend_bypasses(configured_memory_driver, entrypoint, kwargs):
    memory = configured_memory_driver
    driver = {"public": memory.driver.connect, "cached-before-configure": memory.cached_connect,
              "backend": memory.driver.connect_utils._connect}[entrypoint]
    with pytest.raises(DatabaseSafetyError):
        await driver(dsn=ISOLATED, **kwargs)
    assert memory.calls == []


@pytest.mark.asyncio
async def test_backend_default_none_target_kwargs_remain_supported(configured_memory_driver):
    memory = configured_memory_driver
    assert await memory.cached_connect(ISOLATED) is memory.result
    assert memory.calls == [((), {"dsn": ISOLATED, "host": None, "port": None, "database": None})]


@pytest.mark.asyncio
async def test_pool_keeps_await_and_async_context_manager_protocol(configured_memory_driver):
    memory = configured_memory_driver
    pool = memory.driver.create_pool(ISOLATED)
    assert pool is memory.pool
    assert await pool is memory.pool
    async with pool as acquired:
        assert acquired is memory.pool
        assert pool.entered
    assert pool.exited
    assert memory.pool_calls == [((ISOLATED,), {})]


def test_pool_rejects_unsafe_target_before_factory_execution(configured_memory_driver):
    memory = configured_memory_driver
    with pytest.raises(DatabaseSafetyError):
        memory.driver.create_pool(ISOLATED, database="tim")
    assert memory.pool_calls == []


def test_configure_guard_protects_module_collection_before_test_fixtures(configured_memory_driver):
    memory = configured_memory_driver
    # Module-level execution occurs before pytest starts a test's fixtures.
    namespace = {"asyncio": asyncio, "driver": memory.driver,
                 "production_url": "postgresql://fixture:synthetic@127.0.0.1:5432/tim"}
    with pytest.raises(DatabaseSafetyError):
        exec(compile("asyncio.run(driver.connect(production_url))", "synthetic_collected_module.py", "exec"), namespace)
    assert memory.calls == []


def test_configure_marks_test_context_before_pytest_current_test_exists(configured_memory_driver):
    assert configured_memory_driver.configured_without_current_test
    assert configured_memory_driver.configured_runtime_env == "test"


def test_configure_uses_only_explicit_test_credentials(configured_memory_driver):
    assert configured_memory_driver.configured_secret_provider == "url-env"
    assert configured_memory_driver.configured_url_gate == "true"


@pytest.mark.parametrize("runtime_key", ["TIM_DATABASE_URL", "TIM_RUNTIME_DATABASE_URL", "DATABASE_URL"])
def test_runtime_target_cannot_be_allowlisted_by_changing_credentials(runtime_key):
    runtime = ISOLATED.replace("fixture:synthetic@127.0.0.1", "runtime:other@localhost")
    with pytest.raises(DatabaseSafetyError, match="runtime"):
        require_safe_test_database(ISOLATED, {"TIM_DURABLE_TEST_DATABASE_URL": ISOLATED, runtime_key: runtime})


@pytest.mark.parametrize("pgport", ["55432", "5432,55432", "not-a-port"])
def test_portless_runtime_target_with_pgport_is_not_treated_as_distinct(pgport):
    runtime = ISOLATED.replace(":55432/", "/")
    with pytest.raises(DatabaseSafetyError, match="PGPORT"):
        require_safe_test_database(ISOLATED, {
            "TIM_DURABLE_TEST_DATABASE_URL": ISOLATED, "TIM_DATABASE_URL": runtime, "PGPORT": pgport,
        })


@pytest.mark.parametrize("pgport", ["", "5432"])
def test_portless_distinct_runtime_with_default_pgport_remains_supported(pgport):
    runtime = "postgresql://runtime:synthetic@127.0.0.1/tim"
    approved = require_safe_test_database(ISOLATED, {
        "TIM_DURABLE_TEST_DATABASE_URL": ISOLATED, "TIM_DATABASE_URL": runtime, "PGPORT": pgport,
    })
    assert approved.port == 55432


def test_invalid_runtime_url_error_redacts_credentials():
    runtime = "postgresql://runtime:private-runtime-password@127.0.0.1:not-a-port/tim"
    with pytest.raises(DatabaseSafetyError) as error:
        require_safe_test_database(ISOLATED, {"TIM_DURABLE_TEST_DATABASE_URL": ISOLATED, "TIM_DATABASE_URL": runtime})
    assert "private-runtime-password" not in str(error.value)
