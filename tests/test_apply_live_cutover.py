import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("apply_live_cutover", ROOT / "scripts/apply_live_cutover.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stop(Exception):
    pass


@pytest.mark.parametrize("timeout", [None, 42.0])
def test_cutover_connection_uses_a_long_statement_timeout(monkeypatch, tmp_path, timeout):
    # tim-core-01: deferring 50k pending rows in a 15M-row outbox took longer than 60 s.
    module = load()
    seen = {}

    async def fake_connect(*args, **kwargs):
        seen.update(kwargs)
        raise Stop

    monkeypatch.setattr(module.asyncpg, "connect", fake_connect)
    monkeypatch.setattr(module, "settings", SimpleNamespace(database_url="postgresql://tim@127.0.0.1/tim", symbol="BTCUSDT"))
    call = module.run(True, tmp_path / "out.json") if timeout is None else module.run(True, tmp_path / "out.json", timeout)
    with pytest.raises(Stop):
        asyncio.run(call)
    assert seen["command_timeout"] == (module.DEFAULT_COMMAND_TIMEOUT if timeout is None else timeout)
    assert module.DEFAULT_COMMAND_TIMEOUT >= 900


def test_cutover_still_refuses_without_apply(tmp_path):
    result = asyncio.run(load().run(False, tmp_path / "out.json"))
    assert result["status"] == "REFUSED" and result["trading_actions"] == 0
