"""schema.sql keeps ingestion_outbox on aggressive autovacuum settings.

Production evidence: with default scale factors the visibility map of the
multi-gigabyte outbox decayed and every active-work count took seconds. The
schema therefore sets per-table autovacuum options, idempotently, without ever
failing or hanging the runtime's --init-schema.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
import pytest_asyncio

from src.database.connection import Database


DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="isolated durable-ingestion PostgreSQL URL not provided")
WANTED = {
    "autovacuum_vacuum_scale_factor=0.01",
    "autovacuum_analyze_scale_factor=0.01",
    "autovacuum_vacuum_insert_scale_factor=0.01",
}


@pytest_asyncio.fixture
async def database():
    assert DATABASE_URL is not None
    value = Database(DATABASE_URL, min_size=1, max_size=3)
    await value.connect()
    await value.initialize_schema()
    yield value
    await value.initialize_schema()
    await value.close()


async def options(database) -> set[str]:
    async with database.acquire() as connection:
        value = await connection.fetchval("SELECT reloptions FROM pg_class WHERE oid='ingestion_outbox'::regclass")
    return set(value or [])


@pytest.mark.asyncio
async def test_schema_sets_outbox_autovacuum_options_idempotently(database) -> None:
    assert WANTED <= await options(database)
    await database.initialize_schema()
    await database.initialize_schema()
    assert WANTED <= await options(database)


@pytest.mark.asyncio
async def test_schema_restores_options_and_keeps_unrelated_ones(database) -> None:
    async with database.acquire() as connection:
        await connection.execute(
            "ALTER TABLE ingestion_outbox RESET (autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor,"
            " autovacuum_vacuum_insert_scale_factor)"
        )
        await connection.execute("ALTER TABLE ingestion_outbox SET (fillfactor=90)")
    try:
        assert not WANTED & await options(database)
        await database.initialize_schema()
        assert WANTED | {"fillfactor=90"} <= await options(database)
    finally:
        async with database.acquire() as connection:
            await connection.execute("ALTER TABLE ingestion_outbox RESET (fillfactor)")


def autovacuum_block() -> str:
    schema = (Path(__file__).resolve().parents[1] / "src/database/schema.sql").read_text(encoding="utf-8")
    start = schema.index("-- The outbox grows by every trade")
    end = schema.index("$tim$;", start) + len("$tim$;")
    return schema[start:end]


@pytest.mark.asyncio
async def test_option_block_does_not_hang_or_fail_behind_a_conflicting_lock(database) -> None:
    # The pre-existing CREATE INDEX statements already wait for a running vacuum;
    # this proves only that the new block adds no unbounded wait and no failure.
    async with database.acquire() as connection:
        await connection.execute("ALTER TABLE ingestion_outbox RESET (autovacuum_vacuum_scale_factor)")
    async with database.acquire() as holder:
        async with holder.transaction():
            # SHARE UPDATE EXCLUSIVE is what a running (anti-wraparound) vacuum holds.
            await holder.execute("LOCK TABLE ingestion_outbox IN SHARE UPDATE EXCLUSIVE MODE")
            async with database.acquire() as connection:
                started = time.monotonic()
                async with connection.transaction():
                    await connection.execute(autovacuum_block())
                    assert await connection.fetchval("SHOW lock_timeout") == "0", "lock_timeout restored"
                assert time.monotonic() - started < 20
    assert "autovacuum_vacuum_scale_factor=0.01" not in await options(database)
    await database.initialize_schema()
    assert WANTED <= await options(database)
