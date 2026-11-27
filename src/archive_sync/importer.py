"""Server side: verify and import batch files into the separate archive schema.

A batch is accepted all-or-nothing in one transaction. Any hash, range, uniqueness,
completeness or payload conflict rolls the whole batch back and records it as QUARANTINED
(without rows). The live tables in ``public`` and the server's own ingestion cursor are
never read or written here.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

from src.archive_sync.common import (
    CANONICAL_SETTINGS,
    COLUMNS,
    DEFAULT_SCHEMA,
    FORMAT,
    KINDS,
    SOURCE_VALUE,
    ArchiveSyncError,
    batch_id_for,
    canonical_select,
    checked_schema,
    disk_gate,
    hole_size,
    normalise_holes,
    require_disk,
    sha256_file,
)

ACCEPTED, ALREADY, QUARANTINED, STALE, OUT_OF_ORDER, FILE_INVALID = (
    "ACCEPTED",
    "ALREADY_ACCEPTED",
    "QUARANTINED",
    "STALE",
    "OUT_OF_ORDER",
    "FILE_INVALID",
)
# Heap + primary key + batch index, generously rounded up from the CSV size.
DB_BYTES_PER_CSV_BYTE = 3
# 500k trades are ~45 MB of CSV; anything far above is refused before it is unpacked.
MAX_CSV_BYTES = 512 * 1024 * 1024


class _Quarantine(Exception):
    pass


LAYOUTS = ("v1", "v2")
# Layout for archive schemas created from now on through the command line. The library default
# stays v1 so existing callers and benches behave exactly as before; an existing schema keeps its layout.
PREFERRED_NEW_LAYOUT = "v2"


def _schema_ddl(schema: str, layout: str = "v1") -> list[str]:
    """v1: every trade row repeats the 64-character batch_id (S1/S2 as tested).

    v2 (S2.1 draft): batches get a numeric ``batch_no``; trade rows reference it as INTEGER and
    are stored in alignment-friendly column order. The sha256 batch_id, content and file hashes
    and the full manifest stay in ``batches``: provenance is the same, only the per-row
    reference is smaller. The canonical (hashed) column order does not change.
    """
    if layout not in LAYOUTS:
        raise ArchiveSyncError(f"unknown archive layout {layout!r}")
    batch_no = "batch_no INTEGER GENERATED ALWAYS AS IDENTITY UNIQUE," if layout == "v2" else ""
    if layout == "v1":
        trades = f"""CREATE TABLE IF NOT EXISTS {schema}.agg_trades (
            symbol TEXT NOT NULL,
            aggregate_trade_id BIGINT NOT NULL CHECK (aggregate_trade_id >= 0),
            trade_time TIMESTAMPTZ NOT NULL,
            price DOUBLE PRECISION NOT NULL CHECK (price > 0),
            quantity DOUBLE PRECISION NOT NULL CHECK (quantity > 0),
            buyer_is_maker BOOLEAN NOT NULL,
            source TEXT NOT NULL,
            ingest_timestamp TIMESTAMPTZ NOT NULL,
            batch_id TEXT NOT NULL REFERENCES {schema}.batches(batch_id),
            PRIMARY KEY (symbol, aggregate_trade_id))"""
        batch_index = f"CREATE INDEX IF NOT EXISTS agg_trades_batch_idx ON {schema}.agg_trades (batch_id)"
    else:
        trades = f"""CREATE TABLE IF NOT EXISTS {schema}.agg_trades (
            aggregate_trade_id BIGINT NOT NULL CHECK (aggregate_trade_id >= 0),
            trade_time TIMESTAMPTZ NOT NULL,
            ingest_timestamp TIMESTAMPTZ NOT NULL,
            price DOUBLE PRECISION NOT NULL CHECK (price > 0),
            quantity DOUBLE PRECISION NOT NULL CHECK (quantity > 0),
            batch_no INTEGER NOT NULL REFERENCES {schema}.batches(batch_no),
            buyer_is_maker BOOLEAN NOT NULL,
            symbol TEXT NOT NULL,
            source TEXT NOT NULL,
            PRIMARY KEY (symbol, aggregate_trade_id))"""
        batch_index = f"CREATE INDEX IF NOT EXISTS agg_trades_batch_idx ON {schema}.agg_trades (batch_no)"
    return [
        f"CREATE SCHEMA IF NOT EXISTS {schema}",
        f"""CREATE TABLE IF NOT EXISTS {schema}.batches (
            {batch_no}
            batch_id TEXT PRIMARY KEY CHECK (batch_id ~ '^[0-9a-f]{{64}}$'),
            kind TEXT NOT NULL CHECK (kind IN ('new','backfill','prefix')),
            symbol TEXT NOT NULL,
            lo_id BIGINT NOT NULL,
            hi_id BIGINT NOT NULL CHECK (hi_id >= lo_id),
            row_count BIGINT NOT NULL,
            holes JSONB NOT NULL,
            content_sha256 TEXT NOT NULL,
            file_sha256 TEXT NOT NULL,
            source_cursor_id BIGINT,
            exported_at TIMESTAMPTZ,
            status TEXT NOT NULL CHECK (status IN ('ACCEPTED','QUARANTINED','STALE')),
            reason TEXT,
            manifest JSONB NOT NULL,
            imported_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
        trades,
        batch_index,
        f"""CREATE TABLE IF NOT EXISTS {schema}.sync_state (
            symbol TEXT PRIMARY KEY,
            start_id BIGINT NOT NULL,
            watermark BIGINT NOT NULL CHECK (watermark >= start_id - 1),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
        f"""CREATE TABLE IF NOT EXISTS {schema}.holes (
            symbol TEXT NOT NULL,
            lo_id BIGINT NOT NULL,
            hi_id BIGINT NOT NULL CHECK (hi_id >= lo_id),
            PRIMARY KEY (symbol, lo_id))""",
    ]


async def archive_layout(connection: Any, schema: str = DEFAULT_SCHEMA) -> str | None:
    """'v1' or 'v2' for an existing archive schema, None if it has no trade table yet."""
    columns = {
        str(r["column_name"])
        for r in await connection.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=$1 AND table_name='agg_trades'",
            checked_schema(schema),
        )
    }
    if "batch_no" in columns:
        return "v2"
    if "batch_id" in columns:
        return "v1"
    return None


async def ensure_schema(connection: Any, schema: str = DEFAULT_SCHEMA, layout: str | None = None) -> str:
    """Create the archive schema if needed and return its layout; never converts an existing one."""
    schema = checked_schema(schema)
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"archive-ddl:{schema}")
        existing = await archive_layout(connection, schema)
        if existing is not None and layout is not None and existing != layout:
            raise ArchiveSyncError(f"archive schema {schema} has layout {existing}, not {layout}; no conversion")
        chosen = existing or layout or "v1"
        for statement in _schema_ddl(schema, chosen):
            await connection.execute(statement)
    return chosen


async def layout_for_new_schema(connection: Any, schema: str, requested: str | None = None) -> str | None:
    """Layout to pass to ensure_schema: the requested one, else the preferred one for a schema that
    does not exist yet, else None (an existing schema keeps whatever layout it has)."""
    if requested is not None:
        return requested
    return PREFERRED_NEW_LAYOUT if await archive_layout(connection, checked_schema(schema)) is None else None


def row_reference(layout: str) -> tuple[str, str]:
    """SQL column and value expression that tie a trade row to its batch (value takes batch_id as $1)."""
    if layout == "v2":
        return "batch_no", "(SELECT batch_no FROM {schema}.batches WHERE batch_id=$1)"
    return "batch_id", "$1"


async def server_state(connection: Any, symbol: str, schema: str = DEFAULT_SCHEMA) -> dict[str, Any]:
    schema = checked_schema(schema)
    row = await connection.fetchrow(f"SELECT start_id, watermark FROM {schema}.sync_state WHERE symbol=$1", symbol)
    holes = await connection.fetch(
        f"SELECT lo_id, hi_id FROM {schema}.holes WHERE symbol=$1 ORDER BY lo_id", symbol
    )
    return {
        "symbol": symbol,
        "schema": schema,
        "start_id": None if row is None else int(row["start_id"]),
        "watermark": None if row is None else int(row["watermark"]),
        "holes": [[int(h["lo_id"]), int(h["hi_id"])] for h in holes],
    }


def _merge(ranges: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for a, b in sorted(ranges):
        if merged and a <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


_REQUIRED = {
    "batch_id": str, "kind": str, "symbol": str, "lo": int, "hi": int, "holes": list, "row_count": int,
    "content_sha256": str, "file": str, "file_bytes": int, "file_sha256": str,
}


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArchiveSyncError(f"{path.name}: unreadable manifest ({type(error).__name__})") from None
    if not isinstance(manifest, dict):
        raise ArchiveSyncError(f"{path.name}: manifest is not an object")
    for key, kind in _REQUIRED.items():
        value = manifest.get(key)
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise ArchiveSyncError(f"{path.name}: manifest field {key} missing or wrong type")
    if manifest.get("format") != FORMAT or manifest.get("kind") not in KINDS:
        raise ArchiveSyncError(f"{path.name}: unknown manifest format or kind")
    if list(manifest.get("columns") or []) != list(COLUMNS):
        raise ArchiveSyncError(f"{path.name}: column list differs from this importer")
    return manifest


def _verify_file(manifest_path: Path, manifest: dict[str, Any]) -> tuple[bytes | None, str | None]:
    """File-level checks. A failure here means 'transfer again', never 'accept'."""
    name = str(manifest.get("file") or "")
    if "/" in name or "\\" in name or not name.endswith(".csv.gz"):
        return None, "data file name is not a plain batch file name"
    data_path = manifest_path.parent / name
    if not data_path.is_file():
        return None, "data file missing"
    if data_path.stat().st_size != int(manifest["file_bytes"]):
        return None, "data file size differs from manifest"
    if sha256_file(data_path) != manifest["file_sha256"]:
        return None, "data file sha256 differs from manifest"
    try:
        holes = normalise_holes(manifest["holes"], int(manifest["lo"]), int(manifest["hi"]))
    except (ArchiveSyncError, TypeError, ValueError) as error:
        return None, f"invalid hole list: {error}"
    expected_id = batch_id_for(
        manifest["kind"], manifest["symbol"], int(manifest["lo"]), int(manifest["hi"]), manifest["content_sha256"], holes
    )
    if expected_id != manifest.get("batch_id"):
        return None, "batch_id does not match manifest content"
    limit = int(manifest["csv_bytes"]) if isinstance(manifest.get("csv_bytes"), int) else MAX_CSV_BYTES
    try:
        with gzip.open(data_path, "rb") as handle:
            payload = handle.read(min(limit, MAX_CSV_BYTES) + 1)
    except (OSError, EOFError):
        return None, "data file is not valid gzip"
    if len(payload) > min(limit, MAX_CSV_BYTES):
        return None, "data file larger than the manifest says"
    return payload, None


async def _record(connection: Any, schema: str, manifest: dict[str, Any], status: str, reason: str | None) -> None:
    await connection.execute(
        f"""INSERT INTO {schema}.batches (batch_id, kind, symbol, lo_id, hi_id, row_count, holes,
                content_sha256, file_sha256, source_cursor_id, exported_at, status, reason, manifest)
            VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10,$11::timestamptz,$12,$13,$14::jsonb)
            ON CONFLICT (batch_id) DO NOTHING""",
        manifest["batch_id"],
        manifest["kind"],
        manifest["symbol"],
        int(manifest["lo"]),
        int(manifest["hi"]),
        int(manifest["row_count"]),
        json.dumps(manifest["holes"]),
        manifest["content_sha256"],
        manifest["file_sha256"],
        manifest.get("source_cursor_id"),
        datetime.fromisoformat(manifest["exported_at"]) if manifest.get("exported_at") else None,
        status,
        reason,
        json.dumps(manifest, sort_keys=True),
    )


def _placement(kind: str, lo: int, hi: int, state: dict[str, Any]) -> tuple[str, list[int] | None]:
    """Where a batch belongs relative to the archive: 'fits', 'stale' or 'out_of_order'."""
    watermark, start = state["watermark"], state["start_id"]
    if kind == "new":
        if watermark is None:
            return "fits", None
        if lo == watermark + 1:
            return "fits", None
        return ("stale", None) if lo <= watermark else ("out_of_order", None)
    if watermark is None:
        return "out_of_order", None
    if kind == "prefix":
        if hi == start - 1:
            return "fits", None
        return ("stale", None) if hi >= start else ("out_of_order", None)
    for a, b in state["holes"]:
        if a <= lo and hi <= b:
            return "fits", [a, b]
    if start <= lo and hi <= watermark:
        return "stale", None
    return "out_of_order", None


async def import_batch(
    connection: Any,
    manifest_path: str | Path,
    *,
    symbol: str,
    gate_path: str | Path,
    schema: str = DEFAULT_SCHEMA,
    usage: Callable[[str], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    schema = checked_schema(schema)
    path = Path(manifest_path)
    try:
        manifest = load_manifest(path)
    except ArchiveSyncError as error:
        return {"batch_id": None, "file": path.name, "result": FILE_INVALID, "reason": str(error)}
    result: dict[str, Any] = {
        "batch_id": manifest.get("batch_id"),
        "kind": manifest["kind"],
        "lo": manifest.get("lo"),
        "hi": manifest.get("hi"),
    }
    if manifest.get("symbol") != symbol:
        return {**result, "result": FILE_INVALID, "reason": "manifest symbol differs from --symbol"}
    payload, problem = _verify_file(path, manifest)
    if payload is None:
        return {**result, "result": FILE_INVALID, "reason": problem}
    kind, lo, hi = manifest["kind"], int(manifest["lo"]), int(manifest["hi"])
    holes = [list(h) for h in manifest["holes"]]
    require_disk(disk_gate(gate_path, len(payload) * DB_BYTES_PER_CSV_BYTE, usage=usage))

    reason: str | None = None
    try:
        async with connection.transaction():
            for setting in CANONICAL_SETTINGS:
                await connection.execute(setting)
            await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"archive:{schema}:{symbol}")
            existing = await connection.fetchrow(
                f"SELECT status, reason FROM {schema}.batches WHERE batch_id=$1", manifest["batch_id"]
            )
            if existing is not None:
                status = str(existing["status"])
                return {**result, "result": ALREADY if status == "ACCEPTED" else status, "reason": existing["reason"]}
            state = await server_state(connection, symbol, schema)
            placement, hole = _placement(kind, lo, hi, state)
            if placement == "out_of_order":
                return {**result, "result": OUT_OF_ORDER, "reason": "batch does not connect to the archive yet", "state": state}

            if hashlib.sha256(payload).hexdigest() != manifest["content_sha256"]:
                raise _Quarantine("content sha256 differs from manifest")
            if payload.count(b"\n") != int(manifest["row_count"]):
                raise _Quarantine("row count differs from manifest")
            if int(manifest["row_count"]) != (hi - lo + 1) - hole_size(holes):
                raise _Quarantine("manifest row count does not match range minus holes")

            await connection.execute(
                f"""CREATE TEMP TABLE archive_stage (
                    symbol TEXT, aggregate_trade_id BIGINT, trade_time TIMESTAMPTZ,
                    price DOUBLE PRECISION, quantity DOUBLE PRECISION, buyer_is_maker BOOLEAN,
                    source TEXT, ingest_timestamp TIMESTAMPTZ) ON COMMIT DROP"""
            )
            await connection.copy_to_table("archive_stage", source=BytesIO(payload), columns=list(COLUMNS), format="csv")
            check = await connection.fetchrow(
                """SELECT count(*) AS n, count(DISTINCT aggregate_trade_id) AS distinct_ids,
                          count(*) FILTER (WHERE symbol IS DISTINCT FROM $1) AS wrong_symbol,
                          count(*) FILTER (WHERE aggregate_trade_id < $2 OR aggregate_trade_id > $3
                                           OR aggregate_trade_id IS NULL) AS outside,
                          count(*) FILTER (WHERE source IS DISTINCT FROM $4) AS wrong_source,
                          count(*) FILTER (WHERE trade_time IS NULL OR ingest_timestamp IS NULL
                                           OR buyer_is_maker IS NULL OR NOT price > 0
                                           OR NOT quantity > 0) AS invalid
                   FROM archive_stage""",
                symbol,
                lo,
                hi,
                SOURCE_VALUE,
            )
            if check["n"] != int(manifest["row_count"]):
                raise _Quarantine("loaded rows differ from manifest row count")
            if check["distinct_ids"] != check["n"]:
                raise _Quarantine("duplicate trade ids inside the batch")
            for field, text in (
                ("wrong_symbol", "rows of another symbol"),
                ("outside", "trade ids outside the batch range"),
                ("wrong_source", "unexpected source value"),
                ("invalid", "rows with invalid values"),
            ):
                if check[field]:
                    raise _Quarantine(text)
            in_holes = await connection.fetchval(
                """SELECT count(*) FROM archive_stage s
                   JOIN unnest($1::bigint[], $2::bigint[]) AS h(a, b)
                     ON s.aggregate_trade_id BETWEEN h.a AND h.b""",
                [h[0] for h in holes],
                [h[1] for h in holes],
            )
            if in_holes:
                raise _Quarantine("rows inside ranges the manifest lists as holes")
            staged = hashlib.sha256()

            async def _feed(chunk: bytes) -> None:
                staged.update(chunk)

            await connection.copy_from_query(canonical_select("archive_stage", "true"), output=_feed, format="csv")
            if staged.hexdigest() != manifest["content_sha256"]:
                raise _Quarantine("rows re-read from the database do not reproduce the content hash")
            # Same id/count/range checks together prove: ids == [lo, hi] minus holes, exactly.
            compare = await connection.fetchrow(
                f"""SELECT count(*) AS overlap,
                           count(*) FILTER (WHERE (a.trade_time, a.price, a.quantity, a.buyer_is_maker,
                                                   a.source, a.ingest_timestamp)
                                    IS DISTINCT FROM (s.trade_time, s.price, s.quantity, s.buyer_is_maker,
                                                      s.source, s.ingest_timestamp)) AS conflicts
                    FROM archive_stage s JOIN {schema}.agg_trades a
                      ON a.symbol = s.symbol AND a.aggregate_trade_id = s.aggregate_trade_id"""
            )
            if compare["conflicts"]:
                raise _Quarantine(f"{compare['conflicts']} trades differ from rows already in the archive")
            if placement == "stale":
                await _record(connection, schema, manifest, "STALE", "range already archived; rows agree")
                return {**result, "result": STALE, "overlap": int(compare["overlap"])}
            if compare["overlap"]:
                raise _Quarantine("archive already holds rows inside a range it lists as missing")

            await _record(connection, schema, manifest, "ACCEPTED", None)
            ref_column, ref_value = row_reference(await archive_layout(connection, schema) or "v1")
            inserted = await connection.execute(
                f"""INSERT INTO {schema}.agg_trades ({', '.join(COLUMNS)}, {ref_column})
                    SELECT {', '.join(COLUMNS)}, {ref_value.format(schema=schema)} FROM archive_stage""",
                manifest["batch_id"],
            )
            if int(inserted.split()[-1]) != int(manifest["row_count"]):
                raise _Quarantine("insert count differs from manifest")
            new_holes = [list(h) for h in state["holes"]]
            if kind == "new":
                if state["watermark"] is None:
                    await connection.execute(
                        f"INSERT INTO {schema}.sync_state (symbol, start_id, watermark) VALUES ($1,$2,$3)", symbol, lo, hi
                    )
                else:
                    await connection.execute(
                        f"UPDATE {schema}.sync_state SET watermark=$2, updated_at=clock_timestamp() WHERE symbol=$1",
                        symbol,
                        hi,
                    )
                new_holes += holes
            elif kind == "prefix":
                await connection.execute(
                    f"UPDATE {schema}.sync_state SET start_id=$2, updated_at=clock_timestamp() WHERE symbol=$1", symbol, lo
                )
                new_holes += holes
            else:
                a, b = hole  # type: ignore[misc]
                new_holes.remove([a, b])
                if a < lo:
                    new_holes.append([a, lo - 1])
                if hi < b:
                    new_holes.append([hi + 1, b])
                new_holes += holes
            new_holes = _merge(new_holes)
            await connection.execute(f"DELETE FROM {schema}.holes WHERE symbol=$1", symbol)
            if new_holes:
                await connection.executemany(
                    f"INSERT INTO {schema}.holes (symbol, lo_id, hi_id) VALUES ($1,$2,$3)",
                    [(symbol, a, b) for a, b in new_holes],
                )
            return {**result, "result": ACCEPTED, "row_count": int(manifest["row_count"]), "holes": len(holes)}
    except _Quarantine as problem_found:
        reason = str(problem_found)
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"archive:{schema}:{symbol}")
        existing = await connection.fetchval(f"SELECT status FROM {schema}.batches WHERE batch_id=$1", manifest["batch_id"])
        if existing is not None:
            return {**result, "result": ALREADY if existing == "ACCEPTED" else str(existing)}
        await _record(connection, schema, manifest, "QUARANTINED", reason)
    return {**result, "result": QUARANTINED, "reason": reason}


def _order_key(manifest: dict[str, Any]) -> tuple[int, int]:
    kind = manifest["kind"]
    if kind == "backfill":
        return (0, int(manifest["lo"]))
    if kind == "new":
        return (1, int(manifest["lo"]))
    return (2, -int(manifest["hi"]))


async def import_directory(
    connection: Any,
    directory: str | Path,
    *,
    symbol: str,
    gate_path: str | Path,
    schema: str = DEFAULT_SCHEMA,
    usage: Callable[[str], Any] = shutil.disk_usage,
    layout: str | None = None,
) -> dict[str, Any]:
    """Import every complete batch in ``directory``; safe to run again after any interruption."""
    await ensure_schema(connection, schema, layout)
    entries = []
    results: list[dict[str, Any]] = []
    halted = None
    for path in sorted(Path(directory).glob(f"{symbol}-*.manifest.json")):
        try:
            entries.append((path, load_manifest(path)))
        except ArchiveSyncError as error:
            results.append({"batch_id": None, "file": path.name, "result": FILE_INVALID, "reason": str(error)})
            halted = f"stopped after unreadable manifest {path.name}"
    entries.sort(key=lambda item: _order_key(item[1]))
    for path, manifest in entries:
        if halted and manifest["kind"] != "backfill":
            results.append({"batch_id": manifest["batch_id"], "result": "NOT_TRIED", "reason": halted})
            continue
        outcome = await import_batch(connection, path, symbol=symbol, gate_path=gate_path, schema=schema, usage=usage)
        results.append(outcome)
        if outcome["result"] in (QUARANTINED, FILE_INVALID):
            halted = f"stopped after {outcome['result']} batch {manifest['batch_id'][:12]}"
    summary: dict[str, int] = {}
    for item in results:
        summary[item["result"]] = summary.get(item["result"], 0) + 1
    return {
        "mode": "IMPORT_ARCHIVE_SCHEMA_ONLY",
        "schema": schema,
        "symbol": symbol,
        "summary": summary,
        "results": results,
        "state": await server_state(connection, symbol, schema),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
