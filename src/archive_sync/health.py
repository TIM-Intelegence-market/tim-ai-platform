"""Archive health checks and range digests (read-only)."""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from src.archive_sync.common import CANONICAL_SETTINGS, DEFAULT_SCHEMA, canonical_select, checked_schema, disk_gate
from src.archive_sync.importer import server_state


async def _sha_of_query(connection: Any, query: str, *args: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    rows = {"n": 0}

    async def sink(chunk: bytes) -> None:
        digest.update(chunk)
        rows["n"] += chunk.count(b"\n")

    await connection.copy_from_query(query, *args, output=sink, format="csv")
    return digest.hexdigest(), rows["n"]


async def range_digest(
    connection: Any, *, table: str, symbol: str, lo: int, hi: int, statement_timeout_ms: int = 300_000
) -> dict[str, Any]:
    """sha256 over the canonical rows of [lo, hi]; same bytes on Mac and server mean same trades."""
    async with connection.transaction(isolation="repeatable_read", readonly=True):
        await connection.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        for setting in CANONICAL_SETTINGS:
            await connection.execute(setting)
        sha, rows = await _sha_of_query(
            connection, canonical_select(table, "symbol=$1 AND aggregate_trade_id BETWEEN $2 AND $3"), symbol, lo, hi
        )
    return {"table": table, "symbol": symbol, "lo": lo, "hi": hi, "rows": rows, "sha256": sha}


async def archive_health(
    connection: Any,
    *,
    symbol: str,
    schema: str = DEFAULT_SCHEMA,
    max_age: timedelta = timedelta(hours=30),
    verify_last: int = 3,
    disk_path: str | Path | None = None,
    source_cursor_id: int | None = None,
    now: datetime | None = None,
    usage: Callable[[str], Any] = shutil.disk_usage,
) -> dict[str, Any]:
    schema = checked_schema(schema)
    now = now or datetime.now(timezone.utc)
    problems: list[str] = []
    warnings: list[str] = []
    async with connection.transaction(isolation="repeatable_read", readonly=True):
        await connection.execute("SET LOCAL statement_timeout = 300000")
        for setting in CANONICAL_SETTINGS:
            await connection.execute(setting)
        exists = await connection.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.batches")
        if not exists:
            return {"status": "FAIL", "problems": ["archive schema not initialised"], "symbol": symbol, "schema": schema}
        state = await server_state(connection, symbol, schema)
        statuses = {
            str(r["status"]): int(r["n"])
            for r in await connection.fetch(
                f"SELECT status, count(*) AS n FROM {schema}.batches WHERE symbol=$1 GROUP BY status", symbol
            )
        }
        last_import = await connection.fetchval(
            f"SELECT max(imported_at) FROM {schema}.batches WHERE symbol=$1 AND status='ACCEPTED'", symbol
        )
        chain = await connection.fetch(
            f"""SELECT lo_id, hi_id FROM {schema}.batches
                WHERE symbol=$1 AND status='ACCEPTED' AND kind IN ('new','prefix') ORDER BY lo_id""",
            symbol,
        )
        recent = await connection.fetch(
            f"""SELECT batch_id, row_count, content_sha256, kind, lo_id, hi_id FROM {schema}.batches
                WHERE symbol=$1 AND status='ACCEPTED' ORDER BY imported_at DESC, batch_id LIMIT $2""",
            symbol,
            max(0, verify_last),
        )
        verified = []
        for batch in recent:
            sha, rows = await _sha_of_query(
                connection, canonical_select(f"{schema}.agg_trades", "batch_id=$1"), batch["batch_id"]
            )
            ok = sha == batch["content_sha256"] and rows == batch["row_count"]
            verified.append({"batch_id": batch["batch_id"], "kind": batch["kind"], "rows": rows, "ok": ok})
            if not ok:
                problems.append(f"stored rows of batch {batch['batch_id'][:12]} no longer match its hash")
    if statuses.get("QUARANTINED"):
        problems.append(f"{statuses['QUARANTINED']} quarantined batch(es) need a person")
    if state["watermark"] is None:
        problems.append("no accepted batch yet")
    else:
        expected = state["start_id"]
        for row in chain:
            if int(row["lo_id"]) != expected:
                problems.append(f"accepted range chain broken at id {expected}")
                break
            expected = int(row["hi_id"]) + 1
        else:
            if expected - 1 != state["watermark"]:
                problems.append("accepted range chain does not end at the watermark")
    if last_import is None or now - last_import > max_age:
        problems.append(f"no accepted batch within {max_age}")
    open_ids = sum(b - a + 1 for a, b in state["holes"])
    if state["holes"]:
        warnings.append(f"{len(state['holes'])} open hole(s), {open_ids} trade ids missing on the source")
    lag = None
    if source_cursor_id is not None and state["watermark"] is not None:
        lag = int(source_cursor_id) - state["watermark"]
        if lag < 0:
            problems.append("archive watermark is ahead of the source cursor")
    disk = None
    if disk_path is not None:
        disk = disk_gate(disk_path, 0, usage=usage).as_dict()
        if not disk["passed"]:
            problems.append("archive disk below free-space gate")
    return {
        "mode": "OBSERVE",
        "status": "FAIL" if problems else ("WARN" if warnings else "OK"),
        "symbol": symbol,
        "schema": schema,
        "watermark": state["watermark"],
        "start_id": state["start_id"],
        "open_holes": len(state["holes"]),
        "open_hole_ids": open_ids,
        "batches_by_status": statuses,
        "last_accepted_import": last_import.isoformat() if last_import else None,
        "source_lag_ids": lag,
        "verified_batches": verified,
        "disk": disk,
        "problems": problems,
        "warnings": warnings,
        "checked_at": now.isoformat(),
    }
