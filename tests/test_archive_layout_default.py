"""INFRA-08 draft: layout v2 is the preferred layout for new archive schemas created by the CLI.

The library default (``ensure_schema`` without a layout) stays v1, and an existing schema always
keeps its layout. Needs TIM_DURABLE_TEST_DATABASE_URL.
"""
from __future__ import annotations

import argparse
import uuid

import pytest

from src.archive_sync import __main__ as cli
from src.archive_sync import importer
from src.archive_sync.common import ArchiveSyncError
from tests import test_archive_sync as base


@pytest.fixture
def schema_name():
    if not base.DATABASE_URL:
        pytest.skip("isolated PostgreSQL test URL not provided")
    return f"arch_default_{uuid.uuid4().hex[:10]}"


async def _drop(*schemas: str) -> None:
    import asyncpg

    connection = await asyncpg.connect(base.DATABASE_URL)
    try:
        for schema in schemas:
            await connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    finally:
        await connection.close()


def _args(**values) -> argparse.Namespace:
    return argparse.Namespace(**values)


def test_preferred_layout_is_v2_and_known():
    assert importer.PREFERRED_NEW_LAYOUT == "v2"
    assert importer.PREFERRED_NEW_LAYOUT in importer.LAYOUTS


def test_cli_init_help_names_v2_as_default():
    parser = cli.build_parser()
    init = parser._subparsers._group_actions[0].choices["init"]
    layout = next(a for a in init._actions if a.dest == "layout")
    assert layout.default is None and "default v2" in layout.help


@pytest.mark.asyncio
async def test_cli_init_creates_new_schemas_as_v2(schema_name, monkeypatch):
    monkeypatch.setenv("TIM_ARCHIVE_TARGET_URL", base.DATABASE_URL)
    try:
        report = await cli._run(_args(command="init", schema=schema_name, layout=None))
        assert report == {"schema": schema_name, "initialised": True, "layout": "v2"}
        # Running init again keeps it, and asking for v1 on it is refused instead of converting.
        assert (await cli._run(_args(command="init", schema=schema_name, layout=None)))["layout"] == "v2"
        with pytest.raises(ArchiveSyncError, match="no conversion"):
            await cli._run(_args(command="init", schema=schema_name, layout="v1"))
    finally:
        await _drop(schema_name)


@pytest.mark.asyncio
async def test_cli_keeps_an_existing_v1_schema_as_v1(schema_name, monkeypatch):
    import asyncpg

    monkeypatch.setenv("TIM_ARCHIVE_TARGET_URL", base.DATABASE_URL)
    connection = await asyncpg.connect(base.DATABASE_URL)
    try:
        assert await importer.ensure_schema(connection, schema_name, "v1") == "v1"
        assert await importer.layout_for_new_schema(connection, schema_name) is None
        assert (await cli._run(_args(command="init", schema=schema_name, layout=None)))["layout"] == "v1"
        assert await importer.archive_layout(connection, schema_name) == "v1"
    finally:
        await connection.close()
        await _drop(schema_name)


@pytest.mark.asyncio
async def test_cli_import_into_a_missing_schema_creates_v2(schema_name, monkeypatch, tmp_path):
    import asyncpg

    monkeypatch.setenv("TIM_ARCHIVE_TARGET_URL", base.DATABASE_URL)
    (tmp_path / "in").mkdir()
    try:
        report = await cli._run(_args(command="import", schema=schema_name, symbol=base.SYMBOL,
                                      dir=str(tmp_path / "in"), gate_path=str(tmp_path)))
        assert report["summary"] == {}
        connection = await asyncpg.connect(base.DATABASE_URL)
        try:
            assert await importer.archive_layout(connection, schema_name) == "v2"
        finally:
            await connection.close()
    finally:
        await _drop(schema_name)


@pytest.mark.asyncio
async def test_library_default_is_unchanged_v1(schema_name):
    import asyncpg

    connection = await asyncpg.connect(base.DATABASE_URL)
    try:
        assert await importer.layout_for_new_schema(connection, schema_name) == "v2"
        assert await importer.layout_for_new_schema(connection, schema_name, "v1") == "v1"
        assert await importer.ensure_schema(connection, schema_name) == "v1"
    finally:
        await connection.close()
        await _drop(schema_name)
