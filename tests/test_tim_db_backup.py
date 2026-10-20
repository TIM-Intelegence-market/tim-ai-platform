"""scripts/tim_db_backup.py: dumps are checksummed and pruned, the password never reaches argv."""
from __future__ import annotations

import hashlib
import os
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import tim_db_backup as backup

UTC = timezone.utc
PARTS = {"host": "127.0.0.1", "port": "5432", "user": "tim", "password": "pw-not-in-argv", "database": "tim"}


def test_connection_parts_decodes_url() -> None:
    parts = backup.connection_parts("postgresql://tim:p%40ss@127.0.0.1:5433/tim?application_name=x")
    assert parts == {"host": "127.0.0.1", "port": "5433", "user": "tim", "password": "p@ss", "database": "tim"}
    with pytest.raises(backup.BackupError):
        backup.connection_parts("mysql://a@b/c")


def test_pg_env_carries_password_and_drops_foreign_pg_variables(monkeypatch) -> None:
    monkeypatch.setenv("PGSERVICE", "other")
    env = backup.pg_env(PARTS)
    assert env["PGPASSWORD"] == "pw-not-in-argv" and env["PGUSER"] == "tim"
    assert "PGSERVICE" not in env


def fake_tool(tmp_path: Path, name: str, body: str) -> str:
    path = tmp_path / name
    path.write_text(f"#!{sys.executable}\nimport os, sys\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def test_backup_writes_checksummed_dump_without_password_in_argv(tmp_path: Path) -> None:
    argv_log = tmp_path / "argv.txt"
    tool = fake_tool(tmp_path, "pg_dump", (
        f"open({str(argv_log)!r}, 'w').write(' '.join(sys.argv) + '|' + os.environ.get('PGPASSWORD', ''))\n"
        "out = sys.argv[sys.argv.index('--file') + 1]\n"
        "open(out, 'wb').write(b'PGDMP fake dump')"
    ))
    result = backup.backup(tmp_path / "backups", 14, PARTS, pg_dump=tool)
    dump = Path(result["dump"])
    assert result["status"] == "PASS" and dump.is_file()
    assert result["sha256"] == hashlib.sha256(b"PGDMP fake dump").hexdigest()
    assert (dump.parent / (dump.name + ".sha256")).read_text().split()[0] == result["sha256"]
    argv, password = argv_log.read_text().split("|")
    assert "pw-not-in-argv" not in argv and password == "pw-not-in-argv"
    assert not [path for path in dump.parent.iterdir() if path.name.startswith(".tim_dump.")]


def test_failed_pg_dump_leaves_no_partial_dump(tmp_path: Path) -> None:
    tool = fake_tool(tmp_path, "pg_dump", "sys.stderr.write('connection refused'); sys.exit(1)")
    with pytest.raises(backup.BackupError, match="connection refused"):
        backup.backup(tmp_path / "backups", 14, PARTS, pg_dump=tool)
    assert list((tmp_path / "backups").iterdir()) == []


def make_dump(directory: Path, when: datetime, content: bytes = b"x") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"tim_{backup.stamp(when)}.dump"
    path.write_bytes(content)
    path.with_name(path.name + ".sha256").write_text(f"{hashlib.sha256(content).hexdigest()}  {path.name}\n")
    return path


def test_prune_removes_old_dumps_but_keeps_the_newest_and_foreign_files(tmp_path: Path) -> None:
    now = datetime(2026, 10, 20, 3, 15, tzinfo=UTC)
    old = make_dump(tmp_path, now - timedelta(days=20))
    recent = make_dump(tmp_path, now - timedelta(days=2))
    foreign = tmp_path / "notes.txt"
    foreign.write_text("keep")
    assert backup.prune(tmp_path, 14, now) == [old.name]
    assert not old.exists() and recent.exists() and foreign.exists()
    lonely = tmp_path / "lonely"
    only = make_dump(lonely, now - timedelta(days=100))
    assert backup.prune(lonely, 14, now) == [] and only.exists()


def test_prune_by_count_keeps_the_newest_ones(tmp_path: Path) -> None:
    now = datetime(2026, 10, 20, 3, 15, tzinfo=UTC)
    made = [make_dump(tmp_path, now - timedelta(days=day)) for day in range(6)]
    removed = backup.prune(tmp_path, 14, now, keep_count=3)
    assert removed == sorted(path.name for path in made[3:])
    assert [path.exists() for path in made] == [True, True, True, False, False, False]
    assert backup.prune(tmp_path, 14, now, keep_count=1) == sorted(path.name for path in made[1:3])
    assert made[0].exists()


def fake_free(monkeypatch, start: int, per_removed: int, directory: Path) -> None:
    """Free space grows by per_removed for each dump that disappeared since the call started."""
    initial = len(backup.dumps(directory))
    monkeypatch.setattr(backup, "free_bytes", lambda path: start + per_removed * (initial - len(backup.dumps(path))))


def test_make_room_deletes_oldest_until_the_next_dump_fits(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 10, 12, 3, 15, tzinfo=UTC)
    made = [make_dump(tmp_path, now - timedelta(days=day), b"y" * 100) for day in range(5)]
    fake_free(monkeypatch, 10, 100, tmp_path)
    removed, needed, free = backup.make_room(tmp_path)
    assert needed == 125 and free >= needed
    assert removed == [made[4].name, made[3].name]
    assert all(path.exists() for path in made[:3])


def test_make_room_fails_fast_and_keeps_two_dumps(tmp_path: Path, monkeypatch) -> None:
    now = datetime(2026, 10, 12, 3, 15, tzinfo=UTC)
    made = [make_dump(tmp_path, now - timedelta(days=day), b"y" * 100) for day in range(4)]
    fake_free(monkeypatch, 0, 10, tmp_path)
    with pytest.raises(backup.BackupError, match="not enough space"):
        backup.make_room(tmp_path)
    assert [path.exists() for path in made] == [True, True, False, False]


def test_full_disk_never_starts_pg_dump(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "backups"
    now = datetime(2026, 10, 12, 3, 15, tzinfo=UTC)
    make_dump(directory, now - timedelta(days=1), b"y" * 100)
    marker = tmp_path / "ran"
    tool = fake_tool(tmp_path, "pg_dump", f"open({str(marker)!r}, 'w').write('x')")
    monkeypatch.setattr(backup, "free_bytes", lambda path: 0)
    with pytest.raises(backup.BackupError, match="not enough space"):
        backup.backup(directory, 14, PARTS, pg_dump=tool)
    assert not marker.exists()


def test_backup_prunes_by_count_and_removes_stale_temporaries(tmp_path: Path) -> None:
    directory = tmp_path / "backups"
    now = backup.utc_now()
    made = [make_dump(directory, now - timedelta(days=day + 1)) for day in range(4)]
    stale = directory / ".tim_dump.abc123"
    stale.write_bytes(b"partial")
    old = (now - timedelta(hours=7)).timestamp()
    os.utime(stale, (old, old))
    fresh = directory / ".tim_dump.fresh1"
    fresh.write_bytes(b"other run")
    tool = fake_tool(tmp_path, "pg_dump", "open(sys.argv[sys.argv.index('--file') + 1], 'wb').write(b'PGDMP new')")
    result = backup.backup(directory, 14, PARTS, keep_count=3, pg_dump=tool)
    assert result["status"] == "PASS"
    assert result["removed_temporaries"] == [stale.name] and fresh.exists() and not stale.exists()
    assert result["pruned"] == sorted(path.name for path in made[2:])
    assert len(backup.dumps(directory)) == 3


def test_main_rejects_keep_count_below_one() -> None:
    with pytest.raises(SystemExit):
        backup.main(["backup", "--keep-count", "0"])


def test_backup_unit_caps_the_number_of_dumps() -> None:
    unit = (Path(backup.ROOT) / "ops/systemd/tim-backup.service").read_text()
    assert "--keep-count 3" in unit


def test_verified_newest_rejects_tampered_dump(tmp_path: Path) -> None:
    now = datetime(2026, 10, 20, tzinfo=UTC)
    make_dump(tmp_path, now - timedelta(days=1), b"older")
    newest = make_dump(tmp_path, now, b"newest")
    assert backup.verified_newest(tmp_path)[0] == newest
    newest.write_bytes(b"tampered")
    with pytest.raises(backup.BackupError, match="checksum mismatch"):
        backup.verified_newest(tmp_path)
    with pytest.raises(backup.BackupError, match="no TIM dump"):
        backup.verified_newest(tmp_path / "empty")


@pytest.mark.parametrize("name", ["tim", "postgres", "tim_test", "x; DROP DATABASE tim_restore_test", "TIM_restore_test"])
def test_scratch_database_name_is_guarded(name: str) -> None:
    with pytest.raises(backup.BackupError):
        backup.scratch_name("tim", name)
    assert backup.scratch_name("tim", "tim_restore_test") == "tim_restore_test"


def test_compare_requires_non_empty_restore_without_lost_rows() -> None:
    cutoff = datetime(2026, 10, 1, tzinfo=UTC)
    restored = {"candles": {"cutoff": cutoff, "rows": 10}, "agg_trades": {"cutoff": cutoff, "rows": 99}}
    assert backup.compare(restored, restored)["status"] == "PASS"
    backfilled = backup.compare(restored, {**restored, "candles": {"cutoff": cutoff, "rows": 13}})
    assert backfilled["status"] == "PASS"
    assert backfilled["tables"]["candles"]["backfilled_after_dump"] == 3
    assert backfilled["tables"]["candles"]["match"] is False
    assert backup.compare(restored, {**restored, "candles": {"cutoff": cutoff, "rows": 9}})["status"] == "FAIL"
    empty = {"candles": {"cutoff": None, "rows": 0}, "agg_trades": {"cutoff": None, "rows": 0}}
    assert backup.compare(empty, empty)["status"] == "FAIL"


def test_restore_test_always_drops_the_scratch_database(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "calls.txt"
    record = f"open({str(log)!r}, 'a').write(os.path.basename(sys.argv[0]) + ' ' + ' '.join(sys.argv[1:]) + '\\n')"
    tools = {
        "dropdb": fake_tool(tmp_path, "dropdb", record),
        "createdb": fake_tool(tmp_path, "createdb", record),
        "pg_restore": fake_tool(tmp_path, "pg_restore", record + "\nsys.exit(1)"),
        "psql": fake_tool(tmp_path, "psql", "print(100)"),
    }
    monkeypatch.setattr(backup, "free_bytes", lambda path: 20 * 2**30)
    make_dump(tmp_path / "backups", datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(backup.BackupError, match="pg_restore failed"):
        backup.restore_test(tmp_path / "backups", "tim_restore_test", "postgresql://tim@127.0.0.1/tim", PARTS,
                            tools=tools, storage_path=tmp_path)
    calls = log.read_text().splitlines()
    assert calls[0].startswith("dropdb") and calls[1].startswith("createdb") and calls[-1].startswith("dropdb")
    assert all("pw-not-in-argv" not in call for call in calls)


def test_restore_checks_database_disk_before_any_scratch_mutation(tmp_path: Path, monkeypatch) -> None:
    """A tiny dump and ample backup-disk space must not permit a full database disk."""
    directory = tmp_path / "backups"
    database_disk = tmp_path / "postgresql-volume"
    database_disk.mkdir()
    dump = make_dump(directory, datetime(2026, 10, 1, tzinfo=UTC), b"small compressed dump")
    calls = []
    tool = fake_tool(tmp_path, "psql", "print(50 * 2**30)")
    def free(path):
        calls.append(path)
        return (30 if path == database_disk else 200) * 2**30
    monkeypatch.setattr(backup, "free_bytes", free)
    marker = tmp_path / "scratch-was-touched"
    mutation = fake_tool(tmp_path, "mutation", f"open({str(marker)!r}, 'w').write('unsafe')")
    with pytest.raises(backup.BackupError, match="not enough restore space") as error:
        backup.restore_test(directory, "tim_restore_test", "postgresql://tim@127.0.0.1/tim", PARTS,
                            tools={"psql": tool, "dropdb": mutation, "createdb": mutation, "pg_restore": mutation},
                            storage_path=database_disk)
    assert calls == [database_disk]
    assert not marker.exists() and dump.exists()
    space = error.value.evidence["restore_space"]
    assert space["status"] == "FAIL" and space["source_database_bytes"] == 50 * 2**30
    assert space["space_needed_bytes"] == 108 * 2**30


def test_restore_space_keeps_live_reserve_at_boundary(tmp_path: Path, monkeypatch) -> None:
    tool = fake_tool(tmp_path, "psql", "print(10 * 2**30)")
    needed = 28 * 2**30
    monkeypatch.setattr(backup, "free_bytes", lambda path: needed - 1)
    with pytest.raises(backup.BackupError, match="including live reserve"):
        backup.restore_space_check(PARTS, tmp_path, psql=tool)
    monkeypatch.setattr(backup, "free_bytes", lambda path: needed)
    assert backup.restore_space_check(PARTS, tmp_path, psql=tool)["status"] == "PASS"


@pytest.mark.parametrize("size", ["unknown", "0", "-100"])
def test_restore_refuses_unknown_or_invalid_source_size(tmp_path: Path, size: str) -> None:
    tool = fake_tool(tmp_path, "psql", f"print({size!r})")
    with pytest.raises(backup.BackupError, match="database size"):
        backup.restore_space_check(PARTS, tmp_path, psql=tool)


def test_restore_requires_explicit_local_storage_path_before_pg_call(tmp_path: Path) -> None:
    for path in (None, Path("relative"), tmp_path / "missing"):
        with pytest.raises(backup.BackupError, match="restore-storage-path"):
            backup.restore_space_check(PARTS, path, psql="must-not-run")
    with pytest.raises(backup.BackupError, match="local PostgreSQL"):
        backup.restore_space_check({**PARTS, "host": "remote.example"}, tmp_path, psql="must-not-run")


def test_main_writes_fail_report_without_secret(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(backup, "BACKUP_REPORT_PATH", tmp_path / "report.json")
    monkeypatch.setenv("TIM_DATABASE_SECRET_PROVIDER", "file")
    monkeypatch.setenv("TIM_DATABASE_SECRET_FILE", str(tmp_path / "missing"))
    assert backup.main(["backup", "--dir", str(tmp_path / "b")]) == 2
    report = (tmp_path / "report.json").read_text()
    assert '"status": "FAIL"' in report
