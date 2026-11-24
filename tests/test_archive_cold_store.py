"""INFRA-09 draft: cold file store with a hard byte budget. Pure file tests, no database."""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import namedtuple
from pathlib import Path

import pytest

from src.archive_sync import cold_store
from src.archive_sync.common import COLUMNS, FORMAT, ArchiveSyncError, batch_id_for, sha256_file

SYMBOL = "BTCUSDT"
Usage = namedtuple("Usage", "total used free")
ROOMY = lambda _path: Usage(10**12, 0, 10**12)  # noqa: E731


def make_batch(folder: Path, lo: int, hi: int, *, holes=(), price: str = "61339.05", tamper=None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    hole_ids = {i for a, b in holes for i in range(a, b + 1)}
    rows = [
        f"{SYMBOL},{i},2026-11-22 23:55:05.282+00,{price},0.00027,f,BINANCE_SPOT_AGGTRADE,2026-11-22 23:55:05.5105+00\n"
        for i in range(lo, hi + 1) if i not in hole_ids
    ]
    csv = "".join(rows).encode()
    if tamper == "content":
        csv = csv.replace(b"0.00027", b"0.00028", 1)
    content = hashlib.sha256(csv if tamper != "content" else "".join(rows).encode()).hexdigest()
    name = f"{SYMBOL}-new-{lo:020d}-{hi:020d}"
    data = folder / f"{name}.csv.gz"
    data.write_bytes(gzip.compress(csv, mtime=0))
    manifest = {
        "format": FORMAT, "kind": "new", "symbol": SYMBOL, "lo": lo, "hi": hi, "holes": [list(h) for h in holes],
        "row_count": len(rows), "content_sha256": content, "csv_bytes": len(csv), "file": data.name,
        "file_bytes": data.stat().st_size, "file_sha256": sha256_file(data), "columns": list(COLUMNS),
        "batch_id": batch_id_for("new", SYMBOL, lo, hi, content, [list(h) for h in holes]),
    }
    if tamper == "file":
        data.write_bytes(gzip.compress(csv + b"x", mtime=0))
    path = folder / f"{name}.manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def store(tmp_path: Path, limit: int = 10**9) -> cold_store.ColdStore:
    return cold_store.ColdStore.init(tmp_path / "store", limit_bytes=limit, usage=ROOMY)


def test_stores_original_files_bit_identical_with_a_ledger(tmp_path):
    inbox = tmp_path / "in"
    m1 = make_batch(inbox, 1, 100)
    make_batch(inbox, 101, 200, holes=[(150, 152)])
    s = store(tmp_path)
    report = s.ingest_directory(inbox, symbol=SYMBOL)
    assert report["summary"] == {"STORED": 2} and report["halted"] is None
    stored = s.root / "batches" / SYMBOL / m1.name
    assert stored.read_bytes() == m1.read_bytes()
    entries = s.ledger()
    assert len(entries) == 4 and [e["role"] for e in entries] == ["data", "manifest", "data", "manifest"]
    assert all(sha256_file(s.root / e["path"]) == e["sha256"] for e in entries)
    assert s.verify()["status"] == "OK"
    assert not list(s.root.rglob("*.part"))


def test_running_twice_changes_nothing(tmp_path):
    inbox = tmp_path / "in"
    make_batch(inbox, 1, 100)
    s = store(tmp_path)
    s.ingest_directory(inbox, symbol=SYMBOL)
    ledger = (s.root / "LEDGER.jsonl").read_bytes()
    again = s.ingest_directory(inbox, symbol=SYMBOL)
    assert again["summary"] == {"ALREADY": 1}
    assert (s.root / "LEDGER.jsonl").read_bytes() == ledger


def test_budget_stops_before_writing_and_tries_nothing_after(tmp_path):
    inbox = tmp_path / "in"
    first = make_batch(inbox, 1, 1000)
    make_batch(inbox, 1001, 2000)
    make_batch(inbox, 2001, 3000)
    one = first.stat().st_size + (inbox / json.loads(first.read_text())["file"]).stat().st_size
    s = store(tmp_path, limit=one + one // 2)
    report = s.ingest_directory(inbox, symbol=SYMBOL)
    assert [r["status"] for r in report["results"]] == ["STORED", "BUDGET_STOP", "NOT_TRIED"]
    assert report["halted"] == "BUDGET_STOP" and report["used_bytes"] <= s.limit_bytes
    assert len(list((s.root / "batches" / SYMBOL).iterdir())) == 2
    # Still stopped on the next run: no automatic deletion makes room.
    assert s.ingest_directory(inbox, symbol=SYMBOL)["halted"] == "BUDGET_STOP"
    assert s.verify()["status"] == "OK"


def test_budget_counts_files_on_disk_even_if_the_ledger_misses_them(tmp_path):
    s = store(tmp_path, limit=5000)
    stray = s.root / "batches" / SYMBOL
    stray.mkdir(parents=True)
    (stray / "foreign.bin").write_bytes(b"x" * 4900)
    make_batch(tmp_path / "in", 1, 100)
    assert s.ingest_directory(tmp_path / "in", symbol=SYMBOL)["halted"] == "BUDGET_STOP"
    assert s.verify()["problems"] == [f"not in ledger: batches/{SYMBOL}/foreign.bin"]


def test_free_space_gate_stops_too(tmp_path):
    s = cold_store.ColdStore.init(tmp_path / "store", usage=lambda _p: Usage(1000, 900, 100))
    make_batch(tmp_path / "in", 1, 100)
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["halted"] == "DISK_STOP" and not list((s.root / "batches").rglob("*.gz"))


@pytest.mark.parametrize("tamper", ["file", "content"])
def test_damaged_batches_are_refused_and_nothing_is_written(tmp_path, tamper):
    make_batch(tmp_path / "in", 1, 100, tamper=tamper)
    s = store(tmp_path)
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"FILE_INVALID": 1} and s.ledger() == []


def test_id_inside_a_declared_hole_is_refused(tmp_path):
    path = make_batch(tmp_path / "in", 1, 100, holes=[(50, 50)])
    manifest = json.loads(path.read_text())
    manifest["holes"] = [[60, 60]]
    manifest["row_count"] = 99
    manifest["batch_id"] = batch_id_for("new", SYMBOL, 1, 100, manifest["content_sha256"], [[60, 60]])
    path.write_text(json.dumps(manifest))
    report = store(tmp_path).ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["results"][0]["status"] == "FILE_INVALID" and "hole" in report["results"][0]["reason"]


def test_a_different_file_under_a_stored_name_is_a_conflict_and_never_overwritten(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "a", 1, 100)
    s.ingest_directory(tmp_path / "a", symbol=SYMBOL)
    original = {p.name: p.read_bytes() for p in (s.root / "batches" / SYMBOL).iterdir()}
    make_batch(tmp_path / "b", 1, 100, price="61339.06")
    report = s.ingest_directory(tmp_path / "b", symbol=SYMBOL)
    assert report["summary"] == {"CONFLICT": 1}
    assert {p.name: p.read_bytes() for p in (s.root / "batches" / SYMBOL).iterdir()} == original


def test_crash_after_the_data_file_is_resumed_without_duplicates(tmp_path, monkeypatch):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    real = cold_store._copy_verified
    calls = {"n": 0}

    def dying(src, dst, sha):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("process died before the manifest was stored")
        return real(src, dst, sha)

    monkeypatch.setattr(cold_store, "_copy_verified", dying)
    with pytest.raises(OSError):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    monkeypatch.setattr(cold_store, "_copy_verified", real)
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"RESUMED": 1}
    assert len(s.ledger()) == 2 and s.verify()["status"] == "OK"


