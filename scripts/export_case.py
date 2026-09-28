#!/usr/bin/env python3
"""Export one research case as verifiable JSON + standalone HTML.

Source is either a case JSON file (as served by /api/cases/<id>) or the
locally running dashboard. Read-only; writes only into --out.

    python3 scripts/export_case.py case_abc123 --out exports/
    python3 scripts/export_case.py --file case.json --out exports/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research.case_export import build_case_export, to_html, to_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("--file", type=Path, help="case JSON instead of the running dashboard")
    parser.add_argument("--dashboard", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, default=Path("exports"))
    args = parser.parse_args()
    if args.file:
        case = json.loads(args.file.read_text(encoding="utf-8"))
    elif args.case_id:
        with urlopen(f"{args.dashboard}/api/cases/{quote(args.case_id)}", timeout=10) as response:
            case = json.loads(response.read())
    else:
        parser.error("case_id or --file required")
    export = build_case_export(case, exported_at=datetime.now(timezone.utc))
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(export["case"]["case_id"])):
        parser.error("case_id contains characters not allowed in a file name")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / export["case"]["case_id"]
    stem.with_suffix(".json").write_text(to_json(export), encoding="utf-8")
    stem.with_suffix(".html").write_text(to_html(export), encoding="utf-8")
    print(f"{stem}.json\n{stem}.html\noutput_hash {export['output_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
