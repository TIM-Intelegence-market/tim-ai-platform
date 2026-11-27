"""Guards of the S2 dry run (needs TIM_DURABLE_TEST_DATABASE_URL); the run itself is manual."""
from __future__ import annotations

import os

import pytest

from src.archive_sync import dryrun

DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")


@pytest.mark.asyncio
async def test_dry_run_refuses_a_target_that_is_not_a_throwaway_archive_dryrun_database():
    if not DATABASE_URL:
        pytest.skip("isolated PostgreSQL test URL not provided")
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
    try:
        with pytest.raises(AssertionError, match="archive_dryrun"):
            await dryrun._guard_target(connection)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_dry_run_opens_the_source_read_only(monkeypatch):
    if not DATABASE_URL:
        pytest.skip("isolated PostgreSQL test URL not provided")
    monkeypatch.setenv("TIM_ARCHIVE_SOURCE_URL", DATABASE_URL)
    connection = await dryrun._connect("TIM_ARCHIVE_SOURCE_URL", read_only=True)
    try:
        assert await connection.fetchval("SHOW default_transaction_read_only") == "on"
        with pytest.raises(Exception, match="read-only"):
            await connection.execute("CREATE TEMP TABLE should_fail (x int)")
    finally:
        await connection.close()


def test_child_processes_never_get_the_source_url(monkeypatch):
    monkeypatch.setenv("TIM_ARCHIVE_SOURCE_URL", "postgresql://x")
    assert "TIM_ARCHIVE_SOURCE_URL" not in dryrun._env_for_child()
