"""S2.1 draft: archive layout v2 (numeric batch reference). Needs TIM_DURABLE_TEST_DATABASE_URL.

The whole S1 scenario suite runs again against a v2 archive (same fixtures, the archive schema
is created as v2 before each test). Extra tests cover referential integrity, provenance,
crash recovery and backup/restore for v2. Layout v1 stays the default and is not changed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid

import pytest
import pytest_asyncio

from src.archive_sync import health, importer
from src.archive_sync.common import ArchiveSyncError
from tests import test_archive_sync as base

SYMBOL = base.SYMBOL
add_trades, set_cursor, export, run_import, ids_in, manifests = (
    base.add_trades, base.set_cursor, base.export, base.run_import, base.ids_in, base.manifests,
)


@pytest_asyncio.fixture
async def env(tmp_path):
    """Same isolated source/archive schemas as the S1 suite, but the archive is created as layout v2."""
    if not base.DATABASE_URL:
        pytest.skip("isolated PostgreSQL test URL not provided")
    import asyncpg

    connection = await asyncpg.connect(base.DATABASE_URL)
    tag = uuid.uuid4().hex[:10]
    src, dst = f"arch_src_{tag}", f"arch_dst_{tag}"
    await connection.execute(f"CREATE SCHEMA {src}")
    await connection.execute(
        f"""CREATE TABLE {src}.agg_trades (
            symbol TEXT NOT NULL, aggregate_trade_id BIGINT NOT NULL, trade_time TIMESTAMPTZ NOT NULL,
            price DOUBLE PRECISION NOT NULL, quantity DOUBLE PRECISION NOT NULL, buyer_is_maker BOOLEAN NOT NULL,
            source TEXT NOT NULL DEFAULT 'BINANCE_SPOT_AGGTRADE',
            ingest_timestamp TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            PRIMARY KEY (symbol, aggregate_trade_id))"""
    )
    await connection.execute(
        f"""CREATE TABLE {src}.ingestion_cursors (source TEXT, market TEXT, symbol TEXT, data_type TEXT,
            last_aggregate_trade_id BIGINT)"""
    )
    second = await asyncpg.connect(base.DATABASE_URL)
    holder = {"c": connection, "c2": second, "src": src, "dst": dst, "out": tmp_path / "out", "inbox": tmp_path / "inbox"}
    assert await importer.ensure_schema(second, dst, "v2") == "v2"
    yield holder
    await connection.execute(f"DROP SCHEMA IF EXISTS {src} CASCADE")
    await connection.execute(f"DROP SCHEMA IF EXISTS {dst} CASCADE")
    await second.close()
    await connection.close()



# The complete S1 behaviour, re-run on layout v2 (database-backed scenarios only).
for _name, _test in list(vars(base).items()):
    _code = getattr(getattr(_test, "__wrapped__", _test), "__code__", None)
    if _name.startswith("test_") and _code is not None and "env" in _code.co_varnames[: _code.co_argcount]:
        globals()[_name] = _test
del _name, _test, _code


@pytest.mark.asyncio
async def test_v2_rows_carry_a_numeric_reference_to_an_accepted_batch(env):
    await add_trades(env, range(1, 701))
    await set_cursor(env, 700)
    await export(env)
    await run_import(env)
    schema = env["dst"]
    assert await importer.archive_layout(env["c2"], schema) == "v2"
    kinds = {r["column_name"]: r["data_type"] for r in await env["c2"].fetch(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema=$1 AND table_name='agg_trades'",
        schema)}
    assert kinds["batch_no"] == "integer" and "batch_id" not in kinds
    orphans = await env["c2"].fetchval(
        f"""SELECT count(*) FROM {schema}.agg_trades a LEFT JOIN {schema}.batches b USING (batch_no)
            WHERE b.batch_no IS NULL OR b.status <> 'ACCEPTED'""")
    assert orphans == 0
    per_batch = await env["c2"].fetch(
        f"""SELECT b.row_count, count(a.*) AS n FROM {schema}.batches b
            LEFT JOIN {schema}.agg_trades a USING (batch_no) WHERE b.status='ACCEPTED' GROUP BY b.batch_no, b.row_count""")
    assert per_batch and all(r["row_count"] == r["n"] for r in per_batch)


@pytest.mark.asyncio
async def test_v2_foreign_keys_refuse_unknown_batches_and_deleting_referenced_batches(env):
    import asyncpg

    await add_trades(env, range(1, 11))
    await set_cursor(env, 10)
    await export(env)
    await run_import(env)
    schema = env["dst"]
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await env["c2"].execute(
            f"""INSERT INTO {schema}.agg_trades (aggregate_trade_id, trade_time, ingest_timestamp, price, quantity,
                batch_no, buyer_is_maker, symbol, source)
                VALUES (999, now(), now(), 1, 1, 987654, false, $1, 'BINANCE_SPOT_AGGTRADE')""", SYMBOL)
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await env["c2"].execute(f"DELETE FROM {schema}.batches WHERE status='ACCEPTED'")
    with pytest.raises(asyncpg.GeneratedAlwaysError):
        await env["c2"].execute(f"UPDATE {schema}.batches SET batch_no = batch_no + 1000")
    assert await ids_in(env, schema) == list(range(1, 11))


@pytest.mark.asyncio
async def test_v1_and_v2_keep_identical_provenance_and_identical_canonical_hashes(env):
    await add_trades(env, [i for i in range(1, 801) if i not in (77, 401)])
    await set_cursor(env, 800)
    await export(env)
    v1 = f"{env['dst']}_v1"
    try:
        await importer.ensure_schema(env["c2"], v1, "v1")
        r1 = await importer.import_directory(env["c2"], env["out"], symbol=SYMBOL, gate_path=str(env["out"]),
                                             schema=v1, usage=base.ROOMY)
        r2 = await run_import(env)
        assert r1["summary"] == r2["summary"] == {"ACCEPTED": 3}
        assert r1["state"]["holes"] == r2["state"]["holes"] == [[77, 77], [401, 401]]
        columns = "batch_id, kind, lo_id, hi_id, row_count, holes, content_sha256, file_sha256, manifest, status"
        b1 = await env["c2"].fetch(f"SELECT {columns} FROM {v1}.batches ORDER BY batch_id")
        b2 = await env["c2"].fetch(f"SELECT {columns} FROM {env['dst']}.batches ORDER BY batch_id")
        assert [dict(r) for r in b1] == [dict(r) for r in b2]
        d1 = await health.range_digest(env["c2"], table=f"{v1}.agg_trades", symbol=SYMBOL, lo=1, hi=800)
        d2 = await health.range_digest(env["c2"], table=f"{env['dst']}.agg_trades", symbol=SYMBOL, lo=1, hi=800)
        assert d1["sha256"] == d2["sha256"] and d1["rows"] == 798
        check = await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"], verify_last=10)
        assert check["status"] == "WARN" and all(v["ok"] for v in check["verified_batches"])
        assert len(check["verified_batches"]) == 3
    finally:
        await env["c2"].execute(f"DROP SCHEMA IF EXISTS {v1} CASCADE")


@pytest.mark.asyncio
async def test_v2_crash_inside_the_insert_leaves_nothing_and_the_retry_succeeds(env):
    await add_trades(env, range(1, 301))
    await set_cursor(env, 300)
    await export(env, chunk=1000)
    real_execute = env["c2"].execute

    class Crash(Exception):
        pass

    async def crashing(query, *args, **kwargs):
        result = await real_execute(query, *args, **kwargs)
        if "INSERT INTO" in query and ".agg_trades" in query and "archive_stage" in query:
            raise Crash("process died right after the insert, before commit")
        return result

    proxy = _Proxy(env["c2"], crashing)
    with pytest.raises(Crash):
        await importer.import_directory(proxy, env["out"], symbol=SYMBOL, gate_path=str(env["out"]),
                                        schema=env["dst"], usage=base.ROOMY)
    assert await ids_in(env, env["dst"]) == []
    assert await env["c2"].fetchval(f"SELECT count(*) FROM {env['dst']}.batches") == 0
    result = await run_import(env)
    assert result["summary"] == {"ACCEPTED": 1}
    assert await ids_in(env, env["dst"]) == list(range(1, 301))


class _Proxy:
    def __init__(self, real, execute):
        self._real, self.execute = real, execute

    def __getattr__(self, name):
        return getattr(self._real, name)


@pytest.mark.asyncio
async def test_layout_is_never_converted_silently(env):
    with pytest.raises(ArchiveSyncError, match="no conversion"):
        await importer.ensure_schema(env["c2"], env["dst"], "v1")
    assert await importer.ensure_schema(env["c2"], env["dst"]) == "v2"
    with pytest.raises(ArchiveSyncError):
        importer._schema_ddl("archive_x", "v3")


@pytest.mark.asyncio
async def test_v2_backup_and_restore_reproduce_rows_and_provenance(env, tmp_path):
    pg_bin = os.environ.get("TIM_ARCHIVE_TEST_PG_BIN", "")
    pg_dump = shutil.which("pg_dump", path=pg_bin or None)
    pg_restore = shutil.which("pg_restore", path=pg_bin or None)
    if not pg_dump or not pg_restore:
        pytest.skip("pg_dump/pg_restore not installed here")
    # A backup is restored with the tools of the server's own major version. A newer pg_restore
    # emits settings an older server rejects (e.g. transaction_timeout on PG16), which says nothing
    # about the archive layout.
    tool_major = int(re.search(r"(\d+)", subprocess.run(
        [pg_restore, "--version"], capture_output=True, text=True, check=True).stdout.split()[-1]).group(1))
    server_major = int(await env["c2"].fetchval("SELECT current_setting('server_version_num')::int")) // 10000
    if tool_major != server_major:
        pytest.skip(f"pg_restore {tool_major} does not match server major version {server_major}")
    await add_trades(env, range(1, 501))
    await set_cursor(env, 500)
    await export(env)
    await run_import(env)
    schema = env["dst"]
    before = await health.range_digest(env["c2"], table=f"{schema}.agg_trades", symbol=SYMBOL, lo=1, hi=500)
    batches_before = [dict(r) for r in await env["c2"].fetch(
        f"SELECT batch_no, batch_id, content_sha256, file_sha256 FROM {schema}.batches ORDER BY batch_no")]
    dump = tmp_path / "v2.dump"
    done = subprocess.run([pg_dump, "-Fc", "-n", schema, "-f", str(dump), base.DATABASE_URL], capture_output=True, text=True)
    if done.returncode != 0:
        pytest.skip(f"pg_dump not usable against this server: {done.stderr.strip()[:120]}")
    restored = f"{schema}_r"
    await env["c2"].execute(f"ALTER SCHEMA {schema} RENAME TO {restored}")
    try:
        subprocess.run([pg_restore, "--no-owner", "-d", base.DATABASE_URL, str(dump)], check=True, capture_output=True)
        after = await health.range_digest(env["c2"], table=f"{schema}.agg_trades", symbol=SYMBOL, lo=1, hi=500)
        batches_after = [dict(r) for r in await env["c2"].fetch(
            f"SELECT batch_no, batch_id, content_sha256, file_sha256 FROM {schema}.batches ORDER BY batch_no")]
        assert after == before and batches_after == batches_before
        check = await health.archive_health(env["c2"], symbol=SYMBOL, schema=schema, verify_last=10)
        assert check["status"] == "OK" and all(v["ok"] for v in check["verified_batches"])
        # New batches after a restore continue the numbering instead of colliding.
        await add_trades(env, range(501, 601))
        await set_cursor(env, 600)
        await export(env)
        assert (await run_import(env))["summary"].get("ACCEPTED") == 1
        nos = [r[0] for r in await env["c2"].fetch(f"SELECT batch_no FROM {schema}.batches ORDER BY 1")]
        assert len(nos) == len(set(nos)) == len(batches_before) + 1
    finally:
        await env["c2"].execute(f"DROP SCHEMA IF EXISTS {restored} CASCADE")
