#!/usr/bin/env python3
"""Inventory a frozen legacy Module-A JSONL source without changing any files.

Prints JSON to stdout only. The expected SHA-256 must come from the independently
frozen source inventory. No database, service, secret provider or network access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.legacy_provenance import inventory_legacy_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--max-examples", type=int, default=50)
    args = parser.parse_args(argv)
    try:
        result = inventory_legacy_jsonl(args.input, expected_sha256=args.expected_sha256,
                                        max_examples=args.max_examples)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["source_binding"] == "MATCH" and result["documentation_status"] == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
