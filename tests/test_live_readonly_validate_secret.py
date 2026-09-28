"""scripts/live_readonly_validate.py takes the production secret from the runtime resolver."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "live_readonly_validate.py"


def _load():
    spec = importlib.util.spec_from_file_location("live_readonly_validate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_uses_runtime_secret_resolver_and_read_only_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    assert "find-generic-password" not in SCRIPT.read_text(encoding="utf-8")
    import config.settings as settings_module

    monkeypatch.setattr(type(settings_module.settings), "database_url", property(lambda self: "postgresql://tim:x@127.0.0.1:5432/tim"))
    calls: dict[str, object] = {"sql": []}

    class FakeConnection:
        async def execute(self, sql):
            calls["sql"].append(sql)

        async def fetch(self, sql, *args):
            calls["sql"].append(sql)
            return [{"status": "OPEN", "n": 1}] if "GROUP BY" in sql else []

        async def close(self):
            calls["closed"] = True

    async def fake_connect(dsn, timeout):
        calls["dsn"] = dsn
        return FakeConnection()

    monkeypatch.setattr(module, "asyncpg", SimpleNamespace(connect=fake_connect))
    rows, stats = asyncio.run(module.load_window())
    assert calls["dsn"] == "postgresql://tim:x@127.0.0.1:5432/tim"
    assert calls["sql"][0] == "START TRANSACTION READ ONLY" and calls["sql"][-1] == "ROLLBACK"
    assert calls["closed"] is True and rows == [] and stats == {"OPEN": 1}
