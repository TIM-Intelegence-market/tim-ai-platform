"""INFRA-09 cold-state round trip with PostgreSQL (needs TIM_DURABLE_TEST_DATABASE_URL).

Mac first: the exporter takes its state from the cold store (``cold-state``) instead of the
server database. Later migration: the very same stored files, imported into the server's
archive schema, must give the same state and exactly the Mac's trade set.
"""
from __future__ import annotations

import gzip
import json

import pytest

from src.archive_sync import cold_state, cold_store, exporter, importer
from tests.test_archive_sync import ROOMY, SYMBOL, add_trades, env, ids_in, set_cursor  # noqa: F401

pytestmark = pytest.mark.asyncio


def core(state):
    return {k: state[k] for k in ("start_id", "watermark", "holes")}


async def export_from_cold(env, store, out, chunk=150):
    state = cold_state.cold_state(store, SYMBOL)
    return await exporter.export_batches(env["c"], symbol=SYMBOL, out_dir=out, server_state=state,
                                         source_schema=env["src"], chunk=chunk, max_batches=50, usage=ROOMY)


def stored_ids(store):
    ids = []
    for manifest in sorted((store.root / "batches" / SYMBOL).glob("*.manifest.json")):
        data = manifest.with_name(json.loads(manifest.read_text())["file"])
        ids += [int(line.split(b",")[1]) for line in gzip.decompress(data.read_bytes()).splitlines()]
    return sorted(ids)


async def test_mac_first_round_trip_and_later_server_import_agree(env, tmp_path):
    store = cold_store.ColdStore.init(tmp_path / "store", limit_bytes=10**9, usage=ROOMY)
    # Round 1: the Mac holds 201..600 with a gap at 300..310.
    await add_trades(env, [i for i in range(201, 601) if not 300 <= i <= 310])
    await set_cursor(env, 600)
    first = await export_from_cold(env, store, tmp_path / "out1")
    assert {b["kind"] for b in first["batches"]} == {"new"}
    assert store.ingest_directory(tmp_path / "out1", symbol=SYMBOL)["halted"] is None
    assert core(cold_state.cold_state(store, SYMBOL)) == {"start_id": 201, "watermark": 600, "holes": [[300, 310]]}

    # Round 2: history recovery fills part of the gap, older history appears, new trades arrive.
    await add_trades(env, list(range(300, 305)) + list(range(101, 201)) + list(range(601, 801)))
    await set_cursor(env, 800)
    second = await export_from_cold(env, store, tmp_path / "out2")
    assert [b["kind"] for b in second["batches"]][:1] == ["backfill"]
    assert {"new", "prefix"} <= {b["kind"] for b in second["batches"]}
    assert store.ingest_directory(tmp_path / "out2", symbol=SYMBOL)["halted"] is None
    final = cold_state.cold_state(store, SYMBOL, deep=True)
    assert core(final) == {"start_id": 101, "watermark": 800, "holes": [[305, 310]]}
    mac = await ids_in(env, env["src"])
    assert stored_ids(store) == mac and final["archived_trades"] == len(mac)

    # Resume: nothing new on the Mac -> no batch; re-ingesting old exports changes nothing.
    third = await export_from_cold(env, store, tmp_path / "out3")
    assert third["batches"] == [] and third["backfill_ranges_still_empty"] == 1
    for folder in ("out1", "out2"):
        assert set(store.ingest_directory(tmp_path / folder, symbol=SYMBOL)["summary"]) == {"ALREADY"}
    assert core(cold_state.cold_state(store, SYMBOL)) == core(final)

    # Later Linux migration: copy the store to new disks, then import its files into the server.
    assert cold_store.migrate_store(store.root, tmp_path / "new-disks")["status"] == "OK"
    moved = cold_store.ColdStore(tmp_path / "new-disks")
    assert core(cold_state.cold_state(moved, SYMBOL)) == core(final)
    folder = moved.root / "batches" / SYMBOL
    for _ in range(5):  # repeated runs, as the importer defers batches that do not connect yet
        result = await importer.import_directory(env["c2"], folder, symbol=SYMBOL, gate_path=str(tmp_path),
                                                 schema=env["dst"], usage=ROOMY)
        assert not {"QUARANTINED", "FILE_INVALID"} & set(result["summary"]), result["summary"]
        if "ACCEPTED" not in result["summary"]:
            break
    assert core(result["state"]) == core(final)
    assert await ids_in(env, env["dst"]) == mac
    assert cold_store.ColdStore(tmp_path / "new-disks").verify()["status"] == "OK"  # importer left the files alone
