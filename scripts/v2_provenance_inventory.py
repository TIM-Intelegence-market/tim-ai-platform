#!/usr/bin/env python3
"""Read-only provenance inventory for V2-B05. Writes only the --output file."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.research_ops.audit import parse_time  # noqa: E402
from src.v2_completion.provenance_inventory import build_inventory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="TIM checkout with data/research (e.g. ~/TIM-live)")
    parser.add_argument("--cutoff", help="ISO time, default now (UTC)")
    parser.add_argument("--boundary", help="ISO time of the V2 boundary; default: first record with all V2 fields")
    parser.add_argument("--output", type=Path, help="write JSON here (outside data/research)")
    args = parser.parse_args()
    cutoff = parse_time(args.cutoff) if args.cutoff else datetime.now(timezone.utc)
    boundary = parse_time(args.boundary) if args.boundary else None
    if cutoff is None or (args.boundary and boundary is None):
        parser.error("times must be ISO 8601 with time zone")
    inventory = build_inventory(args.root, cutoff=cutoff, boundary=boundary)
    text = json.dumps(inventory, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        if "data/research" in args.output.resolve().as_posix():
            parser.error("output must not be inside data/research")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(json.dumps({k: inventory[k] for k in ("cutoff", "v2_boundary", "bytes_unchanged")} | {"module_a_cache": inventory["module_a_cache"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
