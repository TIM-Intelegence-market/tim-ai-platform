"""INFRA-09 cold-state: archive state of a cold store, as input for ``export --server-state``.

While the archive lives only in a cold store (Mac first, no server database), the exporter still
needs ``{symbol, start_id, watermark, holes}``. This module derives exactly that from the store's
ledger and stored manifests, with the importer's own rules (``importer._placement`` and the hole
update after an accepted batch). It only reads; it never writes into the store.

Fail closed:

* The whole run holds the store's shared lock, so a running ingest makes it fail instead of
  reading a half-written store. A bound store must have its volume mounted and identified.
* The store must verify first (every file re-hashed, nothing unknown below ``batches/``).
* Every stored manifest is re-read and must match its ledger record byte for byte (sha256), the
  ledger fields, its data file record and its own batch_id (which binds kind, range, content
  and holes). Any mismatch stops the run and no state is printed.
* The resulting state must account for every applied row exactly:
  ``watermark - start_id + 1 - holes == sum(row_count)``; otherwise the run stops.

Batches that do not fit are not counted as archived (the state only under-claims, so the next
export repeats those ranges instead of skipping them) and are listed with the reason:
``STALE`` (range already covered), ``OUT_OF_ORDER`` (never connected) or ``INCOMPLETE``
(interrupted ingest: data file recorded without its manifest).

Not activated anywhere; nothing here runs on a schedule.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from src.archive_sync import importer
from src.archive_sync.cold_store import (
    ColdStore,
    _check_batch,
    _dir,
    _parse_manifest,
    _read_bytes,
    _safe_name,
    _safe_symbol,
)
from src.archive_sync.common import (
    ArchiveSyncError,
    batch_id_for,
    hole_size,
    normalise_holes,
    write_json_atomic,
)

STATE_MODE = "COLD_STATE"


def _apply(state: dict[str, Any], kind: str, lo: int, hi: int, holes: list[list[int]],
           hole: list[int] | None) -> None:
    """The importer's state update after an accepted batch (importer.import_batch), on a dict."""
    new_holes = [list(h) for h in state["holes"]]
    if kind == "new":
        if state["watermark"] is None:
            state["start_id"] = lo
        state["watermark"] = hi
    elif kind == "prefix":
        state["start_id"] = lo
    else:
        a, b = hole  # type: ignore[misc]
        new_holes.remove([a, b])
        if a < lo:
            new_holes.append([a, lo - 1])
        if hi < b:
            new_holes.append([hi + 1, b])
    state["holes"] = importer._merge(new_holes + [list(h) for h in holes])


