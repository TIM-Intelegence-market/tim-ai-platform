"""Mac side: read-only key-range export of ``agg_trades`` into hashed batch files."""
from __future__ import annotations

import gzip
import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.archive_sync.common import (
    CANONICAL_SETTINGS,
    COLUMNS,
    FORMAT,
    ArchiveSyncError,
    batch_id_for,
    canonical_select,
    checked_schema,
    disk_gate,
    hole_size,
    require_disk,
    sha256_file,
    write_json_atomic,
)

DEFAULT_CHUNK = 500_000
# Measured 24.11.: one day = 1.44 M trades = 13.6 MB gzip, about 10 bytes per trade.
GZIP_BYTES_PER_TRADE_ESTIMATE = 16

_HOLES_SQL = """
WITH ids AS (
    SELECT aggregate_trade_id AS id FROM {table}
    WHERE symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3
), bounded AS (
    SELECT $2::bigint - 1 AS id UNION ALL SELECT id FROM ids UNION ALL SELECT $3::bigint + 1
), gaps AS (
    SELECT id, lead(id) OVER (ORDER BY id) AS nxt FROM bounded
)
SELECT id + 1 AS a, nxt - 1 AS b FROM gaps WHERE nxt > id + 1 ORDER BY 1
"""


def batch_basename(symbol: str, kind: str, lo: int, hi: int) -> str:
    return f"{symbol}-{kind}-{lo:020d}-{hi:020d}"


def _chunks(lo: int, hi: int, size: int) -> list[tuple[int, int]]:
    return [(start, min(hi, start + size - 1)) for start in range(lo, hi + 1, size)]


def plan_ranges(
    *,
    server_state: dict[str, Any],
    mac_cursor: int,
    mac_min: int | None,
    chunk: int,
) -> list[tuple[str, int, int]]:
    """Which ranges to export this run: backfills of open holes, then new data, then older data."""
    if mac_min is None:
        return []
    plan: list[tuple[str, int, int]] = []
    for a, b in server_state.get("holes") or []:
        for lo, hi in _chunks(int(a), min(int(b), mac_cursor), chunk):
            plan.append(("backfill", lo, hi))
    watermark = server_state.get("watermark")
    start = server_state.get("start_id")
    lo = mac_min if watermark is None else int(watermark) + 1
    while lo <= mac_cursor:
        hi = min(mac_cursor, lo + chunk - 1)
        plan.append(("new", lo, hi))
        lo = hi + 1
    if start is not None and mac_min < int(start):
        hi = int(start) - 1
        while hi >= mac_min:
            lo = max(mac_min, hi - chunk + 1)
            plan.append(("prefix", lo, hi))
            hi = lo - 1
    # Backfills only make sense where the Mac now has rows; the caller filters those.
    return plan


async def _export_one(
    connection: Any,
    *,
    table: str,
    symbol: str,
    kind: str,
    lo: int,
    hi: int,
    holes: list[list[int]],
    out_dir: Path,
    mac_cursor: int,
    snapshot: str,
    exported_at: str,
    code_version: str | None,
) -> dict[str, Any]:
    base = batch_basename(symbol, kind, lo, hi)
    data_path = out_dir / f"{base}.csv.gz"
    part = out_dir / f"{base}.csv.gz.part"
    content = hashlib.sha256()
    counts = {"bytes": 0, "rows": 0}
    raw = part.open("wb")
    zipped = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)

    async def sink(chunk: bytes) -> None:
        content.update(chunk)
        counts["bytes"] += len(chunk)
        counts["rows"] += chunk.count(b"\n")
        zipped.write(chunk)

    try:
        await connection.copy_from_query(
            canonical_select(table, "symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3"),
            symbol,
            lo,
            hi,
            output=sink,
            format="csv",
        )
    finally:
        zipped.close()
        raw.close()
    expected_rows = (hi - lo + 1) - hole_size(holes)
    if counts["rows"] != expected_rows:
        part.unlink(missing_ok=True)
        raise ArchiveSyncError(f"{base}: snapshot gave {counts['rows']} rows, holes imply {expected_rows}")
    os.replace(part, data_path)
    content_sha = content.hexdigest()

    manifest = {
        "format": FORMAT,
        "batch_id": batch_id_for(kind, symbol, lo, hi, content_sha, holes),
        "kind": kind,
        "symbol": symbol,
        "lo": lo,
        "hi": hi,
        "holes": holes,
        "row_count": counts["rows"],
        "csv_bytes": counts["bytes"],
        "content_sha256": content_sha,
        "file": data_path.name,
        "file_bytes": data_path.stat().st_size,
        "file_sha256": sha256_file(data_path),
        "columns": list(COLUMNS),
        "source_cursor_id": mac_cursor,
        "source_snapshot": snapshot,
        "exported_at": exported_at,
        "code_version": code_version,
    }
    write_json_atomic(out_dir / f"{base}.manifest.json", manifest)
    return manifest


