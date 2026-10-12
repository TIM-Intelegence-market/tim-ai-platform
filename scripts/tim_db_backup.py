#!/usr/bin/env python3
"""Daily PostgreSQL backup and weekly restore test for the TIM server (OBSERVE only).

backup        pg_dump -Fc into the backup directory, sha256 next to it, prune old dumps
              (by age and by count; before the dump only as far as free space requires).
restore-test  restore the newest verified dump into a scratch database, compare row
              counts with the live database up to the dump's newest timestamp, drop it.

The password comes from TIM's secret provider and reaches the PostgreSQL tools only
through PGPASSWORD, never through argv or a log line.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

UTC = timezone.utc
DUMP_PATTERN = re.compile(r"^tim_(\d{8}T\d{6}Z)\.dump$")
REPORT_PATH = ROOT / "data/operational/restore_test.json"
BACKUP_REPORT_PATH = ROOT / "data/operational/backup_last_run.json"
# A new dump needs room for about the size of the previous one plus growth.
SPACE_FACTOR = 1.25
# Before a new dump exists, space pruning never goes below this many verified-or-not old dumps.
MIN_KEPT_BEFORE_DUMP = 2
STALE_TEMPORARY = timedelta(hours=6)
# (table, time column) pairs whose history only grows: rows are never deleted, but a gap backfill
# may insert older rows after the dump, so live counts up to a cutoff can exceed the dump's.
COMPARED_TABLES = (("candles", "open_time"), ("agg_trades", "trade_time"))


class BackupError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def connection_parts(database_url: str) -> dict[str, str]:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.username or not parsed.path.strip("/"):
        raise BackupError("database URL is not a PostgreSQL URL")
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.strip("/")),
    }


def pg_env(parts: dict[str, str]) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    env.update({"PGHOST": parts["host"], "PGPORT": parts["port"], "PGUSER": parts["user"]})
    if parts["password"]:
        env["PGPASSWORD"] = parts["password"]
    return env


def run_pg(command: list[str], parts: dict[str, str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, env=pg_env(parts), capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupError(f"{Path(command[0]).name} could not run") from exc
    if result.returncode != 0:
        # stderr of the PostgreSQL tools never contains PGPASSWORD; keep only the tail.
        raise BackupError(f"{Path(command[0]).name} failed: {result.stderr.strip()[-300:]}")
    return result


def dumps(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if DUMP_PATTERN.match(path.name))


def dump_time(path: Path) -> datetime:
    match = DUMP_PATTERN.match(path.name)
    if not match:
        raise BackupError(f"not a TIM dump: {path.name}")
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def remove_dump(path: Path) -> None:
    path.unlink()
    sidecar = path.with_name(path.name + ".sha256")
    if sidecar.exists():
        sidecar.unlink()


def prune(directory: Path, keep_days: int, now: datetime, keep_count: int | None = None) -> list[str]:
    """Delete TIM dumps older than keep_days or beyond the newest keep_count, but never the newest one."""
    removed: list[str] = []
    existing = dumps(directory)
    newest_first = list(reversed(existing))
    for rank, path in enumerate(newest_first):
        if rank == 0:
            continue
        too_old = now - dump_time(path) > timedelta(days=keep_days)
        too_many = keep_count is not None and rank >= keep_count
        if too_old or too_many:
            remove_dump(path)
            removed.append(path.name)
    return sorted(removed)


def free_bytes(directory: Path) -> int:
    return shutil.disk_usage(directory).free


def remove_stale_temporaries(directory: Path, now: datetime) -> list[str]:
    """pg_dump runs killed hard (OOM, power loss) leave .tim_dump.* behind; the unit is a oneshot."""
    removed: list[str] = []
    for path in directory.iterdir():
        if path.name.startswith(".tim_dump.") and path.is_file() and not path.is_symlink():
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if now - modified > STALE_TEMPORARY:
                path.unlink()
                removed.append(path.name)
    return sorted(removed)


def make_room(directory: Path) -> tuple[list[str], int, int]:
    """Free space for the next dump by deleting the oldest dumps, keeping MIN_KEPT_BEFORE_DUMP.

    Returns (removed, needed, free). Raises BackupError before pg_dump starts when even that is
    not enough, so a full disk fails fast with a readable reason instead of an ENOSPC mid-dump.
    """
    existing = dumps(directory)
    needed = int(existing[-1].stat().st_size * SPACE_FACTOR) if existing else 0
    removed: list[str] = []
    free = free_bytes(directory)
    while free < needed and len(existing) > MIN_KEPT_BEFORE_DUMP:
        oldest = existing.pop(0)
        remove_dump(oldest)
        removed.append(oldest.name)
        free = free_bytes(directory)
    if free < needed:
        raise BackupError(
            f"not enough space in {directory}: need about {needed // 2**20} MiB, free {free // 2**20} MiB, "
            f"{len(existing)} dumps kept"
        )
    return removed, needed, free


def backup(
    directory: Path,
    keep_days: int,
    parts: dict[str, str],
    *,
    keep_count: int | None = None,
    pg_dump: str = "pg_dump",
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    started = utc_now()
    stale = remove_stale_temporaries(directory, started)
    made_room, needed, free = make_room(directory)
    target = directory / f"tim_{stamp(started)}.dump"
    descriptor, temporary = tempfile.mkstemp(prefix=".tim_dump.", dir=directory)
    os.close(descriptor)
    try:
        run_pg([pg_dump, "--format=custom", "--no-owner", "--file", temporary, parts["database"]], parts, timeout=3600)
        os.chmod(temporary, 0o640)
        checksum = sha256_file(Path(temporary))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    target.with_name(target.name + ".sha256").write_text(f"{checksum}  {target.name}\n", encoding="utf-8")
    return {
        "status": "PASS",
        "command": "backup",
        "started_at": started.isoformat(),
        "completed_at": utc_now().isoformat(),
        "dump": str(target),
        "bytes": target.stat().st_size,
        "sha256": checksum,
        "pruned": sorted(made_room + prune(directory, keep_days, utc_now(), keep_count)),
        "pruned_for_space": made_room,
        "removed_temporaries": stale,
        "space_needed_bytes": needed,
        "space_free_before_bytes": free,
        "trading_actions": 0,
    }


def verified_newest(directory: Path) -> tuple[Path, str]:
    existing = dumps(directory)
    if not existing:
        raise BackupError(f"no TIM dump in {directory}")
    newest = existing[-1]
    sidecar = newest.with_name(newest.name + ".sha256")
    if not sidecar.is_file():
        raise BackupError(f"checksum file missing for {newest.name}")
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(newest)
    if actual != expected:
        raise BackupError(f"checksum mismatch for {newest.name}")
    return newest, actual


def scratch_name(main_database: str, scratch: str) -> str:
    if scratch == main_database or not scratch.endswith("_restore_test") or not re.fullmatch(r"[a-z_][a-z0-9_]*", scratch):
        raise BackupError("scratch database must be a separate *_restore_test name")
    return scratch


async def count_rows(database_url: str, cutoffs: dict[str, datetime | None] | None) -> dict[str, dict[str, Any]]:
    import asyncpg

    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=600)
    try:
        result: dict[str, dict[str, Any]] = {}
        for table, column in COMPARED_TABLES:
            if cutoffs is None:
                newest = await connection.fetchval(f"SELECT max({column}) FROM {table}")
            else:
                newest = cutoffs.get(table)
            count = 0
            if newest is not None:
                count = await connection.fetchval(f"SELECT count(*) FROM {table} WHERE {column} <= $1", newest)
            result[table] = {"cutoff": newest, "rows": int(count)}
        return result
    finally:
        await connection.close()


def with_database(database_url: str, database: str) -> str:
    parsed = urlsplit(database_url)
    return parsed._replace(path="/" + database).geturl()


def compare(restored: dict[str, dict[str, Any]], live: dict[str, dict[str, Any]]) -> dict[str, Any]:
    tables = {}
    for table, _ in COMPARED_TABLES:
        tables[table] = {
            "cutoff": restored[table]["cutoff"].isoformat() if restored[table]["cutoff"] else None,
            "restored_rows": restored[table]["rows"],
            "live_rows": live[table]["rows"],
            "match": restored[table]["rows"] == live[table]["rows"],
            # rows backfilled into the past after the dump; fewer live rows than restored is a loss
            "backfilled_after_dump": live[table]["rows"] - restored[table]["rows"],
        }
    empty = all(entry["restored_rows"] == 0 for entry in tables.values())
    passed = all(entry["backfilled_after_dump"] >= 0 for entry in tables.values()) and not empty
    return {"status": "PASS" if passed else "FAIL", "tables": tables, "empty_restore": empty}


def restore_test(
    directory: Path,
    scratch: str,
    database_url: str,
    parts: dict[str, str],
    *,
    tools: dict[str, str] | None = None,
) -> dict[str, Any]:
    tools = {"dropdb": "dropdb", "createdb": "createdb", "pg_restore": "pg_restore", **(tools or {})}
    scratch = scratch_name(parts["database"], scratch)
    dump, checksum = verified_newest(directory)
    run_pg([tools["dropdb"], "--if-exists", scratch], parts, timeout=300)
    run_pg([tools["createdb"], scratch], parts, timeout=300)
    try:
        run_pg([tools["pg_restore"], "--no-owner", "--exit-on-error", "--dbname", scratch, str(dump)], parts, timeout=7200)
        restored = asyncio.run(count_rows(with_database(database_url, scratch), None))
        live = asyncio.run(count_rows(database_url, {table: entry["cutoff"] for table, entry in restored.items()}))
    finally:
        run_pg([tools["dropdb"], "--if-exists", scratch], parts, timeout=300)
    result = compare(restored, live)
    return {
        **result,
        "command": "restore-test",
        "completed_at": utc_now().isoformat(),
        "dump": str(dump),
        "dump_sha256": checksum,
        "scratch_database_dropped": True,
        "trading_actions": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TIM PostgreSQL backup and restore test (OBSERVE only)")
    parser.add_argument("command", choices=("backup", "restore-test"))
    parser.add_argument("--dir", type=Path, default=Path("/var/backups/tim"))
    parser.add_argument("--keep-days", type=int, default=14)
    parser.add_argument("--keep-count", type=int, default=None,
                        help="keep at most this many dumps (the newest is always kept)")
    parser.add_argument("--scratch-db", default="tim_restore_test")
    args = parser.parse_args(argv)
    if args.keep_count is not None and args.keep_count < 1:
        parser.error("--keep-count must be at least 1")
    report_path = BACKUP_REPORT_PATH if args.command == "backup" else REPORT_PATH
    try:
        from config.settings import settings

        database_url = settings.database_url
        parts = connection_parts(database_url)
        if args.command == "backup":
            payload = backup(args.dir, args.keep_days, parts, keep_count=args.keep_count)
        else:
            payload = restore_test(args.dir, args.scratch_db, database_url, parts)
    except Exception as exc:  # fail closed and leave evidence, never a secret
        payload = {"status": "FAIL", "command": args.command, "reason": f"{type(exc).__name__}: {exc}"[:500],
                   "completed_at": utc_now().isoformat(), "trading_actions": 0}
    atomic_json(report_path, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
