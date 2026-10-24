import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.reflection.reader import (
    READ_ONLY_SETTINGS,
    SELECT_CASES,
    load_database,
    load_export,
    rows_from_export,
    select_window,
)

FIXTURE = Path(__file__).parent / "fixtures" / "reflection" / "export.json"
START = datetime(2026, 11, 23, tzinfo=timezone.utc)
END = START + timedelta(days=7)


def _row(**overrides):
    row = {
        "observation_id": "ofobs_x",
        "kind": "STRONG_BUYER_ACTIVITY",
        "symbol": "BTCUSDT",
        "observed_at": "2026-11-24T10:00:00+00:00",
        "rule_version": "1.0.0",
        "validation_version": "1.0.0",
        "outcome": "PRICE_INCREASED",
        "complete": True,
        "horizons": [{"minutes": 5, "price_change_percent": "0.2"}, {"minutes": 30, "price_change_percent": "-0.01"}],
        "validated_through": "2026-11-24T10:30:00+00:00",
    }
    row.update(overrides)
    return row


def test_export_join_skips_incomplete_validation():
    cases = load_export(FIXTURE, START, END)
    assert len(cases) == 130
    assert all(case.observed_at >= START and case.observed_at < END for case in cases)
    assert len(rows_from_export(FIXTURE)) == 261  # the incomplete one is read but dropped by the window filter


def test_window_drops_unknown_outcomes_and_foreign_versions():
    rows = [
        _row(),
        _row(observation_id="late", observed_at="2026-11-29T23:50:00+00:00", validated_through="2026-11-30T00:20:00+00:00"),
        _row(observation_id="before", observed_at="2026-11-22T23:59:00+00:00"),
        _row(observation_id="incomplete", complete=False),
        _row(observation_id="no-outcome", outcome=None),
        _row(observation_id="other-version", validation_version="0.9.0"),
    ]
    assert [case.observation_id for case in select_window(rows, START, END)] == ["ofobs_x"]


def test_horizon_outcome_uses_live_sideways_threshold():
    case = select_window([_row()], START, END)[0]
    assert case.outcome_at(5) == "PRICE_INCREASED"
    assert case.outcome_at(30) == "PRICE_SIDEWAYS"
    assert case.outcome_at(15) is None


def test_naive_timestamp_is_rejected():
    with pytest.raises(ValueError):
        select_window([_row(observed_at="2026-11-24T10:00:00")], START, END)


def test_database_path_is_read_only_single_select(monkeypatch):
    url = "postgresql://reader@127.0.0.1:5432/reflection_test"
    for key in ("TIM_DATABASE_URL", "TIM_RUNTIME_DATABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TIM_DURABLE_TEST_DATABASE_URL", url)
    calls = {}

    class Connection:
        async def fetch(self, statement, *args):
            calls["statement"], calls["args"] = statement, args
            return [_row()]

        async def close(self):
            calls["closed"] = True

    async def connect(dsn, **kwargs):
        calls["dsn"], calls["kwargs"] = dsn, kwargs
        return Connection()

    cases = asyncio.run(load_database(url, START, END, connect=connect))
    assert [case.observation_id for case in cases] == ["ofobs_x"]
    assert calls["kwargs"]["server_settings"] == {"default_transaction_read_only": "on"}
    assert calls["statement"] == SELECT_CASES
    assert calls["args"] == (START, END)
    assert calls["closed"] is True
    statement = SELECT_CASES.upper()
    assert statement.startswith("SELECT ") and ";" not in statement
    for word in ("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER", "TRUNCATE", "GRANT"):
        assert word not in statement


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="isolated PostgreSQL URL not provided")
def test_real_database_rejects_writes_on_reflection_connection():
    import asyncpg

    from src.database.connection import Database

    observation_id = "ofobs_reflectiontest00000001"

    async def scenario():
        database = Database(DATABASE_URL, min_size=1, max_size=1)
        await database.connect()
        await database.initialize_schema()
        try:
            async with database.acquire() as connection:
                await connection.execute("DELETE FROM orderflow_observations WHERE observation_id=$1", observation_id)
                await connection.execute(
                    "INSERT INTO orderflow_observations VALUES ($1,'STRONG_BUYER_ACTIVITY','REFLX','60s',$2,'test',$3::jsonb,'1.0.0',$4,'BINANCE_SPOT_AGGTRADE_DETERMINISTIC','OBSERVE')",
                    observation_id, START + timedelta(hours=1), json.dumps([{"a": 1}, {"b": 2}]), "a" * 64,
                )
                await connection.execute(
                    "INSERT INTO orderflow_validations VALUES ($1,'REFLX',$2,100,$3::jsonb,true,'PRICE_INCREASED',$4,$5,'1.0.0','OBSERVE')",
                    observation_id, START + timedelta(hours=1),
                    json.dumps([{"minutes": 30, "price_change_percent": "0.3"}]), "b" * 64, START + timedelta(hours=1, minutes=30),
                )
            cases = await load_database(DATABASE_URL, START, END)
            assert observation_id in [case.observation_id for case in cases]
            reader = await asyncpg.connect(DATABASE_URL, server_settings=dict(READ_ONLY_SETTINGS))
            try:
                with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
                    await reader.execute("DELETE FROM orderflow_observations WHERE observation_id=$1", observation_id)
            finally:
                await reader.close()
        finally:
            async with database.acquire() as connection:
                await connection.execute("DELETE FROM orderflow_observations WHERE observation_id=$1", observation_id)
            await database.close()

    asyncio.run(scenario())