def test_verify_finds_changed_and_missing_files(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    make_batch(tmp_path / "in", 101, 200)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    files = sorted((s.root / "batches" / SYMBOL).glob("*.csv.gz"))
    files[0].write_bytes(files[0].read_bytes() + b"\0")
    files[1].rename(files[1].with_name("moved.bin"))
    problems = s.verify()["problems"]
    assert any(p.startswith("changed:") for p in problems) and any(p.startswith("missing:") for p in problems)


def test_migration_copies_and_verifies_and_keeps_the_source(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    make_batch(tmp_path / "in", 101, 200)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    source_before = {p: p.read_bytes() for p in s.root.rglob("*") if p.is_file()}
    receipt = cold_store.migrate_store(s.root, tmp_path / "new-disk")
    assert receipt["status"] == "OK" and receipt["copied_files"] == 4 and receipt["same_bytes"]
    assert {p: p.read_bytes() for p in s.root.rglob("*") if p.is_file()} == source_before
    new = cold_store.ColdStore(tmp_path / "new-disk")
    assert new.limit_bytes == s.limit_bytes and new.verify()["status"] == "OK"
    with pytest.raises(ArchiveSyncError, match="not empty"):
        cold_store.migrate_store(s.root, tmp_path / "new-disk")


def test_init_refuses_a_foreign_directory_and_a_silent_limit_change(tmp_path):
    foreign = tmp_path / "warpgate-data"
    foreign.mkdir()
    (foreign / "db.sqlite3").write_bytes(b"x")
    with pytest.raises(ArchiveSyncError, match="not empty"):
        cold_store.ColdStore.init(foreign)
    s = store(tmp_path, limit=1000)
    with pytest.raises(ArchiveSyncError, match="another limit"):
        cold_store.ColdStore.init(s.root, limit_bytes=2000)
    assert cold_store.DEFAULT_LIMIT_BYTES == 100 * 1024**3


def test_module_has_no_delete_path():
    source = Path(cold_store.__file__).read_text()
    assert "rmtree" not in source and "os.remove" not in source
    # The only unlink calls remove the module's own temporary ".part" files.
    assert source.count(".unlink(") == source.count("part.unlink(")


def test_command_line_runs_the_whole_cycle(tmp_path, capsys):
    from src.archive_sync import __main__ as cli

    make_batch(tmp_path / "in", 1, 100)
    root, new = str(tmp_path / "store"), str(tmp_path / "new")
    assert cli.main(["cold-init", "--root", root, "--limit-gb", "1"]) == 0
    assert cli.main(["cold-ingest", "--root", root, "--dir", str(tmp_path / "in"), "--symbol", SYMBOL]) == 0
    assert cli.main(["cold-verify", "--root", root]) == 0
    assert cli.main(["cold-migrate", "--root", root, "--to", new]) == 0
    assert cli.main(["cold-init", "--root", str(tmp_path / "in")]) == 2  # foreign directory refused
    capsys.readouterr()
