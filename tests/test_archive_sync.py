"""PostgreSQL integration tests for the archive sync S1 (needs TIM_DURABLE_TEST_DATABASE_URL).

Every test builds its own source schema (stands in for the Mac's public schema) and its own
archive schema, and drops both afterwards. Nothing touches public tables.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from src.archive_sync import exporter, health, importer, transfer
from src.archive_sync.common import ArchiveSyncError, batch_id_for, checked_schema, sha256_file

DATABASE_URL = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
SYMBOL = "BTCUSDT"
BASE = datetime(2026, 11, 20, tzinfo=timezone.utc)
Usage = namedtuple("Usage", "total used free")
ROOMY = lambda _path: Usage(1000 * 2**30, 100 * 2**30, 900 * 2**30)  # noqa: E731
FULL = lambda _path: Usage(1000 * 2**30, 900 * 2**30, 100 * 2**30)  # noqa: E731



@pytest_asyncio.fixture
async def env(tmp_path):
    if not DATABASE_URL:
        pytest.skip("isolated PostgreSQL test URL not provided")
    import asyncpg

    connection = await asyncpg.connect(DATABASE_URL)
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
    second = await asyncpg.connect(DATABASE_URL)
    holder = {"c": connection, "c2": second, "src": src, "dst": dst, "out": tmp_path / "out", "inbox": tmp_path / "inbox"}
    yield holder
    await connection.execute(f"DROP SCHEMA IF EXISTS {src} CASCADE")
    await connection.execute(f"DROP SCHEMA IF EXISTS {dst} CASCADE")
    await second.close()
    await connection.close()


async def add_trades(env, ids, *, price_shift=0.0):
    rows = [
        (
            SYMBOL,
            i,
            BASE + timedelta(milliseconds=37 * i),
            67000.1 + i * 0.01 + price_shift,
            0.000123 * (1 + i % 7),
            i % 3 == 0,
            BASE + timedelta(milliseconds=37 * i, microseconds=123457),
        )
        for i in ids
    ]
    await env["c"].copy_records_to_table(
        "agg_trades",
        schema_name=env["src"],
        records=rows,
        columns=["symbol", "aggregate_trade_id", "trade_time", "price", "quantity", "buyer_is_maker", "ingest_timestamp"],
    )


async def set_cursor(env, value):
    await env["c"].execute(f"DELETE FROM {env['src']}.ingestion_cursors")
    await env["c"].execute(
        f"INSERT INTO {env['src']}.ingestion_cursors VALUES ('BINANCE','SPOT',$1,'AGG_TRADE',$2)", SYMBOL, value
    )


async def state(env):
    await importer.ensure_schema(env["c2"], env["dst"])
    return await importer.server_state(env["c2"], SYMBOL, env["dst"])


async def export(env, *, chunk=300, max_batches=10, usage=ROOMY):
    return await exporter.export_batches(
        env["c"],
        symbol=SYMBOL,
        out_dir=env["out"],
        server_state=await state(env),
        source_schema=env["src"],
        chunk=chunk,
        max_batches=max_batches,
        usage=usage,
    )


async def run_import(env, directory=None, usage=ROOMY):
    return await importer.import_directory(
        env["c2"], directory or env["out"], symbol=SYMBOL, gate_path=str(env["out"]), schema=env["dst"], usage=usage
    )


async def ids_in(env, schema):
    rows = await env["c"].fetch(
        f"SELECT aggregate_trade_id FROM {schema}.agg_trades WHERE symbol=$1 ORDER BY 1", SYMBOL
    )
    return [int(r[0]) for r in rows]


def rewrite_batch(manifest_path: Path, mutate_csv, *, consistent=True):
    """Play a faulty exporter: change the CSV, optionally recompute every hash so it looks valid."""
    manifest = json.loads(manifest_path.read_text())
    data_path = manifest_path.with_name(manifest["file"])
    csv = mutate_csv(gzip.decompress(data_path.read_bytes()))
    data_path.write_bytes(gzip.compress(csv, mtime=0))
    manifest["file_bytes"] = data_path.stat().st_size
    manifest["file_sha256"] = sha256_file(data_path)
    if consistent:
        manifest["content_sha256"] = hashlib.sha256(csv).hexdigest()
        manifest["row_count"] = csv.count(b"\n")
        manifest["csv_bytes"] = len(csv)
        manifest["batch_id"] = batch_id_for(
            manifest["kind"], manifest["symbol"], manifest["lo"], manifest["hi"], manifest["content_sha256"], manifest["holes"]
        )
    manifest_path.write_text(json.dumps(manifest))
    return manifest


def manifests(env):
    return sorted(env["out"].glob("*.manifest.json"))


# --- happy path, completeness, idempotence --------------------------------------------------


@pytest.mark.asyncio
async def test_export_import_reproduces_exact_trade_set_up_to_the_cursor(env):
    present = [i for i in range(1, 1001) if i not in (50, 51, 52, 400, 899)]
    await add_trades(env, present)
    await set_cursor(env, 900)
    report = await export(env)
    assert [(b["kind"], b["lo"], b["hi"]) for b in report["batches"]] == [
        ("new", 1, 300),
        ("new", 301, 600),
        ("new", 601, 900),
    ]
    result = await run_import(env)
    assert result["summary"] == {"ACCEPTED": 3}
    assert result["state"]["watermark"] == 900
    assert result["state"]["holes"] == [[50, 52], [400, 400], [899, 899]]
    assert await ids_in(env, env["dst"]) == [i for i in present if i <= 900]
    for lo, hi in ((1, 300), (301, 600), (601, 900)):
        mac = await health.range_digest(env["c"], table=f"{env['src']}.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
        server = await health.range_digest(env["c2"], table=f"{env['dst']}.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
        assert mac["sha256"] == server["sha256"] and mac["rows"] == server["rows"]
    # Odd session output settings on the server must not change the canonical hash.
    await env["c2"].execute("SET datestyle = 'German'; SET extra_float_digits = 0; SET TIME ZONE 'Europe/Berlin'")
    check = await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"], verify_last=5)
    assert check["status"] == "WARN" and check["open_hole_ids"] == 5 and not check["problems"]
    assert all(item["ok"] for item in check["verified_batches"])


@pytest.mark.asyncio
async def test_trades_after_the_cursor_are_not_exported_yet(env):
    await add_trades(env, range(1, 201))
    await set_cursor(env, 150)
    await export(env, chunk=1000)
    await run_import(env)
    assert max(await ids_in(env, env["dst"])) == 150
    await set_cursor(env, 200)
    report = await export(env, chunk=1000)
    assert [(b["lo"], b["hi"]) for b in report["batches"]] == [(151, 200)]
    await run_import(env)
    assert await ids_in(env, env["dst"]) == list(range(1, 201))


@pytest.mark.asyncio
async def test_reimport_and_reexport_are_idempotent(env):
    await add_trades(env, range(1, 101))
    await set_cursor(env, 100)
    first = await export(env, chunk=1000)
    assert (await run_import(env))["summary"] == {"ACCEPTED": 1}
    assert (await run_import(env))["summary"] == {"ALREADY_ACCEPTED": 1}
    again = await exporter.export_batches(
        env["c"], symbol=SYMBOL, out_dir=env["out"], server_state={"symbol": SYMBOL, "watermark": None, "holes": []},
        source_schema=env["src"], chunk=1000, usage=ROOMY,
    )
    assert again["batches"][0]["batch_id"] == first["batches"][0]["batch_id"]
    assert await ids_in(env, env["dst"]) == list(range(1, 101))


# --- late trades below the watermark --------------------------------------------------------


@pytest.mark.asyncio
async def test_late_backfilled_trade_below_watermark_is_not_lost(env):
    await add_trades(env, [i for i in range(1, 301) if i not in range(100, 111)])
    await set_cursor(env, 300)
    await export(env)
    await run_import(env)
    assert (await state(env))["holes"] == [[100, 110]]
    # History recovery fills part of the gap on the Mac, below the archive watermark.
    await add_trades(env, range(100, 105))
    report = await export(env)
    assert [(b["kind"], b["lo"], b["hi"]) for b in report["batches"]] == [("backfill", 100, 110)]
    result = await run_import(env)
    assert result["summary"] == {"ACCEPTED": 1, "ALREADY_ACCEPTED": 1}
    assert result["state"]["holes"] == [[105, 110]]
    await add_trades(env, range(105, 111))
    await export(env)
    final = await run_import(env)
    assert final["state"]["holes"] == []
    assert await ids_in(env, env["dst"]) == list(range(1, 301))
    check = await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"], verify_last=10)
    assert check["status"] == "OK", check


@pytest.mark.asyncio
async def test_older_history_appearing_before_the_start_is_archived_as_prefix(env):
    await add_trades(env, range(500, 701))
    await set_cursor(env, 700)
    await export(env)
    await run_import(env)
    await add_trades(env, range(100, 500))
    report = await export(env, chunk=250)
    assert [(b["kind"], b["lo"], b["hi"]) for b in report["batches"]] == [("prefix", 250, 499), ("prefix", 100, 249)]
    result = await run_import(env)
    assert result["state"]["start_id"] == 100
    assert await ids_in(env, env["dst"]) == list(range(100, 701))
    assert (await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"]))["status"] == "OK"


@pytest.mark.asyncio
async def test_starting_with_a_later_batch_still_archives_the_earlier_range(env):
    await add_trades(env, range(1, 601))
    await set_cursor(env, 600)
    await export(env)
    first, second = manifests(env)
    await importer.ensure_schema(env["c2"], env["dst"])
    kwargs = dict(symbol=SYMBOL, gate_path=env["out"], schema=env["dst"], usage=ROOMY)
    assert (await importer.import_batch(env["c2"], second, **kwargs))["result"] == "ACCEPTED"
    # The earlier 'new' batch no longer connects; its rows come back as a prefix, not lost.
    assert (await importer.import_batch(env["c2"], first, **kwargs))["result"] == "STALE"
    assert await ids_in(env, env["dst"]) == list(range(301, 601))
    report = await export(env)
    assert [(b["kind"], b["lo"], b["hi"]) for b in report["batches"]] == [("prefix", 1, 300)]
    await run_import(env)
    assert await ids_in(env, env["dst"]) == list(range(1, 601))


@pytest.mark.asyncio
async def test_gap_between_batches_is_refused_until_the_missing_batch_arrives(env):
    await add_trades(env, range(1, 901))
    await set_cursor(env, 900)
    await export(env)
    one, two, three = manifests(env)
    inbox = env["inbox"]
    inbox.mkdir()
    for path in (one, three):
        for name in (path.name, json.loads(path.read_text())["file"]):
            (inbox / name).write_bytes((env["out"] / name).read_bytes())
    result = await run_import(env, inbox)
    assert [r["result"] for r in result["results"]] == ["ACCEPTED", "OUT_OF_ORDER"]
    assert result["state"]["watermark"] == 300
    for name in (two.name, json.loads(two.read_text())["file"]):
        (inbox / name).write_bytes((env["out"] / name).read_bytes())
    result = await run_import(env, inbox)
    assert result["state"]["watermark"] == 900


# --- hash conflicts and faulty batches: nothing of the batch is released --------------------


@pytest.mark.asyncio
async def test_corrupted_transfer_is_rejected_without_touching_the_archive(env):
    await add_trades(env, range(1, 301))
    await set_cursor(env, 300)
    await export(env)
    (path,) = manifests(env)
    data = env["out"] / json.loads(path.read_text())["file"]
    data.write_bytes(data.read_bytes()[:-5])
    result = await run_import(env)
    assert result["results"][0]["result"] == "FILE_INVALID"
    assert await ids_in(env, env["dst"]) == []
    assert result["state"]["watermark"] is None


@pytest.mark.asyncio
async def test_content_hash_conflict_quarantines_whole_batch_and_halts_the_chain(env):
    await add_trades(env, range(1, 601))
    await set_cursor(env, 600)
    await export(env)
    first = manifests(env)[0]
    rewrite_batch(first, lambda csv: csv.replace(b"67000.11,", b"67000.99,", 1), consistent=False)
    result = await run_import(env)
    assert [r["result"] for r in result["results"]] == ["QUARANTINED", "NOT_TRIED"]
    assert "content sha256" in result["results"][0]["reason"]
    assert await ids_in(env, env["dst"]) == []
    check = await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"])
    assert check["status"] == "FAIL" and any("quarantined" in p for p in check["problems"])


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda csv: b"".join((lambda l: l[:2] + [l[1]] + l[3:])(csv.splitlines(keepends=True))), "duplicate"),
        (lambda csv: b"".join(csv.splitlines(keepends=True)[1:]), "row count"),
        (lambda csv: csv.replace(b"BTCUSDT,", b"ETHUSDT,", 1), "another symbol"),
        (lambda csv: csv.replace(b"BINANCE_SPOT_AGGTRADE", b"OTHER", 1), "source"),
    ],
)
@pytest.mark.asyncio
async def test_consistently_hashed_but_wrong_batch_is_quarantined(env, mutate, reason):
    await add_trades(env, range(1, 101))
    await set_cursor(env, 100)
    await export(env, chunk=1000)
    (path,) = manifests(env)
    rewrite_batch(path, mutate)
    result = await run_import(env)
    assert result["results"][0]["result"] == "QUARANTINED"
    assert reason in result["results"][0]["reason"]
    assert await ids_in(env, env["dst"]) == []
    count = await env["c2"].fetchval(f"SELECT count(*) FROM {env['dst']}.batches WHERE status='ACCEPTED'")
    assert count == 0


@pytest.mark.asyncio
async def test_row_inside_a_declared_hole_is_quarantined(env):
    await add_trades(env, [i for i in range(1, 101) if i != 40])
    await set_cursor(env, 100)
    await export(env, chunk=1000)
    (path,) = manifests(env)
    manifest = json.loads(path.read_text())
    assert manifest["holes"] == [[40, 40]]

    def swap(csv):
        lines = csv.splitlines(keepends=True)
        return b"".join(line.replace(b",41,", b",40,", 1) if b",41," in line else line for line in lines)

    result_manifest = rewrite_batch(path, swap)
    assert result_manifest["row_count"] == 99
    result = await run_import(env)
    assert result["results"][0]["result"] == "QUARANTINED"


@pytest.mark.asyncio
async def test_payload_conflict_with_archived_rows_is_quarantined_and_archive_unchanged(env):
    await add_trades(env, range(1, 201))
    await set_cursor(env, 200)
    await export(env, chunk=1000)
    await run_import(env)
    before = await health.range_digest(env["c2"], table=f"{env['dst']}.agg_trades", symbol=SYMBOL, lo=1, hi=200)
    # The Mac's copy changes after archiving (it must not): a re-export of the range differs.
    await env["c"].execute(f"UPDATE {env['src']}.agg_trades SET price=price+1 WHERE aggregate_trade_id=7")
    await exporter.export_batches(
        env["c"], symbol=SYMBOL, out_dir=env["inbox"], server_state={"symbol": SYMBOL, "watermark": None, "holes": []},
        source_schema=env["src"], chunk=1000, usage=ROOMY,
    )
    result = await run_import(env, env["inbox"])
    assert result["results"][0]["result"] == "QUARANTINED"
    assert "differ from rows already in the archive" in result["results"][0]["reason"]
    after = await health.range_digest(env["c2"], table=f"{env['dst']}.agg_trades", symbol=SYMBOL, lo=1, hi=200)
    assert before == after


@pytest.mark.asyncio
async def test_health_detects_archived_rows_changed_after_import(env):
    await add_trades(env, range(1, 101))
    await set_cursor(env, 100)
    await export(env, chunk=1000)
    await run_import(env)
    await env["c2"].execute(f"UPDATE {env['dst']}.agg_trades SET quantity=quantity*2 WHERE aggregate_trade_id=5")
    check = await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"])
    assert check["status"] == "FAIL" and any("no longer match" in p for p in check["problems"])


@pytest.mark.asyncio
async def test_health_fails_when_archive_is_stale_or_missing(env):
    assert (await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"]))["status"] == "FAIL"
    await add_trades(env, range(1, 11))
    await set_cursor(env, 10)
    await export(env)
    await run_import(env)
    later = datetime.now(timezone.utc) + timedelta(hours=31)
    check = await health.archive_health(env["c2"], symbol=SYMBOL, schema=env["dst"], now=later, source_cursor_id=25)
    assert check["status"] == "FAIL" and check["source_lag_ids"] == 15


# --- snapshot, gates, guards -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_is_one_read_only_snapshot(env):
    await add_trades(env, range(1, 101))
    await set_cursor(env, 100)
    real = env["c"]

    class Interleaved:
        """Delegates to the real connection; a second session writes before the first COPY."""

        calls = 0

        def __getattr__(self, name):
            return getattr(real, name)

        async def copy_from_query(self, *args, **kwargs):
            if Interleaved.calls == 0:
                await add_trades_other(env, range(101, 151))
                await env["c2"].execute(f"UPDATE {env['src']}.ingestion_cursors SET last_aggregate_trade_id=150")
                assert await real.fetchval("SHOW transaction_read_only") == "on"
                assert await real.fetchval("SHOW transaction_isolation") == "repeatable read"
            Interleaved.calls += 1
            return await real.copy_from_query(*args, **kwargs)

    report = await exporter.export_batches(
        Interleaved(), symbol=SYMBOL, out_dir=env["out"], server_state=await state(env),
        source_schema=env["src"], chunk=60, usage=ROOMY,
    )
    # Bound and rows come from the snapshot taken before the concurrent write.
    assert report["source_cursor_id"] == 100
    assert [(b["lo"], b["hi"], b["row_count"]) for b in report["batches"]] == [(1, 60, 60), (61, 100, 40)]


async def add_trades_other(env, ids):
    rows = [(SYMBOL, i, BASE, 1.0, 1.0, False) for i in ids]
    await env["c2"].copy_records_to_table(
        "agg_trades", schema_name=env["src"], records=rows,
        columns=["symbol", "aggregate_trade_id", "trade_time", "price", "quantity", "buyer_is_maker"],
    )


@pytest.mark.asyncio
async def test_disk_gates_stop_export_and_import_before_writing(env):
    await add_trades(env, range(1, 101))
    await set_cursor(env, 100)
    with pytest.raises(ArchiveSyncError, match="disk gate"):
        await export(env, usage=FULL)
    assert manifests(env) == []
    await export(env)
    with pytest.raises(ArchiveSyncError, match="disk gate"):
        await run_import(env, usage=FULL)
    assert await ids_in(env, env["dst"]) == []


@pytest.mark.asyncio
async def test_importer_refuses_public_schema_and_bad_names():
    with pytest.raises(ArchiveSyncError):
        checked_schema("public")
    with pytest.raises(ArchiveSyncError):
        checked_schema("archive; drop table x")
    assert checked_schema("archive_mac") == "archive_mac"


@pytest.mark.asyncio
async def test_export_needs_a_durable_cursor(env):
    await add_trades(env, range(1, 11))
    with pytest.raises(ArchiveSyncError, match="cursor"):
        await export(env)


# --- transfer --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transfer_resumes_after_a_dropped_connection_and_import_sees_only_complete_batches(env):
    await add_trades(env, range(1, 901))
    await set_cursor(env, 900)
    await export(env)

    class Flaky(transfer.LocalDirTarget):
        failures = 0

        def upload(self, local, name):
            if name.endswith(".manifest.json") and "-00000000000000000301-" in name and Flaky.failures < 1:
                Flaky.failures += 1
                (self.root / (name + ".part")).write_text("{half")
                raise ArchiveSyncError("connection dropped")
            super().upload(local, name)

    target = Flaky(env["inbox"])
    with pytest.raises(ArchiveSyncError):
        transfer.transfer_directory(env["out"], target, symbol=SYMBOL, attempts=1, sleep=lambda _s: None)
    partial = await run_import(env, env["inbox"])
    assert partial["state"]["watermark"] == 300  # half-sent batch is invisible, nothing broken
    report = transfer.transfer_directory(env["out"], target, symbol=SYMBOL, sleep=lambda _s: None)
    assert report["skipped_already_present"] == 3
    final = await run_import(env, env["inbox"])
    assert final["state"]["watermark"] == 900


def test_ssh_target_verifies_remote_hash_before_rename(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    local = tmp_path / "BTCUSDT-new-1.csv.gz"
    local.write_bytes(b"abc")
    calls = []

    def runner(argv):
        import subprocess

        calls.append(list(argv))
        if argv[0] == "scp":
            dest = argv[-1].split(":", 1)[1]
            Path(dest).write_bytes(Path(argv[-2]).read_bytes())
            return subprocess.CompletedProcess(argv, 0, "", "")
        done = subprocess.run(["bash", "-c", argv[-1]], capture_output=True, text=True)
        return done

    target = transfer.SshTarget(host="archive-host", remote_dir=str(remote), key="/k", port=2222, runner=runner)
    target.upload(local, local.name)
    assert (remote / local.name).read_bytes() == b"abc"
    assert not (remote / (local.name + ".part")).exists()
    assert target.sha256(local.name) == sha256_file(local)
    assert ["-o", "BatchMode=yes"] == calls[0][1:3] and "-p" in calls[0] and "-P" in calls[1]

    def corrupting(argv):
        result = runner(argv)
        if argv[0] == "scp":
            Path(argv[-1].split(":", 1)[1]).write_bytes(b"abX")
        return result

    bad = transfer.SshTarget(host="archive-host", remote_dir=str(remote), runner=corrupting)
    other = tmp_path / "BTCUSDT-new-2.csv.gz"
    other.write_bytes(b"abc")
    with pytest.raises(ArchiveSyncError, match="sha256"):
        bad.upload(other, other.name)
    assert not (remote / other.name).exists() and not (remote / (other.name + ".part")).exists()


def test_transfer_refuses_when_receiver_is_short_of_space(tmp_path):
    (tmp_path / "BTCUSDT-new-x.csv.gz").write_bytes(b"1")
    (tmp_path / "BTCUSDT-new-x.manifest.json").write_text("{}")

    class Tight(transfer.LocalDirTarget):
        def disk(self):
            return 100, 10

    with pytest.raises(ArchiveSyncError, match="free-space"):
        transfer.transfer_directory(tmp_path, Tight(tmp_path / "dst"), symbol=SYMBOL)
    assert not (tmp_path / "dst" / "BTCUSDT-new-x.csv.gz").exists()


def test_unsafe_names_and_remote_dirs_are_refused(tmp_path):
    with pytest.raises(ArchiveSyncError):
        transfer.SshTarget(host="h", remote_dir="../etc")
    with pytest.raises(ArchiveSyncError):
        transfer.SshTarget(host="h", remote_dir="a; rm -rf /")
    with pytest.raises(ArchiveSyncError):
        transfer.LocalDirTarget(tmp_path).sha256("../x")


def test_cli_never_falls_back_to_the_runtime_database(monkeypatch, capsys):
    from src.archive_sync.__main__ import main

    monkeypatch.delenv("TIM_ARCHIVE_TARGET_URL", raising=False)
    assert main(["state", "--symbol", SYMBOL]) == 2
    assert "TIM_ARCHIVE_TARGET_URL is not set" in capsys.readouterr().out


# --- review follow-ups -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_backfill_in_the_middle_of_a_hole_leaves_both_remainders_open(env):
    await add_trades(env, [i for i in range(1, 201) if not 100 <= i <= 110])
    await set_cursor(env, 200)
    await export(env, chunk=1000)
    await run_import(env)
    await add_trades(env, range(104, 107))
    await export(env, chunk=1000)
    result = await run_import(env)
    assert result["state"]["holes"] == [[100, 103], [107, 110]]
    assert [i for i in await ids_in(env, env["dst"]) if 99 <= i <= 111] == [99, 104, 105, 106, 111]


@pytest.mark.asyncio
async def test_non_canonical_number_text_is_quarantined_even_with_matching_hashes(env):
    await add_trades(env, range(1, 21))
    await set_cursor(env, 20)
    await export(env, chunk=1000)
    (path,) = manifests(env)
    rewrite_batch(path, lambda csv: csv.replace(b"67000.11,", b"6.700011e4,", 1))
    result = await run_import(env)
    assert result["results"][0]["result"] == "QUARANTINED"
    assert "re-read" in result["results"][0]["reason"]
    assert await ids_in(env, env["dst"]) == []


@pytest.mark.asyncio
async def test_unreadable_manifest_is_reported_and_halts_without_crashing(env):
    await add_trades(env, range(1, 601))
    await set_cursor(env, 600)
    await export(env)
    first, second = manifests(env)
    second.write_text("{not json")
    (env["out"] / f"{SYMBOL}-new-x.manifest.json").write_text('{"format": "tim-archive-batch/1"}')
    result = await run_import(env)
    kinds = sorted(r["result"] for r in result["results"])
    assert kinds == ["FILE_INVALID", "FILE_INVALID", "NOT_TRIED"]
    assert result["state"]["watermark"] is None


@pytest.mark.asyncio
async def test_bad_hole_list_is_file_invalid_not_a_crash(env):
    await add_trades(env, range(1, 21))
    await set_cursor(env, 20)
    await export(env, chunk=1000)
    (path,) = manifests(env)
    manifest = json.loads(path.read_text())
    manifest["holes"] = [[30, 40]]
    path.write_text(json.dumps(manifest))
    result = await run_import(env)
    assert result["results"][0]["result"] == "FILE_INVALID"
    assert "hole" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_source_cursor_behind_the_archive_stops_the_export(env):
    await add_trades(env, range(1, 101))
    await set_cursor(env, 100)
    await export(env, chunk=1000)
    await run_import(env)
    await set_cursor(env, 80)
    with pytest.raises(ArchiveSyncError, match="behind the archive"):
        await export(env, chunk=1000)


@pytest.mark.asyncio
async def test_changed_chunk_size_between_runs_loses_nothing(env):
    await add_trades(env, range(1, 1001))
    await set_cursor(env, 1000)
    await export(env, chunk=300)
    for path in manifests(env)[1:]:
        path.unlink()
    await run_import(env)
    await export(env, chunk=170)
    await run_import(env)
    await export(env, chunk=170)
    result = await run_import(env)
    assert result["state"]["watermark"] == 1000
    assert await ids_in(env, env["dst"]) == list(range(1, 1001))


@pytest.mark.asyncio
async def test_source_session_settings_do_not_change_the_batch_hash(env):
    await add_trades(env, range(1, 51))
    await set_cursor(env, 50)
    plain = await export(env, chunk=1000)
    await env["c"].execute("SET datestyle = 'SQL, DMY'; SET extra_float_digits = 0; SET TIME ZONE 'America/New_York'")
    odd = await exporter.export_batches(
        env["c"], symbol=SYMBOL, out_dir=env["inbox"], server_state=await state(env),
        source_schema=env["src"], chunk=1000, usage=ROOMY,
    )
    assert odd["batches"][0]["batch_id"] == plain["batches"][0]["batch_id"]


def test_ssh_host_and_key_cannot_inject_options():
    for host in ("-oProxyCommand=touch x", "a b", "h;id", ""):
        with pytest.raises(ArchiveSyncError):
            transfer.SshTarget(host=host, remote_dir="tim-archive")
    with pytest.raises(ArchiveSyncError):
        transfer.SshTarget(host="h", remote_dir="tim-archive", key="-oProxyCommand=x")
    calls = []
    target = transfer.SshTarget(
        host="user@archive-host", remote_dir="tim-archive",
        runner=lambda argv: calls.append(list(argv)) or __import__("subprocess").CompletedProcess(argv, 0, "", ""),
    )
    target.sha256("BTCUSDT-new-1.csv.gz")
    assert calls[0][calls[0].index("--") + 1] == "user@archive-host"


@pytest.mark.asyncio
async def test_id_window_exports_only_that_range_and_never_older_data(env):
    await add_trades(env, [i for i in range(1, 501) if i != 210])
    await set_cursor(env, 500)
    report = await exporter.export_batches(
        env["c"], symbol=SYMBOL, out_dir=env["out"], server_state={"symbol": SYMBOL, "watermark": None, "holes": []},
        source_schema=env["src"], chunk=60, usage=ROOMY, id_window=(200, 320),
    )
    assert [(b["kind"], b["lo"], b["hi"]) for b in report["batches"]] == [("new", 200, 259), ("new", 260, 319), ("new", 320, 320)]
    result = await run_import(env)
    assert result["state"] == {**result["state"], "start_id": 200, "watermark": 320, "holes": [[210, 210]]}
