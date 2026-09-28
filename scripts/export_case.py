#!/usr/bin/env python3
"""Export one research case as verifiable JSON + standalone HTML.

Source is either a case JSON file (as served by /api/cases/<id>) or the
locally running dashboard. Read-only; writes only into --out.

    python3 scripts/export_case.py case_abc123 --out exports/
    python3 scripts/export_case.py --file case.json --out exports/
    python3 scripts/export_case.py case_abc123 --history history.json   # history from a file

With a case_id the RETROSPECTIVE history is fetched from the dashboard
(/api/orderflow/history) unless --history or --no-history is given.
history.json: {"observations": [...orderflow observations...], "validations": [...orderflow validations...]}
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
from src.research.retrospective import case_retrospective  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("case_id", nargs="?")
    parser.add_argument("--file", type=Path, help="case JSON instead of the running dashboard")
    parser.add_argument("--dashboard", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, default=Path("exports"))
    parser.add_argument("--history", type=Path, help="orderflow observations + validations for the RETROSPECTIVE block")
    parser.add_argument("--no-history", action="store_true", help="export without RETROSPECTIVE block")
    args = parser.parse_args()
    if args.file:
        case = json.loads(args.file.read_text(encoding="utf-8"))
    elif args.case_id:
        with urlopen(f"{args.dashboard}/api/cases/{quote(args.case_id)}", timeout=10) as response:
            case = json.loads(response.read())
    else:
        parser.error("case_id or --file required")
    history = None
    if args.history:
        history = json.loads(args.history.read_text(encoding="utf-8"))
    elif args.case_id and not args.file and not args.no_history:
        with urlopen(f"{args.dashboard}/api/orderflow/history", timeout=10) as response:
            history = json.loads(response.read())
    retrospective = None
    if history is not None and not args.no_history:
        retrospective = case_retrospective(case, history.get("observations", []), history.get("validations", [])) or None
    export = build_case_export(case, exported_at=datetime.now(timezone.utc), retrospective=retrospective)
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
