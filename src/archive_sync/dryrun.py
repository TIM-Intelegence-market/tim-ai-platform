"""S2 dry run of the archive sync: one real trading day into a throwaway PostgreSQL 18.

Run by hand only. The source (Mac database) is opened with ``default_transaction_read_only=on``
and only read inside snapshots. The target must be a throwaway database whose name starts with
``archive_dryrun``; every write goes there. The production server is never contacted here.

    python -m src.archive_sync.dryrun --day 2026-11-22 --work DIR --report report.json
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import os
import random
import resource
import shutil
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.archive_sync import exporter, health, importer, transfer
from src.archive_sync.common import COLUMNS, ArchiveSyncError, batch_id_for, sha256_file

SYMBOL = "BTCUSDT"
ROOT = Path(__file__).resolve().parents[2]


def _usage() -> dict[str, float]:
    own, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    scale = 1 if sys.platform == "darwin" else 1024  # macOS reports bytes, Linux kilobytes
    return {
        "cpu_user_s": own.ru_utime + kids.ru_utime,
        "cpu_system_s": own.ru_stime + kids.ru_stime,
        "max_rss_mb_self": own.ru_maxrss * scale / 2**20,
        "max_rss_mb_children": kids.ru_maxrss * scale / 2**20,
    }


class Step:
    def __init__(self, report: dict[str, Any], name: str) -> None:
        self.report, self.name, self.data = report, name, {}

    def __enter__(self) -> dict[str, Any]:
        self.t0, self.u0 = time.monotonic(), _usage()
        return self.data

    def __exit__(self, kind, error, _tb) -> bool:
        u1 = _usage()
        self.data["seconds"] = round(time.monotonic() - self.t0, 3)
        self.data["cpu_s"] = round(
            (u1["cpu_user_s"] - self.u0["cpu_user_s"]) + (u1["cpu_system_s"] - self.u0["cpu_system_s"]), 3
        )
        self.data["max_rss_mb_so_far"] = round(max(u1["max_rss_mb_self"], u1["max_rss_mb_children"]), 1)
        if error is not None:
            self.data["passed"] = False
            self.data["error"] = f"{type(error).__name__}: {error}"
        else:
            self.data.setdefault("passed", True)
        self.report["steps"][self.name] = self.data
        print(f"[{self.name}] passed={self.data['passed']} {self.data['seconds']}s", flush=True)
        # Record the failure and go on with the next step; the report says which step failed.
        return kind is not None and issubclass(kind, Exception)


def _check(condition: bool, text: str) -> None:
    if not condition:
        raise AssertionError(text)


async def _connect(env_name: str, *, read_only: bool) -> Any:
    import asyncpg

    url = os.environ.get(env_name, "").strip()
    if not url:
        raise ArchiveSyncError(f"{env_name} is not set")
    settings = {"default_transaction_read_only": "on"} if read_only else {}
    return await asyncpg.connect(url, server_settings=settings)


async def _guard_target(connection: Any) -> dict[str, Any]:
    row = await connection.fetchrow(
        "SELECT current_database() AS db, inet_server_port() AS port, current_setting('server_version_num')::int AS v"
    )
    _check(str(row["db"]).startswith("archive_dryrun"), "target database must be a throwaway archive_dryrun*")
    minimum = 160000 if os.environ.get("TIM_DRYRUN_ALLOW_PG16_SMOKE") == "1" else 180000
    _check(int(row["v"]) >= minimum, "target must be PostgreSQL 18 or newer")
    _check(int(row["port"]) != 5432, "target must not run on the production port")
    return {"database": row["db"], "port": row["port"], "server_version_num": row["v"]}


async def _day_range(source: Any, day: date) -> tuple[int, int]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    async with source.transaction(isolation="repeatable_read", readonly=True):
        await source.execute("SET LOCAL statement_timeout = 120000")
        lo = await source.fetchval(
            """SELECT aggregate_trade_id FROM agg_trades WHERE symbol=$1 AND trade_time >= $2
               ORDER BY trade_time, aggregate_trade_id LIMIT 1""",
            SYMBOL,
            start,
        )
        hi = await source.fetchval(
            """SELECT aggregate_trade_id FROM agg_trades WHERE symbol=$1 AND trade_time < $2
               ORDER BY trade_time DESC, aggregate_trade_id DESC LIMIT 1""",
            SYMBOL,
            start + timedelta(days=1),
        )
    _check(lo is not None and hi is not None and hi >= lo, "no trades for that day on the source")
    return int(lo), int(hi)


async def _ids(connection: Any, table: str, lo: int, hi: int) -> list[int]:
    rows = await connection.fetch(
        f"SELECT aggregate_trade_id FROM {table} WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3 ORDER BY 1",
        SYMBOL,
        lo,
        hi,
    )
    return [int(r[0]) for r in rows]


def _env_for_child() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("TIM_ARCHIVE_SOURCE_URL", None)
    env["PYTHONPATH"] = str(ROOT)
    return env


def _import_cmd(directory: Path, schema: str, gate: Path) -> list[str]:
    return [sys.executable, "-I", "-c",
            "import sys; sys.path.insert(0, %r); from src.archive_sync.__main__ import main; sys.exit(main(sys.argv[1:]))"
            % str(ROOT),
            "import", "--symbol", SYMBOL, "--dir", str(directory), "--schema", schema, "--gate-path", str(gate)]


async def _invariants(target: Any, schema: str) -> dict[str, Any]:
    """After any interruption: every accepted batch is complete, nothing else is in the archive."""
    exists = await target.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.batches")
    if not exists:
        return {"accepted": 0, "rows": 0, "consistent": True}
    accepted = await target.fetchval(
        f"SELECT coalesce(sum(row_count),0) FROM {schema}.batches WHERE status='ACCEPTED'"
    )
    rows = await target.fetchval(f"SELECT count(*) FROM {schema}.agg_trades")
    orphans = await target.fetchval(
        f"""SELECT count(*) FROM {schema}.agg_trades a JOIN {schema}.batches b USING (batch_id)
            WHERE b.status <> 'ACCEPTED'"""
    )
    return {"accepted_rows": int(accepted), "rows": int(rows), "consistent": int(accepted) == int(rows) and orphans == 0}


def _rewrite(src_manifest: Path, dst_dir: Path, mutate) -> Path:
    manifest = json.loads(src_manifest.read_text())
    csv = mutate(gzip.decompress((src_manifest.parent / manifest["file"]).read_bytes()))
    dst_dir.mkdir(parents=True, exist_ok=True)
    data = dst_dir / manifest["file"]
    data.write_bytes(gzip.compress(csv, mtime=0))
    manifest.update(
        file_bytes=data.stat().st_size, file_sha256=sha256_file(data), csv_bytes=len(csv),
        content_sha256=hashlib.sha256(csv).hexdigest(), row_count=csv.count(b"\n"),
    )
    manifest["batch_id"] = batch_id_for(manifest["kind"], manifest["symbol"], manifest["lo"], manifest["hi"],
                                        manifest["content_sha256"], manifest["holes"])
    path = dst_dir / src_manifest.name
    path.write_text(json.dumps(manifest))
    return path


async def run(day: date, work: Path, chunk: int) -> dict[str, Any]:
    report: dict[str, Any] = {"mode": "DRY_RUN_S2", "day": day.isoformat(), "symbol": SYMBOL, "steps": {},
                              "started_at": datetime.now(timezone.utc).isoformat(), "cpu_count": os.cpu_count()}
    out, inbox, gate = work / "out", work / "inbox", work
    for path in (out, inbox):
        path.mkdir(parents=True, exist_ok=True)
        _check(not any(path.iterdir()), f"{path} must be empty")
    source = await _connect("TIM_ARCHIVE_SOURCE_URL", read_only=True)
    target = await _connect("TIM_ARCHIVE_TARGET_URL", read_only=False)
    try:
        with Step(report, "00_guards") as s:
            s["target"] = await _guard_target(target)
            s["source_read_only"] = await source.fetchval("SHOW default_transaction_read_only")
            _check(s["source_read_only"] == "on", "source must be read-only")
            s["source_server_version_num"] = int(await source.fetchval("SHOW server_version_num"))
        lo, hi = await _day_range(source, day)
        report["id_range"] = [lo, hi]

        with Step(report, "02_export_day") as s:
            result = await exporter.export_batches(
                source, symbol=SYMBOL, out_dir=out, server_state={"symbol": SYMBOL, "watermark": None, "holes": []},
                chunk=chunk, max_batches=100, id_window=(lo, hi),
            )
            s["batches"] = len(result["batches"])
            s["rows"] = sum(b["row_count"] for b in result["batches"])
            s["files_bytes"] = sum(p.stat().st_size for p in out.iterdir())
            manifests = sorted(out.glob("*.manifest.json"))
            s["holes"] = sum(len(json.loads(p.read_text())["holes"]) for p in manifests)
            _check(result["batches"][-1]["hi"] == hi, "export did not reach the end of the day")

        with Step(report, "05_transfer_with_dropped_connection") as s:
            class Flaky(transfer.LocalDirTarget):
                dropped = 0

                def upload(self, local, name):
                    if Flaky.dropped == 0 and name.endswith(".csv.gz") and local != sorted(out.glob("*.csv.gz"))[0]:
                        Flaky.dropped = 1
                        (self.root / (name + ".part")).write_bytes(local.read_bytes()[: local.stat().st_size // 2])
                        raise ArchiveSyncError("simulated connection drop")
                    super().upload(local, name)

            target_dir = Flaky(inbox)
            try:
                transfer.transfer_directory(out, target_dir, symbol=SYMBOL, attempts=1, sleep=lambda _s: None)
                raise AssertionError("drop was not simulated")
            except ArchiveSyncError:
                s["first_attempt"] = "dropped"
            partial = await importer.import_directory(target, inbox, symbol=SYMBOL, gate_path=gate, schema="archive_partial")
            s["import_after_drop"] = partial["summary"]
            s["invariants_after_drop"] = await _invariants(target, "archive_partial")
            _check(s["invariants_after_drop"]["consistent"], "half transfer left an inconsistent archive")
            again = transfer.transfer_directory(out, target_dir, symbol=SYMBOL, sleep=lambda _s: None)
            s["resume"] = {"sent": len(again["sent"]), "skipped": again["skipped_already_present"]}
            for path in out.iterdir():
                _check(sha256_file(path) == sha256_file(inbox / path.name), f"{path.name} differs after transfer")
            s["leftover_part_files"] = len(list(inbox.glob("*.part")))

        with Step(report, "04_import_three_times") as s:
            runs, durations = [], []
            for _ in range(3):
                t0 = time.monotonic()
                result = await importer.import_directory(target, inbox, symbol=SYMBOL, gate_path=gate, schema="archive_mac")
                durations.append(round(time.monotonic() - t0, 3))
                runs.append(result["summary"])
            s["run_seconds"] = durations
            s["runs"] = runs
            total = await target.fetchval("SELECT count(*) FROM archive_mac.agg_trades")
            distinct = await target.fetchval("SELECT count(DISTINCT aggregate_trade_id) FROM archive_mac.agg_trades")
            s["rows"], s["distinct_ids"] = int(total), int(distinct)
            _check(runs[0] == {"ACCEPTED": report["steps"]["02_export_day"]["batches"]}, "first run not all accepted")
            _check(all(r == {"ALREADY_ACCEPTED": runs[0]["ACCEPTED"]} for r in runs[1:]), "re-import was not a no-op")
            _check(total == distinct == report["steps"]["02_export_day"]["rows"], "duplicates or missing rows")

        with Step(report, "03_compare_ids_values_hashes") as s:
            src_digest = await health.range_digest(source, table="agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
            dst_digest = await health.range_digest(target, table="archive_mac.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
            async with source.transaction(isolation="repeatable_read", readonly=True):
                src_ids = await _ids(source, "agg_trades", lo, hi)
            dst_ids = await _ids(target, "archive_mac.agg_trades", lo, hi)
            s["source"], s["archive"] = src_digest, dst_digest
            s["ids_equal"] = src_ids == dst_ids
            s["missing_on_source_in_range"] = (hi - lo + 1) - len(src_ids)
            _check(s["ids_equal"] and src_digest["sha256"] == dst_digest["sha256"], "source and archive differ")
            check = await health.archive_health(target, symbol=SYMBOL, schema="archive_mac", verify_last=100)
            s["health"] = {k: check[k] for k in ("status", "problems", "warnings")}
            _check(check["status"] in ("OK", "WARN"), "archive health failed")

        with Step(report, "06_process_crash_during_import") as s:
            kills = []
            full = report["steps"]["04_import_three_times"]["run_seconds"][0] + 0.7  # + interpreter start
            for delay in [round(full * f, 2) for f in (0.1, 0.3, 0.5, 0.65, 0.8, 0.95)]:
                child = subprocess.Popen(_import_cmd(inbox, "archive_crash", gate), env=_env_for_child(),
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(delay)
                finished = child.poll() is not None
                if not finished:
                    child.send_signal(signal.SIGKILL)
                child.wait()
                await asyncio.sleep(0.5)  # let the server notice the dead backend and roll back
                state = await _invariants(target, "archive_crash")
                kills.append({"after_s": delay, "killed": not finished, **state})
                _check(state["consistent"], f"inconsistent archive after kill at {delay}s")
            final = subprocess.run(_import_cmd(inbox, "archive_crash", gate), env=_env_for_child(),
                                   capture_output=True, text=True, timeout=1800)
            s["kills"] = kills
            s["final_exit"] = final.returncode
            digest = await health.range_digest(target, table="archive_crash.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
            s["final_matches_source"] = digest["sha256"] == src_digest["sha256"]
            s["kills_after_a_committed_batch"] = sum(1 for k in kills if k["killed"] and k["accepted_rows"] > 0)
            _check(final.returncode == 0 and s["final_matches_source"], "archive after crashes differs from source")

        with Step(report, "07_conflicting_and_corrupt_batches") as s:
            first = sorted(inbox.glob("*.manifest.json"))[0]
            cases = {}
            bad = work / "bad-truncated"
            bad.mkdir()
            for path in (first, first.parent / json.loads(first.read_text())["file"]):
                shutil.copy(path, bad / path.name)
            data = bad / json.loads(first.read_text())["file"]
            data.write_bytes(data.read_bytes()[:-100])
            cases["truncated_file"] = (await importer.import_directory(target, bad, symbol=SYMBOL, gate_path=gate,
                                                                       schema="archive_mac"))["summary"]

            def change_price(csv: bytes) -> bytes:
                lines = csv.splitlines(keepends=True)
                fields = lines[10].split(b",")
                fields[3] = repr(float(fields[3]) + 0.01).encode()
                lines[10] = b",".join(fields)
                return b"".join(lines)

            conflict = _rewrite(first, work / "bad-conflict", change_price)
            cases["changed_price_vs_archive"] = (await importer.import_directory(
                target, conflict.parent, symbol=SYMBOL, gate_path=gate, schema="archive_mac"))["summary"]

            def duplicate(csv: bytes) -> bytes:
                lines = csv.splitlines(keepends=True)
                return b"".join(lines[:2] + [lines[1]] + lines[3:])

            dup = _rewrite(first, work / "bad-duplicate", duplicate)
            cases["duplicate_id_fresh_archive"] = (await importer.import_directory(
                target, dup.parent, symbol=SYMBOL, gate_path=gate, schema="archive_bad"))["summary"]
            s["cases"] = cases
            after = await health.range_digest(target, table="archive_mac.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
            s["archive_unchanged"] = after["sha256"] == src_digest["sha256"]
            s["archive_bad_rows"] = int(await target.fetchval("SELECT count(*) FROM archive_bad.agg_trades"))
            _check(cases["truncated_file"] == {"FILE_INVALID": 1}, "truncated file not rejected")
            _check(cases["changed_price_vs_archive"] == {"QUARANTINED": 1}, "price conflict not quarantined")
            _check(cases["duplicate_id_fresh_archive"] == {"QUARANTINED": 1}, "duplicate not quarantined")
            _check(s["archive_unchanged"] and s["archive_bad_rows"] == 0, "a faulty batch released rows")

        with Step(report, "08_late_trades_below_watermark") as s:
            await target.execute("CREATE SCHEMA sim_src")
            await target.execute(
                """CREATE TABLE sim_src.agg_trades (symbol TEXT, aggregate_trade_id BIGINT, trade_time TIMESTAMPTZ,
                   price DOUBLE PRECISION, quantity DOUBLE PRECISION, buyer_is_maker BOOLEAN, source TEXT,
                   ingest_timestamp TIMESTAMPTZ, PRIMARY KEY (symbol, aggregate_trade_id))"""
            )
            await target.execute(
                """CREATE TABLE sim_src.ingestion_cursors (source TEXT, market TEXT, symbol TEXT, data_type TEXT,
                   last_aggregate_trade_id BIGINT)"""
            )
            await target.execute(
                f"INSERT INTO sim_src.agg_trades SELECT {', '.join(COLUMNS)} FROM archive_mac.agg_trades"
            )
            await target.execute("INSERT INTO sim_src.ingestion_cursors VALUES ('BINANCE','SPOT',$1,'AGG_TRADE',$2)",
                                 SYMBOL, hi)
            rng = random.Random(20261124)
            middle = lo + (hi - lo) // 2
            withheld = sorted(set(rng.sample(range(lo + 1, hi), 25)) | set(range(middle, middle + 1000)))
            await target.execute(
                "CREATE TABLE sim_src.withheld AS SELECT * FROM sim_src.agg_trades WHERE aggregate_trade_id = ANY($1::bigint[])",
                withheld,
            )
            await target.execute("DELETE FROM sim_src.agg_trades WHERE aggregate_trade_id = ANY($1::bigint[])", withheld)
            sim_out = work / "sim-out"
            state0 = {"symbol": SYMBOL, "watermark": None, "holes": []}
            await exporter.export_batches(target, symbol=SYMBOL, out_dir=sim_out, server_state=state0,
                                          source_schema="sim_src", chunk=chunk, max_batches=100, id_window=(lo, hi))
            first_import = await importer.import_directory(target, sim_out, symbol=SYMBOL, gate_path=gate,
                                                           schema="archive_late")
            s["holes_after_first_import"] = len(first_import["state"]["holes"])
            s["withheld_trades"] = len(withheld)
            # The source "recovers" the trades later; the archive watermark is already past them.
            await target.execute("INSERT INTO sim_src.agg_trades SELECT * FROM sim_src.withheld")
            state1 = await importer.server_state(target, SYMBOL, "archive_late")
            backfill = await exporter.export_batches(target, symbol=SYMBOL, out_dir=sim_out, server_state=state1,
                                                     source_schema="sim_src", chunk=chunk, max_batches=100,
                                                     id_window=(lo, hi))
            s["backfill_batches"] = len(backfill["batches"])
            second = await importer.import_directory(target, sim_out, symbol=SYMBOL, gate_path=gate, schema="archive_late")
            s["holes_after_backfill"] = second["state"]["holes"]
            digest = await health.range_digest(target, table="archive_late.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
            s["matches_source_day"] = digest["sha256"] == src_digest["sha256"]
            _check(s["holes_after_first_import"] > 0 and s["matches_source_day"], "late trades were lost")
            _check(len(s["holes_after_backfill"]) == report["steps"]["02_export_day"]["holes"] or not s["holes_after_backfill"],
                   "unexpected holes remain")

        with Step(report, "09_concurrent_imports_and_writer") as s:
            children = [subprocess.Popen(_import_cmd(inbox, "archive_conc", gate), env=_env_for_child(),
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(3)]
            await asyncio.sleep(0.3)
            rogue = {"inserted": False, "error": None}
            try:
                await importer.ensure_schema(target, "archive_conc")
                async with target.transaction():
                    await target.execute(
                        """INSERT INTO archive_conc.batches (batch_id, kind, symbol, lo_id, hi_id, row_count, holes,
                           content_sha256, file_sha256, status, reason, manifest)
                           VALUES (repeat('f',64),'new',$1,$2,$2,1,'[]','x','x','STALE','rogue writer','{}')
                           ON CONFLICT DO NOTHING""",
                        SYMBOL, hi,
                    )
                    tag = await target.execute(
                        f"""INSERT INTO archive_conc.agg_trades ({', '.join(COLUMNS)}, batch_id)
                            SELECT symbol, aggregate_trade_id, trade_time, price + 1, quantity, buyer_is_maker, source,
                                   ingest_timestamp, repeat('f',64) FROM archive_mac.agg_trades
                            WHERE aggregate_trade_id = $1 ON CONFLICT DO NOTHING""",
                        hi,
                    )
                    rogue["inserted"] = tag.endswith(" 1")
            except Exception as error:  # noqa: BLE001 - the race may legitimately fail either way
                rogue["error"] = type(error).__name__
            outputs = [child.communicate(timeout=1800) for child in children]
            s["exit_codes"] = [child.returncode for child in children]
            s["rogue_writer"] = rogue
            statuses = await target.fetch(
                "SELECT status, count(*) AS n FROM archive_conc.batches GROUP BY status ORDER BY status"
            )
            s["batches_by_status"] = {r["status"]: int(r["n"]) for r in statuses}
            check = await health.archive_health(target, symbol=SYMBOL, schema="archive_conc", verify_last=100)
            s["accepted_batches_verify"] = all(v["ok"] for v in check["verified_batches"])
            dup = await target.fetchval(
                "SELECT count(*) - count(DISTINCT aggregate_trade_id) FROM archive_conc.agg_trades"
            )
            s["duplicate_rows"] = int(dup)
            s["child_summaries"] = [json.loads(o[0]).get("summary") if o[0].strip().startswith("{") else o[0][-200:]
                                    for o in outputs]
            _check(s["accepted_batches_verify"] and dup == 0, "concurrent import produced a bad archive")
            accepted = s["batches_by_status"].get("ACCEPTED", 0)
            batches = report["steps"]["02_export_day"]["batches"]
            if rogue["inserted"]:
                _check(s["batches_by_status"].get("QUARANTINED", 0) >= 1, "rogue row was not detected")
            else:
                _check(accepted == batches, "not all batches accepted without a rogue row")

        with Step(report, "10_backup_and_restore") as s:
            pg_bin = Path(os.environ.get("TIM_DRYRUN_PG_BIN", "/Library/PostgreSQL/18/bin"))
            url = os.environ["TIM_ARCHIVE_TARGET_URL"]
            dump = work / "archive_mac.dump"
            subprocess.run([str(pg_bin / "pg_dump"), "-Fc", "-n", "archive_mac", "-f", str(dump), url], check=True,
                           capture_output=True)
            s["dump_bytes"] = dump.stat().st_size
            s["dump_sha256"] = sha256_file(dump)
            await target.execute("CREATE DATABASE archive_dryrun_restore")
            restore_url = url.rsplit("/", 1)[0] + "/archive_dryrun_restore"
            subprocess.run([str(pg_bin / "pg_restore"), "--no-owner", "-d", restore_url, str(dump)], check=True,
                           capture_output=True)
            import asyncpg

            restored = await asyncpg.connect(restore_url)
            try:
                digest = await health.range_digest(restored, table="archive_mac.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
                check = await health.archive_health(restored, symbol=SYMBOL, schema="archive_mac", verify_last=100)
            finally:
                await restored.close()
            s["restore_matches_source"] = digest["sha256"] == src_digest["sha256"]
            original = await health.archive_health(target, symbol=SYMBOL, schema="archive_mac", verify_last=100)
            s["restore_health"] = check["status"]
            s["original_health"] = original["status"]
            s["restore_same_problems"] = check["problems"] == original["problems"]
            s["restore_batches"] = check["batches_by_status"]
            _check(s["restore_matches_source"] and s["restore_same_problems"]
                   and check["batches_by_status"] == original["batches_by_status"]
                   and all(v["ok"] for v in check["verified_batches"]), "restore differs")

        with Step(report, "11_resources") as s:
            sizes = await target.fetch(
                """SELECT n.nspname AS schema, sum(pg_total_relation_size(c.oid))::bigint AS bytes
                   FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname='archive_mac' AND c.relkind IN ('r','i','t') GROUP BY 1"""
            )
            s["archive_mac_bytes"] = int(sizes[0]["bytes"]) if sizes else 0
            s["bytes_per_trade"] = round(s["archive_mac_bytes"] / max(1, report["steps"]["02_export_day"]["rows"]), 1)
            s["usage_total"] = {k: round(v, 2) for k, v in _usage().items()}
    finally:
        await source.close()
        await target.close()
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["passed"] = all(step.get("passed") for step in report["steps"].values())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", required=True, type=date.fromisoformat)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--chunk", type=int, default=500_000)
    args = parser.parse_args(argv)
    report = asyncio.run(run(args.day, args.work, args.chunk))
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(args.report)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