async def export_batches(
    connection: Any,
    *,
    symbol: str,
    out_dir: str | Path,
    server_state: dict[str, Any],
    source_schema: str = "public",
    chunk: int = DEFAULT_CHUNK,
    max_batches: int = 10,
    statement_timeout_ms: int = 600_000,
    usage: Callable[[str], Any] = shutil.disk_usage,
    now: datetime | None = None,
    code_version: str | None = None,
) -> dict[str, Any]:
    """Export up to ``max_batches`` batches from ONE read-only REPEATABLE READ snapshot.

    The upper bound is the durable ingestion cursor read inside that same snapshot, so trades
    still in flight are never exported. IDs missing on the Mac are listed as holes; the server
    keeps them open, and a later run exports them as ``backfill`` once the Mac has them.
    """
    if chunk < 1:
        raise ArchiveSyncError("chunk must be positive")
    if server_state.get("symbol") not in (None, symbol):
        raise ArchiveSyncError("server state belongs to another symbol")
    schema = checked_schema(source_schema, allow_public=True)
    table = f"{schema}.agg_trades"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    exported_at = (now or datetime.now(timezone.utc)).isoformat()
    written: list[dict[str, Any]] = []
    skipped_empty = 0
    async with connection.transaction(isolation="repeatable_read", readonly=True):
        await connection.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        for setting in CANONICAL_SETTINGS:
            await connection.execute(setting)
        snapshot = str(await connection.fetchval("SELECT pg_current_snapshot()::text"))
        mac_cursor = await connection.fetchval(
            f"""SELECT last_aggregate_trade_id FROM {schema}.ingestion_cursors
                WHERE source='BINANCE' AND market='SPOT' AND symbol=$1 AND data_type='AGG_TRADE'""",
            symbol,
        )
        if mac_cursor is None:
            raise ArchiveSyncError("no durable ingestion cursor for symbol; nothing is exported")
        mac_cursor = int(mac_cursor)
        if server_state.get("watermark") is not None and mac_cursor < int(server_state["watermark"]):
            raise ArchiveSyncError("source cursor is behind the archive watermark (restore or reset?); nothing exported")
        mac_min = await connection.fetchval(
            f"SELECT aggregate_trade_id FROM {table} WHERE symbol=$1 ORDER BY aggregate_trade_id LIMIT 1",
            symbol,
        )
        plan = plan_ranges(
            server_state=server_state,
            mac_cursor=mac_cursor,
            mac_min=None if mac_min is None else int(mac_min),
            chunk=chunk,
        )
        for kind, lo, hi in plan:
            if len(written) >= max_batches:
                break
            holes = [[int(r["a"]), int(r["b"])] for r in await connection.fetch(_HOLES_SQL.format(table=table), symbol, lo, hi)]
            if kind == "backfill" and hole_size(holes) == hi - lo + 1:
                skipped_empty += 1
                continue
            expected = (hi - lo + 1) - hole_size(holes)
            require_disk(disk_gate(out, expected * GZIP_BYTES_PER_TRADE_ESTIMATE, usage=usage))
            written.append(
                await _export_one(
                    connection,
                    table=table,
                    symbol=symbol,
                    kind=kind,
                    lo=lo,
                    hi=hi,
                    holes=holes,
                    out_dir=out,
                    mac_cursor=mac_cursor,
                    snapshot=snapshot,
                    exported_at=exported_at,
                    code_version=code_version,
                )
            )
    return {
        "mode": "EXPORT_READ_ONLY",
        "symbol": symbol,
        "source_cursor_id": mac_cursor,
        "batches": [
            {k: m[k] for k in ("batch_id", "kind", "lo", "hi", "row_count", "file")} for m in written
        ],
        "backfill_ranges_still_empty": skipped_empty,
        "exported_at": exported_at,
    }
