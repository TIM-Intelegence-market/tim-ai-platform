"""INFRA-09 cold-state: archive state from a cold store. Pure file tests, no database.

The PostgreSQL round trip (exporter -> cold store -> cold-state -> exporter, and the same files
into the server importer) is in ``test_archive_cold_state_pg.py``.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest

from src.archive_sync import __main__ as cli
from src.archive_sync import cold_state, cold_store, exporter
from src.archive_sync.common import (
    COLUMNS,
    FORMAT,
    ArchiveSyncError,
    batch_id_for,
    sha256_file,
)
from tests.test_archive_cold_store import ROOMY, SYMBOL, FakeMounts



def batch(folder: Path, kind: str, lo: int, hi: int, *, holes=(), price="61339.05", batch_id=None) -> Path:
    """One exporter-shaped batch (any kind), same file names and manifest fields as the exporter."""
    folder.mkdir(parents=True, exist_ok=True)
    hole_ids = {i for a, b in holes for i in range(a, b + 1)}
    csv = "".join(
        f"{SYMBOL},{i},2026-11-22 23:55:05.282+00,{price},0.00027,f,BINANCE_SPOT_AGGTRADE,2026-11-22 23:55:05.5105+00\n"
        for i in range(lo, hi + 1) if i not in hole_ids
    ).encode()
    content = hashlib.sha256(csv).hexdigest()
    base = exporter.batch_basename(SYMBOL, kind, lo, hi)
    data = folder / f"{base}.csv.gz"
    data.write_bytes(gzip.compress(csv, mtime=0))
    holes = [list(h) for h in holes]
    manifest = {
        "format": FORMAT, "kind": kind, "symbol": SYMBOL, "lo": lo, "hi": hi, "holes": holes,
        "row_count": csv.count(b"\n"), "content_sha256": content, "csv_bytes": len(csv), "file": data.name,
        "file_bytes": data.stat().st_size, "file_sha256": sha256_file(data), "columns": list(COLUMNS),
        "batch_id": batch_id or batch_id_for(kind, SYMBOL, lo, hi, content, holes),
    }
    path = folder / f"{base}.manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def new_store(tmp_path: Path, limit: int = 10**9) -> cold_store.ColdStore:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return cold_store.ColdStore.init(tmp_path / "store", limit_bytes=limit, usage=ROOMY)


def ingest(store, folder):
    report = store.ingest_directory(folder, symbol=SYMBOL)
    return report


def state_of(store, **kw):
    return cold_state.cold_state(store, SYMBOL, **kw)


def core(report):
    return {k: report[k] for k in ("start_id", "watermark", "holes")}


# ----------------------------------------------------------------------- state from the ledger
def test_empty_store_gives_the_state_of_an_empty_archive(tmp_path):
    report = state_of(new_store(tmp_path))
    assert core(report) == {"start_id": None, "watermark": None, "holes": []}
    assert report["symbol"] == SYMBOL and report["archived_trades"] == 0 and report["not_applied"] == []
    # The exporter's planner takes it like the server's state: export everything from the Mac's oldest id.
    assert exporter.plan_ranges(server_state=report, mac_cursor=250, mac_min=1, chunk=100) == [
        ("new", 1, 100), ("new", 101, 200), ("new", 201, 250)]


def test_new_batches_with_holes_give_watermark_start_and_open_holes(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "in", "new", 1, 100, holes=[(40, 45)])
    batch(tmp_path / "in", "new", 101, 200, holes=[(101, 101), (190, 200)])
    assert ingest(s, tmp_path / "in")["summary"] == {"STORED": 2}
    report = state_of(s)
    assert core(report) == {"start_id": 1, "watermark": 200, "holes": [[40, 45], [101, 101], [190, 200]]}
    assert report["archived_trades"] == 200 - 6 - 1 - 11 and report["batches_applied"] == 2
    # Next export: backfill the open holes, then new data after the watermark.
    assert exporter.plan_ranges(server_state=report, mac_cursor=260, mac_min=1, chunk=100) == [
        ("backfill", 40, 45), ("backfill", 101, 101), ("backfill", 190, 200), ("new", 201, 260)]


def test_backfill_in_the_middle_of_a_hole_leaves_both_remainders_open(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "a", "new", 1, 300, holes=[(100, 200)])
    ingest(s, tmp_path / "a")
    batch(tmp_path / "b", "backfill", 120, 150, holes=[(130, 131)])
    ingest(s, tmp_path / "b")
    assert core(state_of(s))["holes"] == [[100, 119], [130, 131], [151, 200]]


def test_prefix_moves_the_start_back(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "a", "new", 500, 700)
    ingest(s, tmp_path / "a")
    batch(tmp_path / "b", "prefix", 250, 499, holes=[(300, 301)])
    batch(tmp_path / "b", "prefix", 100, 249)
    ingest(s, tmp_path / "b")
    report = state_of(s)
    assert core(report) == {"start_id": 100, "watermark": 700, "holes": [[300, 301]]}
    assert report["archived_trades"] == 601 - 2


def test_out_of_order_batch_counts_only_once_the_gap_is_stored(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "a", "new", 1, 300)
    batch(tmp_path / "a", "new", 601, 900)
    ingest(s, tmp_path / "a")
    report = state_of(s)
    assert core(report) == {"start_id": 1, "watermark": 300, "holes": []}
    assert [(b["lo"], b["status"]) for b in report["not_applied"]] == [(601, "OUT_OF_ORDER")]
    batch(tmp_path / "b", "new", 301, 600)
    ingest(s, tmp_path / "b")
    report = state_of(s)
    assert core(report) == {"start_id": 1, "watermark": 900, "holes": []} and report["not_applied"] == []
    assert report["archived_trades"] == 900


def test_overlapping_batch_is_stale_and_never_counted_twice(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "a", "new", 1, 300)
    ingest(s, tmp_path / "a")
    batch(tmp_path / "b", "new", 201, 400)  # a second export from an old state
    ingest(s, tmp_path / "b")
    report = state_of(s)
    assert core(report) == {"start_id": 1, "watermark": 300, "holes": []}
    assert [(b["lo"], b["status"]) for b in report["not_applied"]] == [(201, "STALE")]
    assert report["archived_trades"] == 300


def test_state_is_independent_of_how_batches_were_split_across_ingests(tmp_path):
    specs = [("new", 101, 200, [(110, 120)]), ("new", 201, 300, []), ("backfill", 110, 120, [(115, 115)]),
             ("prefix", 1, 100, [])]
    one = new_store(tmp_path / "one")
    for kind, lo, hi, holes in specs:
        batch(tmp_path / "all", kind, lo, hi, holes=holes)
    ingest(one, tmp_path / "all")  # name order puts backfill and prefix before new
    two = new_store(tmp_path / "two")
    for number, (kind, lo, hi, holes) in enumerate(specs):
        batch(tmp_path / f"run{number}", kind, lo, hi, holes=holes)
        ingest(two, tmp_path / f"run{number}")
    assert core(state_of(one)) == core(state_of(two)) == {"start_id": 1, "watermark": 300, "holes": [[115, 115]]}


# ----------------------------------------------------------------------- fail closed
def test_changed_stored_file_gives_no_state(tmp_path):
    s = new_store(tmp_path)
    stored = batch(tmp_path / "in", "new", 1, 100)
    ingest(s, tmp_path / "in")
    target = s.root / "batches" / SYMBOL / stored.name
    target.chmod(0o644)
    target.write_text(target.read_text().replace('"hi": 100', '"hi": 1000'))
    target.chmod(0o444)
    with pytest.raises(ArchiveSyncError, match="does not verify"):
        state_of(s)


def test_manifest_whose_batch_id_does_not_bind_its_holes_is_refused(tmp_path, monkeypatch):
    s = new_store(tmp_path)
    batch(tmp_path / "in", "new", 1, 100, batch_id="0" * 64)
    assert ingest(s, tmp_path / "in")["summary"] == {"FILE_INVALID": 1}  # ingest refuses it already
    # Defence in depth: a store filled by an older or faulty ingest still gives no state.
    monkeypatch.setattr(cold_store, "_check_batch", lambda path, manifest=None, symbol=None: (manifest, None))
    assert ingest(s, tmp_path / "in")["summary"] == {"STORED": 1}
    monkeypatch.undo()
    with pytest.raises(ArchiveSyncError, match="batch_id"):
        state_of(s)


def test_file_outside_the_ledger_gives_no_state(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "in", "new", 1, 100)
    ingest(s, tmp_path / "in")
    (s.root / "batches" / SYMBOL / "stray.csv.gz").write_bytes(b"x")
    with pytest.raises(ArchiveSyncError, match="does not verify"):
        state_of(s)


def test_running_writer_makes_state_fail_instead_of_reading_half_a_store(tmp_path):
    s = new_store(tmp_path)
    with s._locked(), pytest.raises(ArchiveSyncError, match="lock"):
        state_of(s)


def test_absent_or_wrong_volume_gives_no_state(tmp_path):
    volume = tmp_path / "vol"
    volume.mkdir()
    mounts = FakeMounts(volume)
    s = cold_store.ColdStore.init(volume / "store", volume_mount=volume, parent=tmp_path, is_mount=mounts, usage=ROOMY)
    batch(tmp_path / "in", "new", 1, 100)
    ingest(s, tmp_path / "in")
    assert core(state_of(s))["watermark"] == 100
    mounts.mounted.clear()
    with pytest.raises(ArchiveSyncError, match="not mounted"):
        state_of(s)


def test_interrupted_ingest_first_refuses_then_resumes_to_the_same_state(tmp_path, monkeypatch):
    volume = tmp_path / "vol"
    volume.mkdir()
    mounts = FakeMounts(volume)
    s = cold_store.ColdStore.init(volume / "store", volume_mount=volume, parent=tmp_path, is_mount=mounts, usage=ROOMY)
    batch(tmp_path / "in", "new", 1, 100)
    real = cold_store._copy_verified

    def copy_then_unmount(src, dst, sha, **kw):
        real(src, dst, sha, **kw)
        mounts.mounted.clear()

    monkeypatch.setattr(cold_store, "_copy_verified", copy_then_unmount)
    with pytest.raises(ArchiveSyncError, match="not mounted"):
        ingest(s, tmp_path / "in")
    monkeypatch.setattr(cold_store, "_copy_verified", real)
    mounts.mounted.add(str(volume.resolve()))
    with pytest.raises(ArchiveSyncError, match="does not verify"):  # data file on disk, not yet in the ledger
        state_of(s)
    assert ingest(s, tmp_path / "in")["summary"] == {"RESUMED": 1}
    assert core(state_of(s)) == {"start_id": 1, "watermark": 100, "holes": []}
    assert ingest(s, tmp_path / "in")["summary"] == {"ALREADY": 1}


def test_data_recorded_without_its_manifest_is_incomplete_not_archived(tmp_path, monkeypatch):
    s = new_store(tmp_path)
    batch(tmp_path / "in", "new", 1, 100)
    real = cold_store._copy_verified

    def fail_on_manifest(src, dst, sha, **kw):
        if str(dst).endswith(".manifest.json"):
            raise cold_store.SourceChanged("manifest changed after its check")
        return real(src, dst, sha, **kw)

    monkeypatch.setattr(cold_store, "_copy_verified", fail_on_manifest)
    assert ingest(s, tmp_path / "in")["halted"] == "FILE_INVALID"
    report = state_of(s)
    assert core(report) == {"start_id": None, "watermark": None, "holes": []}
    assert [b["status"] for b in report["not_applied"]] == ["INCOMPLETE"]
    monkeypatch.setattr(cold_store, "_copy_verified", real)
    assert ingest(s, tmp_path / "in")["summary"] == {"RESUMED": 1}
    assert core(state_of(s))["watermark"] == 100


def test_budget_stop_leaves_a_state_of_what_was_really_stored(tmp_path):
    batch(tmp_path / "in", "new", 1, 100)
    batch(tmp_path / "in", "new", 101, 200)
    one = sum(p.stat().st_size for p in (tmp_path / "in").glob(f"{SYMBOL}-new-{1:020d}-*"))
    s = new_store(tmp_path, limit=one + 10)
    assert ingest(s, tmp_path / "in")["halted"] == "BUDGET_STOP"
    report = state_of(s)
    assert core(report)["watermark"] == 100 and report["remaining_bytes"] == 10
    # The next export starts right after what is stored, nothing is skipped.
    assert exporter.plan_ranges(server_state=report, mac_cursor=200, mac_min=1, chunk=100) == [("new", 101, 200)]


def test_deep_check_passes_on_a_sound_store(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "in", "new", 1, 100, holes=[(5, 6)])
    ingest(s, tmp_path / "in")
    assert state_of(s, deep=True)["deep"] is True


def test_state_reads_only(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "in", "new", 1, 100)
    ingest(s, tmp_path / "in")
    before = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in s.root.rglob("*")}
    state_of(s, deep=True)
    assert {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in s.root.rglob("*")} == before


# ----------------------------------------------------------------------- migration and CLI
def test_migrated_store_gives_the_same_state(tmp_path):
    s = new_store(tmp_path)
    batch(tmp_path / "a", "new", 1, 300, holes=[(100, 200)])
    ingest(s, tmp_path / "a")
    batch(tmp_path / "b", "backfill", 100, 150)
    ingest(s, tmp_path / "b")
    receipt = cold_store.migrate_store(s.root, tmp_path / "new-disks")
    assert receipt["status"] == "OK"
    moved = cold_store.ColdStore(tmp_path / "new-disks")
    assert core(state_of(moved)) == core(state_of(s)) == {"start_id": 1, "watermark": 300, "holes": [[151, 200]]}


def test_cli_writes_a_state_file_the_export_command_reads(tmp_path, capsys):
    s = new_store(tmp_path)
    batch(tmp_path / "in", "new", 1, 100, holes=[(50, 50)])
    ingest(s, tmp_path / "in")
    out = tmp_path / "state.json"
    assert cli.main(["cold-state", "--root", str(s.root), "--symbol", SYMBOL, "--out", str(out), "--unbound-ok"]) == 0
    printed = json.loads(capsys.readouterr().out)
    written = json.loads(out.read_text())
    assert core(written) == core(printed) == {"start_id": 1, "watermark": 100, "holes": [[50, 50]]}
    assert written["symbol"] == SYMBOL
    args = cli.build_parser().parse_args(["export", "--symbol", SYMBOL, "--out", "x", "--server-state", str(out)])
    assert json.loads(Path(args.server_state).read_text())["watermark"] == 100


def test_cli_refuses_unbound_store_and_state_file_inside_the_store(tmp_path, capsys):
    s = new_store(tmp_path)
    assert cli.main(["cold-state", "--root", str(s.root), "--symbol", SYMBOL]) == 2
    assert "not bound" in capsys.readouterr().out
    inside = s.root / "state.json"
    assert cli.main(["cold-state", "--root", str(s.root), "--symbol", SYMBOL, "--out", str(inside), "--unbound-ok"]) == 2
    assert "inside the cold store" in capsys.readouterr().out and not inside.exists()


def test_cli_refuses_unsafe_symbol(tmp_path, capsys):
    s = new_store(tmp_path)
    assert cli.main(["cold-state", "--root", str(s.root), "--symbol", "../x", "--unbound-ok"]) == 2
    capsys.readouterr()


def test_store_root_through_a_symbolic_link_is_refused(tmp_path):
    s = new_store(tmp_path)
    link = tmp_path / "link"
    os.symlink(s.root, link)
    with pytest.raises(ArchiveSyncError):
        state_of(cold_store.ColdStore(link))