def replay(batches: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply batches in ledger order as repeated importer runs would: a batch that does not connect
    yet is retried after every accepted one; a stale batch is never counted.

    Returns (state, applied, not_applied). Applied batches are disjoint by construction."""
    state: dict[str, Any] = {"start_id": None, "watermark": None, "holes": []}
    pending = list(batches)
    applied: list[dict[str, Any]] = []
    not_applied: list[dict[str, Any]] = []
    progress = True
    while pending and progress:
        progress = False
        waiting = []
        for batch in pending:
            placement, hole = importer._placement(batch["kind"], batch["lo"], batch["hi"], state)
            if placement == "fits":
                _apply(state, batch["kind"], batch["lo"], batch["hi"], batch["holes"], hole)
                applied.append(batch)
                progress = True
            elif placement == "stale":
                not_applied.append({**_brief(batch), "status": "STALE"})
            else:
                waiting.append(batch)
        pending = waiting
    not_applied += [{**_brief(batch), "status": "OUT_OF_ORDER"} for batch in pending]
    return state, applied, not_applied


def _brief(batch: dict[str, Any]) -> dict[str, Any]:
    return {k: batch[k] for k in ("manifest", "batch_id", "kind", "lo", "hi")}


def _stored_batches(store: ColdStore, symbol: str, *, deep: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Complete stored batches of ``symbol`` in ledger order, each cross-checked; and incomplete ones."""
    by_batch: dict[str, dict[str, dict[str, Any]]] = {}
    order: list[str] = []
    prefix = f"batches/{symbol}/"
    for entry in store.ledger():
        if not entry["path"].startswith(prefix):
            continue
        if entry.get("symbol") != symbol or not isinstance(entry.get("batch_id"), str):
            raise ArchiveSyncError(f"ledger record {entry['path']} lacks its symbol or batch_id")
        role = entry.get("role")
        if role not in ("data", "manifest"):
            raise ArchiveSyncError(f"ledger record {entry['path']} has no valid role")
        roles = by_batch.setdefault(entry["batch_id"], {})
        if entry["batch_id"] not in order:
            order.append(entry["batch_id"])
        if role in roles:
            raise ArchiveSyncError(f"batch {entry['batch_id']} is recorded twice as {role}")
        roles[role] = entry
    complete: list[dict[str, Any]] = []
    incomplete: list[dict[str, Any]] = []
    folder = store.root / "batches" / symbol
    for batch_id in order:
        roles = by_batch[batch_id]
        if set(roles) != {"data", "manifest"}:
            only = next(iter(roles.values()))
            incomplete.append({"manifest": None, "batch_id": batch_id, "kind": only.get("kind"),
                               "lo": only.get("lo"), "hi": only.get("hi"), "status": "INCOMPLETE",
                               "recorded": sorted(roles)})
            continue
        record, data = roles["manifest"], roles["data"]
        name = record["path"].rsplit("/", 1)[1]
        _safe_name(name)
        with _dir(folder) as folder_fd:
            raw = _read_bytes(name, folder_fd)
        if hashlib.sha256(raw).hexdigest() != record["sha256"] or len(raw) != int(record["bytes"]):
            raise ArchiveSyncError(f"stored manifest {name} differs from its ledger record")
        manifest = _parse_manifest(raw, name)
        lo, hi = int(manifest["lo"]), int(manifest["hi"])
        holes = normalise_holes(manifest["holes"], lo, hi)
        checks = (
            manifest["symbol"] == symbol,
            manifest["batch_id"] == batch_id,
            batch_id_for(manifest["kind"], symbol, lo, hi, manifest["content_sha256"], holes) == batch_id,
            all(e.get("kind") == manifest["kind"] and e.get("lo") == lo and e.get("hi") == hi
                and e.get("content_sha256") == manifest["content_sha256"] for e in (record, data)),
            data["path"] == prefix + manifest["file"],
            data["sha256"] == manifest["file_sha256"] and int(data["bytes"]) == int(manifest["file_bytes"]),
            int(manifest["row_count"]) == hi - lo + 1 - hole_size(holes),
            lo <= hi,
        )
        if not all(checks):
            raise ArchiveSyncError(f"stored batch {name} does not match its ledger records or its batch_id")
        if deep:
            _, problem = _check_batch(folder / name, manifest, symbol)
            if problem:
                raise ArchiveSyncError(f"stored batch {name}: {problem}")
        complete.append({"manifest": name, "batch_id": batch_id, "kind": manifest["kind"], "lo": lo, "hi": hi,
                         "holes": holes, "row_count": int(manifest["row_count"])})
    return complete, incomplete


def cold_state(store: ColdStore, symbol: str, *, deep: bool = False) -> dict[str, Any]:
    """Archive state of ``symbol`` in the store; the same keys as ``importer.server_state``."""
    _safe_symbol(symbol)
    with store._locked(shared=True):
        check = store._verify()
        if check["status"] != "OK":
            raise ArchiveSyncError(f"store does not verify ({len(check['problems'])} problems); no state given")
        batches, incomplete = _stored_batches(store, symbol, deep=deep)
        state, applied, not_applied = replay(batches)
        rows = sum(b["row_count"] for b in applied)
        if state["watermark"] is None:
            expected = 0
        else:
            expected = state["watermark"] - state["start_id"] + 1 - hole_size(state["holes"])
        if rows != expected:
            raise ArchiveSyncError(f"state accounts for {expected} trades, applied batches hold {rows}; no state given")
        used = check["used_bytes"]
        return {
            "mode": STATE_MODE,
            "status": "OK",
            "symbol": symbol,
            "start_id": state["start_id"],
            "watermark": state["watermark"],
            "holes": state["holes"],
            "archived_trades": rows,
            "batches_applied": len(applied),
            "not_applied": not_applied + incomplete,
            "files_verified": check["files"],
            "deep": deep,
            "volume": check["volume"],
            "used_bytes": used,
            "limit_bytes": store.limit_bytes,
            "remaining_bytes": max(0, store.limit_bytes - used),
        }


def write_state(report: dict[str, Any], out: str | Path, store_root: Path) -> Path:
    """Write the state for ``export --server-state``; never into the store itself."""
    path = Path(os.path.realpath(out))
    try:
        path.relative_to(os.path.realpath(store_root))
    except ValueError:
        write_json_atomic(path, report)
        return path
    raise ArchiveSyncError("state file must not be written inside the cold store")
