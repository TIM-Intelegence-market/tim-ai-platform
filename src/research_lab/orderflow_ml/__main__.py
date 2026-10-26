"""S8 command line (lab only; no runtime database, no holdout, no S2 price files).

    python -m src.research_lab.orderflow_ml fetch --from 2020-01-01 --to 2024-12-31 [--raw-dir DIR]
    python -m src.research_lab.orderflow_ml export [--from ...] [--to ...] [--out DIR]
    python -m src.research_lab.orderflow_ml replay --decision 2021-03-01T12:00:00Z --export-dir DIR
    python -m src.research_lab.orderflow_ml crosscheck-s2 --s2-root data/research_lab/aggtrades

``--raw-dir`` serves already downloaded archives (and their .CHECKSUM files) by
file name instead of fetching them; the cloud cannot reach data.binance.vision.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from src.research_lab.data.aggtrades import DirectoryFetcher
from src.research_lab.data.store import http_fetch
from src.research_lab.orderflow_ml.export import ExportConfig, crosscheck_s2, replay, run_export
from src.research_lab.orderflow_ml.store import DEFAULT_ROOT, MinuteBarStore, days_between


def _code_version() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s8")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "export"):
        p = sub.add_parser(name)
        p.add_argument("--from", dest="first", default="2020-01-01")
        p.add_argument("--to", dest="last", default="2024-12-31")
        if name == "fetch":
            p.add_argument("--raw-dir")
            p.add_argument("--keep-raw", action="store_true")
        else:
            p.add_argument("--out")
    r = sub.add_parser("replay")
    r.add_argument("--decision", required=True, help="UTC time of the decision (minute end)")
    r.add_argument("--export-dir")
    r.add_argument("--from", dest="first", default="2020-01-01")
    r.add_argument("--to", dest="last", default="2024-12-31")
    c = sub.add_parser("crosscheck-s2")
    c.add_argument("--s2-root", required=True)
    args = parser.parse_args(argv)

    if args.cmd == "fetch":
        fetcher = DirectoryFetcher(Path(args.raw_dir)) if args.raw_dir else http_fetch
        store = MinuteBarStore(args.root, fetcher)
        for day in days_between(date.fromisoformat(args.first), date.fromisoformat(args.last)):
            entry = store.fetch(day, keep_raw=args.keep_raw)
            print(day.isoformat(), entry["quality"], flush=True)
        return 0
    store = MinuteBarStore(args.root)
    if args.cmd == "export":
        cfg = ExportConfig(date.fromisoformat(args.first), date.fromisoformat(args.last))
        split = run_export(store, cfg, args.out or Path(args.root) / "exports", code_version=_code_version())
        print(json.dumps({k: split[k] for k in ("export_id", "features_hash", "labels_hash", "input_dataset_hash")}, indent=2))
        return 0
    if args.cmd == "replay":
        cfg = ExportConfig(date.fromisoformat(args.first), date.fromisoformat(args.last))
        stamp = datetime.fromisoformat(args.decision.replace("Z", "+00:00")).astimezone(timezone.utc)
        print(json.dumps(replay(store, int(stamp.timestamp() * 1000), cfg, args.export_dir), indent=2, default=str))
        return 0
    from src.research_lab.data.aggtrades import AggTradeDayStore

    print(json.dumps(crosscheck_s2(store, AggTradeDayStore(args.s2_root), store.present_days()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
