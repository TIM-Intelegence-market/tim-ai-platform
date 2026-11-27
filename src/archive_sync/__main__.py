"""Manual command line for the archive sync (S1). Nothing here runs on a schedule.

Connection strings come only from the environment, never from arguments or output:
``TIM_ARCHIVE_SOURCE_URL`` (Mac, read-only use) and ``TIM_ARCHIVE_TARGET_URL`` (server).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from src.archive_sync.common import DEFAULT_SCHEMA, ArchiveSyncError


def _url(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ArchiveSyncError(f"{name} is not set; no fallback to the runtime database is used")
    return value


async def _connect(name: str) -> Any:
    import asyncpg

    return await asyncpg.connect(_url(name))


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    from src.archive_sync import exporter, health, importer, transfer

    if args.command == "export":
        state = json.loads(Path(args.server_state).read_text(encoding="utf-8"))
        connection = await _connect("TIM_ARCHIVE_SOURCE_URL")
        try:
            return await exporter.export_batches(
                connection,
                symbol=args.symbol,
                out_dir=args.out,
                server_state=state,
                source_schema=args.source_schema,
                chunk=args.chunk,
                max_batches=args.max_batches,
            )
        finally:
            await connection.close()
    if args.command.startswith("cold-"):
        from src.archive_sync import cold_store

        if args.command == "cold-init":
            store = cold_store.ColdStore.init(args.root, limit_bytes=int(args.limit_gib * 1024**3),
                                              volume_mount=args.volume, parent=args.parent, image=args.image)
            return {"root": str(store.root), "limit_bytes": store.limit_bytes, "initialised": True,
                    "volume": store.volume}
        store = cold_store.ColdStore(args.root)
        if store.volume is None and not args.unbound_ok:
            raise ArchiveSyncError("store is not bound to a mounted volume; refusing (use --unbound-ok only for local tests)")
        if args.command == "cold-ingest":
            return store.ingest_directory(args.dir, symbol=args.symbol)
        if args.command == "cold-verify":
            return store.verify()
        if args.command == "cold-migrate":
            return cold_store.migrate_store(args.root, args.to, volume_mount=args.volume, parent=args.parent)
    if args.command == "transfer":
        target: Any
        if args.local_target:
            target = transfer.LocalDirTarget(Path(args.local_target))
        else:
            target = transfer.SshTarget(host=args.host, remote_dir=args.remote_dir, key=args.key, port=args.port)
        return transfer.transfer_directory(args.dir, target, symbol=args.symbol)
    connection = await _connect("TIM_ARCHIVE_TARGET_URL")
    try:
        if args.command == "init":
            requested = await importer.layout_for_new_schema(connection, args.schema, args.layout)
            layout = await importer.ensure_schema(connection, args.schema, requested)
            return {"schema": args.schema, "initialised": True, "layout": layout}
        if args.command == "state":
            return await importer.server_state(connection, args.symbol, args.schema)
        if args.command == "import":
            return await importer.import_directory(
                connection, args.dir, symbol=args.symbol, gate_path=args.gate_path, schema=args.schema,
                layout=await importer.layout_for_new_schema(connection, args.schema),
            )
        if args.command == "health":
            return await health.archive_health(
                connection,
                symbol=args.symbol,
                schema=args.schema,
                max_age=timedelta(hours=args.max_age_hours),
                verify_last=args.verify_last,
                disk_path=args.gate_path,
                source_cursor_id=args.source_cursor_id,
            )
    finally:
        await connection.close()
    raise ArchiveSyncError(f"unknown command {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.archive_sync", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="Mac: read-only export of new and backfilled ranges")
    export.add_argument("--symbol", required=True)
    export.add_argument("--out", required=True)
    export.add_argument("--server-state", required=True, help="JSON written by the 'state' command")
    export.add_argument("--source-schema", default="public")
    export.add_argument("--chunk", type=int, default=500_000)
    export.add_argument("--max-batches", type=int, default=10)
    send = sub.add_parser("transfer", help="send batch files, resumable, sha256-verified")
    send.add_argument("--symbol", required=True)
    send.add_argument("--dir", required=True)
    send.add_argument("--local-target")
    send.add_argument("--host")
    send.add_argument("--remote-dir")
    send.add_argument("--key")
    send.add_argument("--port", type=int)
    cold = sub.add_parser("cold-init", help="interim file archive with a hard byte budget (INFRA-09 draft)")
    cold.add_argument("--root", required=True)
    cold.add_argument("--limit-gib", type=float, required=True,
                      help="hard budget in GiB (1 GiB = 1024^3 bytes); always explicit, e.g. 26 for the 32 GiB volume")
    cold.add_argument("--volume", help="mounted file system the store is bound to (checked before every write)")
    cold.add_argument("--parent", help="parent file system that must keep 15%% free")
    cold.add_argument("--image", help="image file behind the volume; must stay fully allocated (not sparse)")
    cold = sub.add_parser("cold-ingest", help="verify batch files and store them, stop at the budget")
    cold.add_argument("--root", required=True)
    cold.add_argument("--unbound-ok", action="store_true", help=argparse.SUPPRESS)
    cold.add_argument("--dir", required=True)
    cold.add_argument("--symbol", required=True)
    cold = sub.add_parser("cold-verify", help="re-hash every stored file")
    cold.add_argument("--root", required=True)
    cold.add_argument("--unbound-ok", action="store_true", help=argparse.SUPPRESS)
    cold = sub.add_parser("cold-migrate", help="copy the store to a new empty root and verify it there")
    cold.add_argument("--root", required=True)
    cold.add_argument("--to", required=True)
    cold.add_argument("--volume")
    cold.add_argument("--parent")
    cold.add_argument("--unbound-ok", action="store_true", help=argparse.SUPPRESS)
    for name, text in (
        ("init", "server: create the archive schema"),
        ("state", "server: watermark and open holes"),
        ("import", "server: verify and import received batches"),
        ("health", "server: archive health check"),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("--schema", default=DEFAULT_SCHEMA)
        if name != "init":
            command.add_argument("--symbol", required=True)
        else:
            command.add_argument("--layout", choices=("v1", "v2"), help="only for a new schema; default v2 (an existing schema keeps its layout)")
        if name == "import":
            command.add_argument("--dir", required=True)
        if name in ("import", "health"):
            command.add_argument("--gate-path", required=name == "import")
        if name == "health":
            command.add_argument("--max-age-hours", type=float, default=30.0)
            command.add_argument("--verify-last", type=int, default=3)
            command.add_argument("--source-cursor-id", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "transfer" and not args.local_target and not (args.host and args.remote_dir):
        print(json.dumps({"error": "transfer needs --local-target or --host and --remote-dir"}))
        return 2
    try:
        report = asyncio.run(_run(args))
    except ArchiveSyncError as error:
        print(json.dumps({"error": str(error)}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    if args.command == "health":
        return 0 if report.get("status") in ("OK", "WARN") else 1
    if args.command == "cold-ingest":
        return 0 if report.get("halted") is None else 1
    if args.command in ("cold-verify", "cold-migrate"):
        return 0 if report.get("status") == "OK" else 1
    if args.command == "import":
        return 1 if report["summary"].get("QUARANTINED") or report["summary"].get("FILE_INVALID") else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
