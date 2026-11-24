"""S2.1: compare archive layouts v1 and v2 on the same batch files (manual, throwaway database only).

    python -m src.archive_sync.layout_bench --batches DIR --work DIR --report report.json

Imports the same batches into fresh schemas ``bench_v1``/``bench_v2`` of a database whose name
starts with ``archive_dryrun``, then measures size, import time, query times and dump/restore.
The batch files are only read. Nothing outside that database is written.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.archive_sync import health, importer
from src.archive_sync.common import ArchiveSyncError, sha256_file

SYMBOL = "BTCUSDT"
REPEAT = 7
_DAY = timedelta(days=1)


async def _timed(connection: Any, query: str, *args: Any) -> float:
    samples = []
    for _ in range(REPEAT):
        t0 = time.perf_counter()
        await connection.fetch(query, *args)
        samples.append((time.perf_counter() - t0) * 1000)
    return round(statistics.median(samples), 3)


async def _sizes(connection: Any, schema: str) -> dict[str, int]:
    rows = await connection.fetch(
        """SELECT c.relname, pg_relation_size(c.oid) AS bytes FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $1 AND c.relkind IN ('r','i','t')""",
        schema,
    )
    sizes = {str(r["relname"]): int(r["bytes"]) for r in rows}
    sizes["total"] = sum(sizes.values())
    return sizes


async def _bench_layout(connection: Any, layout: str, batches: Path, work: Path, url: str, pg_bin: Path) -> dict[str, Any]:
    schema = f"bench_{layout}"
    exists = await connection.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname=$1", schema)
    if exists:
        raise ArchiveSyncError(f"{schema} already exists; use a fresh database")
    await importer.ensure_schema(connection, schema, layout)
    t0 = time.perf_counter()
    result = await importer.import_directory(connection, batches, symbol=SYMBOL, gate_path=work, schema=schema)
    import_s = round(time.perf_counter() - t0, 3)
    await connection.execute(f"VACUUM (ANALYZE) {schema}.agg_trades")
    rows = int(await connection.fetchval(f"SELECT count(*) FROM {schema}.agg_trades"))
    lo, hi = (int(v) for v in await connection.fetchrow(
        f"SELECT min(aggregate_trade_id), max(aggregate_trade_id) FROM {schema}.agg_trades"))
    mid = lo + (hi - lo) // 2
    sizes = await _sizes(connection, schema)
    ref_column, ref_value = importer.row_reference(layout)
    first_batch = await connection.fetchval(f"SELECT batch_id FROM {schema}.batches ORDER BY lo_id LIMIT 1")
    queries = {
        "point_lookup_ms": await _timed(connection, f"SELECT * FROM {schema}.agg_trades WHERE symbol=$1 AND aggregate_trade_id=$2", SYMBOL, mid),
        "range_100k_count_ms": await _timed(connection, f"SELECT count(*), sum(quantity) FROM {schema}.agg_trades WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3", SYMBOL, mid, mid + 99_999),
        "full_day_scan_ms": await _timed(connection, f"SELECT count(*), sum(price*quantity) FROM {schema}.agg_trades"),
        "one_hour_by_time_ms": await _timed(connection, f"SELECT count(*) FROM {schema}.agg_trades WHERE trade_time >= (SELECT min(trade_time) FROM {schema}.agg_trades) + interval '12 hours' AND trade_time < (SELECT min(trade_time) FROM {schema}.agg_trades) + interval '13 hours'"),
        "provenance_of_one_trade_ms": await _timed(connection, f"SELECT b.batch_id, b.content_sha256, b.file_sha256, b.exported_at FROM {schema}.agg_trades a JOIN {schema}.batches b USING ({ref_column}) WHERE a.symbol=$1 AND a.aggregate_trade_id=$2", SYMBOL, mid),
        "rows_of_one_batch_ms": await _timed(connection, f"SELECT count(*) FROM {schema}.agg_trades WHERE {ref_column} = {ref_value.format(schema=schema)}", first_batch),
    }
    t0 = time.perf_counter()
    digest = await health.range_digest(connection, table=f"{schema}.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
    queries["canonical_digest_full_day_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    t0 = time.perf_counter()
    check = await health.archive_health(connection, symbol=SYMBOL, schema=schema, verify_last=1000, max_age=_DAY * 3650)
    queries["verify_all_batches_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    dump = work / f"{schema}.dump"
    t0 = time.perf_counter()
    subprocess.run([str(pg_bin / "pg_dump"), "-Fc", "-n", schema, "-f", str(dump), url], check=True, capture_output=True)
    dump_s = round(time.perf_counter() - t0, 3)
    restore_db = f"archive_dryrun_s21_restore_{layout}"
    await connection.execute(f"CREATE DATABASE {restore_db}")
    restore_url = url.rsplit("/", 1)[0] + "/" + restore_db
    t0 = time.perf_counter()
    subprocess.run([str(pg_bin / "pg_restore"), "--no-owner", "-d", restore_url, str(dump)], check=True, capture_output=True)
    restore_s = round(time.perf_counter() - t0, 3)
    import asyncpg

    restored = await asyncpg.connect(restore_url)
    try:
        restored_digest = await health.range_digest(restored, table=f"{schema}.agg_trades", symbol=SYMBOL, lo=lo, hi=hi)
        restored_check = await health.archive_health(restored, symbol=SYMBOL, schema=schema, verify_last=1000, max_age=_DAY * 3650)
        restored_batches = await restored.fetch(f"SELECT batch_id, content_sha256, file_sha256 FROM {schema}.batches ORDER BY batch_id")
    finally:
        await restored.close()
    batches_now = await connection.fetch(f"SELECT batch_id, content_sha256, file_sha256 FROM {schema}.batches ORDER BY batch_id")
    return {
        "layout": layout,
        "import": {"summary": result["summary"], "seconds": import_s, "rows_per_s": round(rows / import_s)},
        "rows": rows,
        "sizes_bytes": sizes,
        "bytes_per_trade": round(sizes["total"] / rows, 1),
        "heap_bytes_per_trade": round(sizes.get("agg_trades", 0) / rows, 1),
        "queries": queries,
        "digest": digest["sha256"],
        "health": check["status"],
        "verified_batches_ok": all(v["ok"] for v in check["verified_batches"]),
        "restore": {
            "dump_bytes": dump.stat().st_size,
            "dump_sha256": sha256_file(dump),
            "dump_seconds": dump_s,
            "restore_seconds": restore_s,
            "digest_equal": restored_digest["sha256"] == digest["sha256"],
            "health": restored_check["status"],
            "verified_batches_ok": all(v["ok"] for v in restored_check["verified_batches"]),
            "provenance_equal": [tuple(r) for r in restored_batches] == [tuple(r) for r in batches_now],
        },
    }




async def run(batches: Path, work: Path) -> dict[str, Any]:
    import asyncpg

    url = os.environ.get("TIM_ARCHIVE_TARGET_URL", "").strip()
    if not url:
        raise ArchiveSyncError("TIM_ARCHIVE_TARGET_URL is not set")
    pg_bin = Path(os.environ.get("TIM_DRYRUN_PG_BIN", "/Library/PostgreSQL/18/bin"))
    work.mkdir(parents=True, exist_ok=True)
    connection = await asyncpg.connect(url)
    try:
        info = await connection.fetchrow(
            "SELECT current_database() AS db, inet_server_port() AS port, current_setting('server_version_num')::int AS v")
        if not str(info["db"]).startswith("archive_dryrun") or int(info["port"]) == 5432:
            raise ArchiveSyncError("target must be a throwaway archive_dryrun* database, not on port 5432")
        report: dict[str, Any] = {
            "mode": "LAYOUT_BENCH_S2_1",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "target": {"database": info["db"], "port": info["port"], "server_version_num": info["v"]},
            "batch_files": {p.name: sha256_file(p) for p in sorted(batches.iterdir()) if p.is_file()},
            "layouts": {},
        }
        for layout in ("v1", "v2"):
            report["layouts"][layout] = await _bench_layout(connection, layout, batches, work, url, pg_bin)
    finally:
        await connection.close()
    v1, v2 = report["layouts"]["v1"], report["layouts"]["v2"]
    report["comparison"] = {
        "same_rows": v1["rows"] == v2["rows"],
        "same_canonical_digest": v1["digest"] == v2["digest"],
        "total_bytes_saved_pct": round(100 * (1 - v2["sizes_bytes"]["total"] / v1["sizes_bytes"]["total"]), 1),
        "bytes_per_trade": [v1["bytes_per_trade"], v2["bytes_per_trade"]],
        "import_seconds": [v1["import"]["seconds"], v2["import"]["seconds"]],
        "dump_bytes": [v1["restore"]["dump_bytes"], v2["restore"]["dump_bytes"]],
    }
    report["passed"] = bool(
        report["comparison"]["same_rows"] and report["comparison"]["same_canonical_digest"]
        and all(l["verified_batches_ok"] and l["restore"]["digest_equal"] and l["restore"]["provenance_equal"]
                and l["restore"]["verified_batches_ok"] for l in (v1, v2))
    )
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batches", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args(argv)
    report = asyncio.run(run(args.batches, args.work))
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps({"passed": report["passed"], "comparison": report["comparison"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
