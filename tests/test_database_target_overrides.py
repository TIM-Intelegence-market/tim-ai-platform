from __future__ import annotations

import asyncpg
import pytest

from src.database.safety import DatabaseSafetyError
from tests.conftest import enforce_database_isolation


ISOLATED = "postgresql://fixture:synthetic@127.0.0.1:55432/tim_override_test"


@pytest.fixture(params=["connect", "create_pool"])
def guarded_driver(request, monkeypatch: pytest.MonkeyPatch):
    """Exercise the real fixture wrappers with memory-only driver originals."""
    calls = []
    result = object()

    async def fake_driver(*args, **kwargs):
        calls.append((args, kwargs))
        return result

    for key in ("TIM_DATABASE_URL", "TIM_RUNTIME_DATABASE_URL", "DATABASE_URL", "TIM_DATABASE_NAME"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", ISOLATED)
    monkeypatch.setattr(asyncpg, "connect", fake_driver)
    monkeypatch.setattr(asyncpg, "create_pool", fake_driver)
    enforce_database_isolation.__wrapped__(monkeypatch)
    return getattr(asyncpg, request.param), calls, result


@pytest.mark.asyncio
@pytest.mark.parametrize("keyword_dsn", [False, True], ids=["positional-dsn", "keyword-dsn"])
@pytest.mark.parametrize("overrides", [
    pytest.param({"host": "production.invalid"}, id="different-host"),
    pytest.param({"port": 5432}, id="different-port"),
    pytest.param({"database": "tim"}, id="production-database"),
    pytest.param({"host": "127.0.0.1", "port": 5432, "database": "tim"}, id="production-target"),
    pytest.param({"host": ["127.0.0.1", "production.invalid"]}, id="host-list"),
    pytest.param({"port": [5432]}, id="port-list"),
    pytest.param({"database": ""}, id="empty-database"),
    pytest.param({"host": "127.0.0.1"}, id="matching-host"),
    pytest.param({"port": 55432}, id="matching-port"),
    pytest.param({"database": "tim_override_test"}, id="matching-database"),
])
async def test_target_overrides_fail_before_driver(guarded_driver, keyword_dsn, overrides):
    driver, calls, _ = guarded_driver
    args, kwargs = ((), {"dsn": ISOLATED}) if keyword_dsn else ((ISOLATED,), {})
    with pytest.raises(DatabaseSafetyError, match="target overrides are forbidden"):
        await driver(*args, **kwargs, **overrides)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{}, {"host": None, "port": None, "database": None}, {"command_timeout": 30}])
async def test_dsn_only_target_reaches_fake_driver(guarded_driver, kwargs):
    driver, calls, result = guarded_driver
    assert await driver(ISOLATED, **kwargs) is result
    assert calls == [((ISOLATED,), kwargs)]


@pytest.mark.asyncio
async def test_missing_explicit_test_url_fails_before_driver(guarded_driver, monkeypatch: pytest.MonkeyPatch):
    driver, calls, _ = guarded_driver
    monkeypatch.delenv("TIM_DURABLE_TEST_DATABASE_URL")
    with pytest.raises(DatabaseSafetyError, match="runtime fallback is forbidden"):
        await driver(ISOLATED)
    assert calls == []
