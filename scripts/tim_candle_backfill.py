#!/usr/bin/env python3
"""Rebuild missing 1m candles in an explicit UTC window from stored raw aggTrades.

Dry run by default. ``--apply`` needs a recorded governance decision. Writes a versioned
manifest to data/operational/candle_backfill/. OBSERVE only, no orders.

Example:
  scripts/tim_candle_backfill.py --start 2026-10-01T00:00:00Z --end 2026-10-20T00:00:00Z
  scripts/tim_candle_backfill.py --start ... --end ... --apply \
      --approved-by Uzi --decision-ref <id> --approved-at 2026-10-20T11:10:19Z
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.operational.candle_backfill import Governance, parse_utc, run_backfill  # noqa: E402

CODE_FILES = ("src/operational/candle_backfill.py", "src/operational/history_recovery.py", "scripts/tim_candle_backfill.py")


def code_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, help="UTC, minute aligned, e.g. 2026-10-01T00:00:00Z")
    parser.add_argument("--end", required=True, help="UTC, exclusive")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--apply", action="store_true", help="write candles (default: dry run)")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--decision-ref", default="")
    parser.add_argument("--approved-at", default="")
    parser.add_argument("--output-dir", default=str(ROOT / "data/operational/candle_backfill"))
    args = parser.parse_args(argv)
    if args.apply and not (args.approved_by and args.decision_ref and args.approved_at):
        parser.error("--apply needs --approved-by, --decision-ref and --approved-at")
    return args


async def main_async(args: argparse.Namespace) -> dict:
    from config.settings import settings
    from src.database.connection import Database

    now = datetime.now(timezone.utc)
    governance = Governance(args.approved_by, args.decision_ref, args.approved_at) if args.apply else None
    database = Database(settings.database_url, min_size=1, max_size=1)
    await database.connect()
    try:
        return await run_backfill(
            database, (args.symbol or settings.symbol).upper(), parse_utc(args.start), parse_utc(args.end),
            now=now, apply=args.apply, governance=governance, code_hashes=code_hashes(),
        )
    finally:
        await database.close()


def main(argv: list[str] | None = None) -> int:
    import fcntl

    args = parse_args(argv)
    lock_path = ROOT / "data/operational/history_recovery.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"status":"ALREADY_RUNNING"}')
            return 3
        manifest = asyncio.run(main_async(args))
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = manifest["run_at_utc"].replace(":", "").replace("-", "").split(".")[0]
    path = out_dir / f"backfill-{manifest['mode'].lower()}-{stamp}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n")
    temporary.replace(path)
    print(json.dumps({"manifest": str(path), "mode": manifest["mode"], "manifest_sha256": manifest["manifest_sha256"],
                      **manifest["totals"]}, indent=2, default=str))
    return 0 if manifest["totals"]["not_rebuilt"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
