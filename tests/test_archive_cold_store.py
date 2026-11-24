"""INFRA-09 draft: cold file store with a hard byte budget. Pure file tests, no database."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
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
    assert not list(s.root.rglob("*.part")) and not list(s.root.rglob(".tmp-*"))


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

    def dying(src, dst, sha, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("process died before the manifest was stored")
        return real(src, dst, sha, **kw)

    monkeypatch.setattr(cold_store, "_copy_verified", dying)
    with pytest.raises(ArchiveSyncError, match="process died"):
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
    files[0].chmod(0o644)
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
    # The only unlink removes a temporary file this process created itself (guarded by its prefix).
    assert source.count(".unlink(") == 1 and "os.unlink(name, dir_fd=dir_fd)" in source
    assert ".truncate(" not in source and "ftruncate" not in source
    assert "os.replace" not in source and ".replace(info)" not in source and "os.rename" not in source


def test_command_line_runs_the_whole_cycle(tmp_path, capsys):
    from src.archive_sync import __main__ as cli

    make_batch(tmp_path / "in", 1, 100)
    root, new = str(tmp_path / "store"), str(tmp_path / "new")
    assert cli.main(["cold-init", "--root", root, "--limit-gib", "1"]) == 0
    # An unbound store is refused by the command line unless explicitly allowed for local tests.
    assert cli.main(["cold-ingest", "--root", root, "--dir", str(tmp_path / "in"), "--symbol", SYMBOL]) == 2
    assert cli.main(["cold-ingest", "--root", root, "--dir", str(tmp_path / "in"), "--symbol", SYMBOL, "--unbound-ok"]) == 0
    assert cli.main(["cold-verify", "--root", root, "--unbound-ok"]) == 0
    assert cli.main(["cold-migrate", "--root", root, "--to", new, "--unbound-ok"]) == 0
    assert cli.main(["cold-init", "--root", str(tmp_path / "in"), "--limit-gib", "1"]) == 2  # foreign directory refused
    with pytest.raises(SystemExit):  # the budget is never implied
        cli.main(["cold-init", "--root", str(tmp_path / "other")])
    assert not (tmp_path / "other").exists()
    capsys.readouterr()


# ---------------------------------------------------------------- INFRA-09 preflight hardening
class FakeMounts:
    """Stands in for os.path.ismount: the tests decide which directories count as mounted."""

    def __init__(self, *paths):
        self.mounted = {str(Path(p).resolve()) for p in paths}

    def __call__(self, path):
        return str(Path(path).resolve()) in self.mounted


def bound(tmp_path, limit=10**9, parent_usage=None):
    volume = tmp_path / "vol"
    volume.mkdir()
    mounts = FakeMounts(volume)
    usage = parent_usage or ROOMY
    s = cold_store.ColdStore.init(volume / "store", limit_bytes=limit, volume_mount=volume, parent=tmp_path,
                                  is_mount=mounts, usage=usage)
    return s, volume, mounts


def test_bound_store_records_its_volume_and_marker(tmp_path):
    s, volume, mounts = bound(tmp_path)
    marker = (volume / cold_store.VOLUME_MARKER).read_text().strip()
    assert s.volume["volume_id"] == marker and s.volume["mount"] == str(volume.resolve())
    assert s.check_volume()["bound"] is True
    assert not os.access(volume / cold_store.VOLUME_MARKER, os.W_OK) or os.geteuid() == 0


def test_absent_mount_fails_closed_at_open_and_before_every_write(tmp_path):
    s, volume, mounts = bound(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    make_batch(tmp_path / "in", 101, 200)
    mounts.mounted.clear()
    with pytest.raises(ArchiveSyncError, match="not mounted"):
        cold_store.ColdStore(s.root, is_mount=mounts, usage=ROOMY)
    with pytest.raises(ArchiveSyncError, match="not mounted"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert s.ledger() == [] and not list((s.root / "batches").rglob("*.gz"))


def test_mount_disappearing_between_two_files_stops_the_next_write(tmp_path, monkeypatch):
    s, volume, mounts = bound(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    real = cold_store._copy_verified

    def copy_then_unmount(src, dst, sha, **kw):
        real(src, dst, sha, **kw)
        mounts.mounted.clear()

    monkeypatch.setattr(cold_store, "_copy_verified", copy_then_unmount)
    with pytest.raises(ArchiveSyncError, match="not mounted"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert len(list((s.root / "batches" / SYMBOL).iterdir())) == 1  # the manifest never followed


def test_wrong_volume_is_refused(tmp_path):
    s, volume, mounts = bound(tmp_path)
    marker = volume / cold_store.VOLUME_MARKER
    marker.chmod(0o644)
    marker.write_text("some-other-volume\n")
    with pytest.raises(ArchiveSyncError, match="wrong volume"):
        cold_store.ColdStore(s.root, is_mount=mounts, usage=ROOMY)


def test_init_needs_a_real_mount_and_a_root_inside_it(tmp_path):
    volume = tmp_path / "vol"
    volume.mkdir()
    with pytest.raises(ArchiveSyncError, match="not a mounted"):
        cold_store.ColdStore.init(volume / "store", volume_mount=volume, is_mount=FakeMounts())
    with pytest.raises(ArchiveSyncError, match="inside the volume"):
        cold_store.ColdStore.init(tmp_path / "elsewhere", volume_mount=volume, is_mount=FakeMounts(volume))
    with pytest.raises(ArchiveSyncError, match="sub-directory"):
        cold_store.ColdStore.init(volume, volume_mount=volume, is_mount=FakeMounts(volume))


def test_parent_file_system_below_reserve_stops_every_write(tmp_path):
    def usage(path):
        return Usage(1000, 900, 100) if Path(path).resolve() == tmp_path.resolve() else Usage(10**12, 0, 10**12)

    volume = tmp_path / "vol"
    volume.mkdir()
    mounts = FakeMounts(volume)
    s = cold_store.ColdStore.init(volume / "store", volume_mount=volume, is_mount=mounts, usage=ROOMY)
    s.volume["parent"] = str(tmp_path)  # same as --parent, set after init so init itself can run
    s._usage = usage
    make_batch(tmp_path / "in", 1, 100)
    with pytest.raises(ArchiveSyncError, match="parent file system"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert s.ledger() == []


def test_second_writer_is_refused_while_the_first_holds_the_lock(tmp_path):
    s = store(tmp_path)
    other = cold_store.ColdStore(s.root, usage=ROOMY)
    make_batch(tmp_path / "in", 1, 100)
    with s._locked():
        with pytest.raises(ArchiveSyncError, match="lock"):
            other.ingest_directory(tmp_path / "in", symbol=SYMBOL)
        with pytest.raises(ArchiveSyncError, match="lock"):
            cold_store.migrate_store(s.root, tmp_path / "copy")
    assert other.ingest_directory(tmp_path / "in", symbol=SYMBOL)["summary"] == {"STORED": 1}


def test_concurrent_processes_never_store_a_batch_twice(tmp_path):
    import multiprocessing

    s = store(tmp_path)
    for lo in range(1, 2001, 100):
        make_batch(tmp_path / "in", lo, lo + 99)
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(4) as pool:
        reports = pool.map(_ingest_worker, [(str(s.root), str(tmp_path / "in"))] * 4)
    stored = sum(r.get("STORED", 0) for r in reports)
    final = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert stored + final["summary"].get("STORED", 0) == 20
    paths = [e["path"] for e in s.ledger()]
    assert len(paths) == len(set(paths)) == 40 and s.verify()["status"] == "OK"


def _ingest_worker(args):
    root, inbox = args
    try:
        return cold_store.ColdStore(root, usage=ROOMY).ingest_directory(inbox, symbol=SYMBOL)["summary"]
    except ArchiveSyncError:
        return {"LOCKED": 1}


def test_torn_last_ledger_line_is_ignored_and_the_file_re_recorded(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    ledger = s.root / "LEDGER.jsonl"
    text = ledger.read_text()
    ledger.write_text(text[: len(text) - 20])  # crash in the middle of the last append
    assert len(s.ledger()) == 1
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"RESUMED": 1}
    assert len(s.ledger()) == 2 and s.verify()["status"] == "OK"


def test_unreadable_ledger_line_in_the_middle_stops_everything(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    ledger = s.root / "LEDGER.jsonl"
    lines = ledger.read_text().splitlines(keepends=True)
    ledger.write_text(lines[0] + "{broken\n" + lines[1])
    with pytest.raises(ArchiveSyncError, match="ledger line 2"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)


def test_symbolic_links_are_refused_in_inbox_and_store_path(tmp_path):
    real = make_batch(tmp_path / "real", 1, 100)
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / real.name).symlink_to(real)
    (inbox / json.loads(real.read_text())["file"]).symlink_to(tmp_path / "real" / json.loads(real.read_text())["file"])
    s = store(tmp_path)
    assert s.ingest_directory(inbox, symbol=SYMBOL)["results"][0]["reason"] == "symbolic link refused"
    data_only = tmp_path / "in2"
    data_only.mkdir()
    (data_only / real.name).write_text(real.read_text())
    (data_only / json.loads(real.read_text())["file"]).symlink_to(tmp_path / "real" / json.loads(real.read_text())["file"])
    assert s.ingest_directory(data_only, symbol=SYMBOL)["results"][0]["reason"] == "symbolic link refused"
    (tmp_path / "alias").symlink_to(s.root)
    with pytest.raises(ArchiveSyncError, match="symbolic link"):
        cold_store.ColdStore(tmp_path / "alias")
    with pytest.raises(ArchiveSyncError, match="unsafe symbol"):
        s.ingest_directory(inbox, symbol="../x")


def test_stored_files_and_store_metadata_are_read_only(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    for entry in s.ledger():
        assert (s.root / entry["path"]).stat().st_mode & 0o222 == 0
    assert (s.root / "STORE.json").stat().st_mode & 0o222 == 0
    one = s.root / s.ledger()[0]["path"]
    one.chmod(0o644)
    assert s.verify()["problems"] == [f"writable (should be read-only): {s.ledger()[0]['path']}"]


def test_restart_reopens_the_store_and_continues(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    make_batch(tmp_path / "in", 101, 200)
    reopened = cold_store.ColdStore(s.root, usage=ROOMY)
    assert reopened.ingest_directory(tmp_path / "in", symbol=SYMBOL)["summary"] == {"ALREADY": 1, "STORED": 1}


def test_backup_and_restore_through_two_migrations_is_bit_identical(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    make_batch(tmp_path / "in", 101, 200, holes=[(120, 125)])
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert cold_store.migrate_store(s.root, tmp_path / "backup")["status"] == "OK"
    assert cold_store.migrate_store(tmp_path / "backup", tmp_path / "restored")["status"] == "OK"
    original = {e["path"]: e["sha256"] for e in s.ledger()}
    restored = cold_store.ColdStore(tmp_path / "restored")
    assert {e["path"]: e["sha256"] for e in restored.ledger()} == original
    assert all(sha256_file(restored.root / p) == h for p, h in original.items())
    # A restored store accepts the same inbox as ALREADY: no duplicates after a restore.
    assert restored.ingest_directory(tmp_path / "in", symbol=SYMBOL)["summary"] == {"ALREADY": 2}


def test_sparse_volume_image_stops_every_write(tmp_path):
    volume = tmp_path / "vol"
    volume.mkdir()
    image = tmp_path / "archive.img"
    with image.open("wb") as handle:
        handle.write(b"\0" * 65536)
        handle.flush()
        os.fsync(handle.fileno())
    mounts = FakeMounts(volume)
    s = cold_store.ColdStore.init(volume / "store", volume_mount=volume, image=image, is_mount=mounts, usage=ROOMY)
    assert s.check_volume()["bound"] is True
    with image.open("r+b") as handle:  # make the file sparse, as a trim of the loop file system would
        handle.truncate(64 * 1024 * 1024)
    make_batch(tmp_path / "in", 1, 100)
    with pytest.raises(ArchiveSyncError, match="sparse"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)


# ---------------------------------------------------------------- INFRA-09 remediation: confinement
def snapshot(folder: Path, skip=()) -> dict[str, tuple]:
    """Every entry below folder (no links followed) with its content hash, except the skipped trees."""
    found = {}
    for path in sorted(folder.rglob("*")):
        rel = str(path.relative_to(folder))
        if any(rel == s or rel.startswith(s + "/") for s in skip):
            continue
        info = path.lstat()
        body = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        found[rel] = (oct(info.st_mode), hashlib.sha256(body).hexdigest() if body is not None else None,
                      os.readlink(path) if path.is_symlink() else None)
    return found


def test_planted_link_under_a_stored_name_is_a_conflict_and_the_outside_file_is_untouched(tmp_path):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"precious")
    folder = s.root / "batches" / SYMBOL
    folder.mkdir()
    (folder / json.loads(manifest.read_text())["file"]).symlink_to(victim)
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"CONFLICT": 1} and victim.read_bytes() == b"precious"
    assert s.ledger() == []


def test_symbol_directory_replaced_by_a_link_is_refused(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    outside = tmp_path / "outside"
    outside.mkdir()
    (s.root / "batches" / SYMBOL).symlink_to(outside)
    with pytest.raises(ArchiveSyncError, match="symbolic link"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert list(outside.iterdir()) == [] and s.ledger() == []


def test_ledger_and_lock_replaced_by_links_are_refused(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"precious, no newline at the end")
    ledger = s.root / "LEDGER.jsonl"
    ledger.rename(tmp_path / "ledger.saved")
    ledger.symlink_to(victim)
    with pytest.raises(ArchiveSyncError, match="symbolic link"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert victim.read_bytes() == b"precious, no newline at the end"  # not truncated, not appended
    ledger.unlink()
    (tmp_path / "ledger.saved").rename(ledger)
    lock = s.root / ".lock"
    lock.unlink()
    lock.symlink_to(tmp_path / "planted-lock")
    with pytest.raises(ArchiveSyncError, match="symbolic link"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert not (tmp_path / "planted-lock").exists()


def test_ledger_path_leaving_the_store_stops_verify_and_migration(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    ledger = s.root / "LEDGER.jsonl"
    entry = json.loads(ledger.read_text().splitlines()[0])
    for evil in ("../../escape.txt", "batches/BTCUSDT/../../../escape.txt", "/etc/passwd", "STORE.json"):
        ledger.write_text(ledger.read_text() + json.dumps({**entry, "path": evil}) + "\n")
        with pytest.raises(ArchiveSyncError, match="outside batches"):
            s.verify()
        with pytest.raises(ArchiveSyncError, match="outside batches"):
            cold_store.migrate_store(s.root, tmp_path / f"m-{len(evil)}")
        ledger.write_text("".join(line + "\n" for line in ledger.read_text().splitlines()[:-1]))
    assert not (tmp_path / "escape.txt").exists() and s.verify()["status"] == "OK"


def test_manifest_with_foreign_symbol_or_unsafe_file_name_is_invalid(tmp_path):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    body = json.loads(manifest.read_text())
    for change, reason in (({"symbol": "ETHUSDT"}, "symbol"), ({"file": ".hidden.csv.gz"}, "file name"),
                           ({"file": "../x.csv.gz"}, "file name")):
        manifest.write_text(json.dumps({**body, **change}))
        report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
        assert report["summary"] == {"FILE_INVALID": 1} and reason in report["results"][0]["reason"]
    assert s.ledger() == [] and not list((s.root / "batches").rglob("*.gz"))


def test_fifo_in_the_inbox_does_not_hang_and_is_invalid(tmp_path):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    data = tmp_path / "in" / json.loads(manifest.read_text())["file"]
    data.unlink()
    os.mkfifo(data)
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"FILE_INVALID": 1}


def test_manifest_changed_after_the_check_stores_the_checked_bytes(tmp_path, monkeypatch):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    checked = manifest.read_bytes()
    real = cold_store._check_batch

    def swap_after_reading(path, parsed=None, symbol=None):
        result = real(path, parsed, symbol)
        path.write_bytes(checked.replace(b'"kind": "new"', b'"kind": "new", "x": 1'))
        return result

    monkeypatch.setattr(cold_store, "_check_batch", swap_after_reading)
    assert s.ingest_directory(tmp_path / "in", symbol=SYMBOL)["summary"] == {"STORED": 1}
    assert (s.root / "batches" / SYMBOL / manifest.name).read_bytes() == checked


def test_data_changed_after_the_check_is_refused_without_leftovers(tmp_path, monkeypatch):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    data = tmp_path / "in" / json.loads(manifest.read_text())["file"]
    real = cold_store._check_batch

    def swap_after_check(path, parsed=None, symbol=None):
        result = real(path, parsed, symbol)
        data.write_bytes(gzip.compress(b"forged\n", mtime=0))
        return result

    monkeypatch.setattr(cold_store, "_check_batch", swap_after_check)
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"FILE_INVALID": 1} and "sha256 changed" in report["results"][0]["reason"]
    assert list((s.root / "batches" / SYMBOL).iterdir()) == [] and s.ledger() == []


def test_verify_reports_extra_hard_links_and_left_over_temporary_files(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    stored = s.root / s.ledger()[0]["path"]
    os.link(stored, tmp_path / "second-name")
    (stored.parent / ".tmp-0123").write_bytes(b"x" * 10)
    problems = s.verify()["problems"]
    assert any(p.startswith("extra hard link") for p in problems)
    assert any(p.startswith("left-over temporary file") for p in problems)
    assert s.used_bytes() >= sum(e["bytes"] for e in s.ledger()) + 10


def test_planted_volume_marker_link_is_refused(tmp_path):
    volume = tmp_path / "vol"
    volume.mkdir()
    victim = tmp_path / "victim.txt"
    (volume / cold_store.VOLUME_MARKER).symlink_to(victim)
    with pytest.raises(ArchiveSyncError, match="symbolic link"):
        cold_store.ColdStore.init(volume / "store", volume_mount=volume, is_mount=FakeMounts(volume), usage=ROOMY)
    assert not victim.exists()


def test_full_cycle_writes_nothing_outside_the_store_and_the_migration_target(tmp_path):
    s, volume, mounts = bound(tmp_path)
    for lo in range(1, 501, 100):
        make_batch(tmp_path / "in", lo, lo + 99)
    before = snapshot(tmp_path, skip=("vol/store", "copy"))
    assert s.ingest_directory(tmp_path / "in", symbol=SYMBOL)["summary"] == {"STORED": 5}
    assert s.verify()["status"] == "OK"
    assert cold_store.migrate_store(s.root, tmp_path / "copy", source_is_mount=mounts)["status"] == "OK"
    assert snapshot(tmp_path, skip=("vol/store", "copy")) == before


@pytest.mark.parametrize("seed", range(25))
def test_random_runs_keep_the_budget_and_integrity_invariants(tmp_path, seed):
    import random

    rng = random.Random(seed)
    sizes = [rng.randint(20, 400) for _ in range(rng.randint(3, 9))]
    lo = 1
    for size in sizes:
        make_batch(tmp_path / "in", lo, lo + size - 1, holes=[(lo + 5, lo + 7)] if rng.random() < 0.3 else ())
        lo += size
    one = sum(p.stat().st_size for p in (tmp_path / "in").iterdir()) / len(sizes)
    limit = int(one * rng.uniform(0.5, len(sizes) + 1))
    s = store(tmp_path, limit=limit)
    for _ in range(rng.randint(1, 4)):  # repeated runs, as after restarts
        report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
        assert report["used_bytes"] <= limit
        assert set(report["summary"]) <= {"STORED", "ALREADY", "BUDGET_STOP", "NOT_TRIED"}
    paths = [e["path"] for e in s.ledger()]
    assert len(paths) == len(set(paths)) and len(paths) % 2 == 0
    assert s.used_bytes() <= limit and s.verify()["status"] == "OK"
    for entry in s.ledger():  # every stored file equals its original byte for byte
        assert (s.root / entry["path"]).read_bytes() == (tmp_path / "in" / Path(entry["path"]).name).read_bytes()


# ---------------------------------------------------------------- INFRA-09 remediation: second review
def test_invalid_utf8_batch_is_invalid_not_a_crash(tmp_path):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    body = json.loads(manifest.read_text())
    raw = b"\xff\xfe" * 10
    data = tmp_path / "in" / body["file"]
    data.write_bytes(gzip.compress(raw, mtime=0))
    content = hashlib.sha256(raw).hexdigest()
    body.update(content_sha256=content, csv_bytes=len(raw), file_bytes=data.stat().st_size, file_sha256=sha256_file(data),
                batch_id=batch_id_for("new", SYMBOL, 1, 100, content, []))
    manifest.write_text(json.dumps(body))
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"FILE_INVALID": 1} and "UTF-8" in report["results"][0]["reason"]


def test_non_canonical_trade_ids_are_invalid(tmp_path):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 3)
    body = json.loads(manifest.read_text())
    rows = "".join(f"{SYMBOL},{i},2026-11-22 23:55:05+00,1,1,f,X,2026-11-22 23:55:05+00\n" for i in ("+1", "2", "3"))
    data = tmp_path / "in" / body["file"]
    data.write_bytes(gzip.compress(rows.encode(), mtime=0))
    content = hashlib.sha256(rows.encode()).hexdigest()
    body.update(content_sha256=content, csv_bytes=len(rows), file_bytes=data.stat().st_size, file_sha256=sha256_file(data),
                batch_id=batch_id_for("new", SYMBOL, 1, 3, content, []))
    manifest.write_text(json.dumps(body))
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"FILE_INVALID": 1} and "canonical" in report["results"][0]["reason"]


def test_source_growing_after_the_check_never_exceeds_its_declared_size(tmp_path, monkeypatch):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    data = tmp_path / "in" / json.loads(manifest.read_text())["file"]
    declared = data.stat().st_size
    real = cold_store._check_batch

    def grow_after_check(path, parsed=None, symbol=None):
        result = real(path, parsed, symbol)
        with data.open("ab") as handle:
            handle.write(b"\0" * (4 << 20))
        return result

    monkeypatch.setattr(cold_store, "_check_batch", grow_after_check)
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"FILE_INVALID": 1} and "larger than declared" in report["results"][0]["reason"]
    assert s.ledger() == [] and list((s.root / "batches" / SYMBOL).iterdir()) == []
    assert declared < (4 << 20)


def test_same_batch_under_a_second_name_is_a_conflict(tmp_path):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    body = json.loads(manifest.read_text())
    copy = tmp_path / "in2"
    copy.mkdir()
    new_name = body["file"].replace("-new-", "-copy-")
    (copy / new_name).write_bytes((tmp_path / "in" / body["file"]).read_bytes())
    (copy / new_name.replace(".csv.gz", ".manifest.json")).write_text(json.dumps({**body, "file": new_name}))
    report = s.ingest_directory(copy, symbol=SYMBOL)
    assert report["summary"] == {"CONFLICT": 1} and "another name" in report["results"][0]["reason"]


def test_manifest_and_data_names_must_pair(tmp_path):
    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    body = json.loads(manifest.read_text())
    other = body["file"].replace("-new-", "-other-")
    (tmp_path / "in" / body["file"]).rename(tmp_path / "in" / other)
    manifest.write_text(json.dumps({**body, "file": other}))
    report = s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    assert report["summary"] == {"FILE_INVALID": 1} and "match the manifest" in report["results"][0]["reason"]


def test_empty_or_malformed_volume_marker_fails_closed(tmp_path):
    volume = tmp_path / "vol"
    volume.mkdir()
    (volume / cold_store.VOLUME_MARKER).write_text("")
    with pytest.raises(ArchiveSyncError, match="malformed"):
        cold_store.ColdStore.init(volume / "store", volume_mount=volume, is_mount=FakeMounts(volume), usage=ROOMY)
    (tmp_path / "b").mkdir()
    s, vol2, _mounts = bound(tmp_path / "b")
    marker = vol2 / cold_store.VOLUME_MARKER
    marker.chmod(0o644)
    marker.write_text("")
    with pytest.raises(ArchiveSyncError, match="wrong volume"):
        s.check_volume()


def test_init_refuses_root_volume_oversized_limit_and_a_changed_binding(tmp_path):
    with pytest.raises(ArchiveSyncError, match="root file system"):
        cold_store.ColdStore.init(tmp_path / "x", volume_mount="/", is_mount=lambda p: True, usage=ROOMY)
    volume = tmp_path / "vol"
    volume.mkdir()
    small = lambda _p: Usage(10**6, 0, 10**6)  # noqa: E731
    with pytest.raises(ArchiveSyncError, match="15% reserve"):
        cold_store.ColdStore.init(volume / "store", limit_bytes=10**6, volume_mount=volume,
                                  is_mount=FakeMounts(volume), usage=small)
    assert not (volume / "store").exists() and not (volume / cold_store.VOLUME_MARKER).exists()
    s = store(tmp_path)
    with pytest.raises(ArchiveSyncError, match="volume binding"):
        cold_store.ColdStore.init(s.root, limit_bytes=s.limit_bytes, volume_mount=volume, is_mount=FakeMounts(volume))


def test_init_creates_only_the_store_directory(tmp_path):
    with pytest.raises(ArchiveSyncError, match="does not exist"):
        cold_store.ColdStore.init(tmp_path / "a" / "b" / "store", usage=ROOMY)
    assert not (tmp_path / "a").exists()


def test_vanished_inbox_file_and_file_system_errors_are_clean_errors(tmp_path, monkeypatch):
    from src.archive_sync import __main__ as cli

    s = store(tmp_path)
    manifest = make_batch(tmp_path / "in", 1, 100)
    real = cold_store._read_bytes

    def vanish(name, dir_fd):
        if name == manifest.name:
            raise FileNotFoundError(2, "No such file or directory")
        return real(name, dir_fd)

    monkeypatch.setattr(cold_store, "_read_bytes", vanish)
    assert s.ingest_directory(tmp_path / "in", symbol=SYMBOL)["summary"] == {"FILE_INVALID": 1}
    monkeypatch.setattr(cold_store, "_read_bytes", real)

    def full(*_a, **_k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cold_store, "_write_new", full)
    with pytest.raises(ArchiveSyncError, match="ENOSPC: halted"):
        s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    code = cli.main(["cold-ingest", "--root", str(s.root), "--dir", str(tmp_path / "in"), "--symbol", SYMBOL,
                     "--unbound-ok"])
    assert code == 2 and s.ledger() == []


def test_torn_ledger_is_closed_not_truncated(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    ledger = s.root / "LEDGER.jsonl"
    torn = ledger.read_bytes()[:-20]
    ledger.write_bytes(torn)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    after = ledger.read_bytes()
    assert after.startswith(torn + b"\n") and b"torn_tail_discarded" in after
    assert len(s.ledger()) == 2 and s.verify()["status"] == "OK"


def test_migration_into_or_around_the_source_is_refused(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    before = snapshot(s.root)
    with pytest.raises(ArchiveSyncError, match="contain each other"):
        cold_store.migrate_store(s.root, s.root / "batches" / "copy")
    with pytest.raises(ArchiveSyncError, match="contain each other"):
        cold_store.migrate_store(s.root, tmp_path)
    assert snapshot(s.root) == before


def test_verify_is_refused_while_a_writer_holds_the_lock(tmp_path):
    s = store(tmp_path)
    with s._locked():
        with pytest.raises(ArchiveSyncError, match="lock"):
            cold_store.ColdStore(s.root, usage=ROOMY).verify()
    assert s.verify()["status"] == "OK"


def test_torn_append_that_only_lost_its_newline_is_recorded_once(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    ledger = s.root / "LEDGER.jsonl"
    ledger.write_bytes(ledger.read_bytes()[:-1])  # crash after the entry, before its newline
    assert len(s.ledger()) == 1
    assert s.ingest_directory(tmp_path / "in", symbol=SYMBOL)["summary"] == {"RESUMED": 1}
    paths = [e["path"] for e in s.ledger()]
    assert len(paths) == len(set(paths)) == 2 and b"torn_tail_closed" in ledger.read_bytes()
    assert cold_store.migrate_store(s.root, tmp_path / "copy")["status"] == "OK"


def test_ledger_repeating_a_path_with_other_content_stops_everything(tmp_path):
    s = store(tmp_path)
    make_batch(tmp_path / "in", 1, 100)
    s.ingest_directory(tmp_path / "in", symbol=SYMBOL)
    ledger = s.root / "LEDGER.jsonl"
    first = json.loads(ledger.read_text().splitlines()[0])
    ledger.write_text(ledger.read_text() + json.dumps({**first, "sha256": "0" * 64}) + "\n")
    with pytest.raises(ArchiveSyncError, match="other content"):
        s.verify()


def test_verify_needs_no_write_access_to_the_lock(tmp_path):
    s = store(tmp_path)
    (s.root / ".lock").chmod(0o444)
    assert s.verify()["status"] == "OK"
