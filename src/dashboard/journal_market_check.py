"""Read-only: does every plan journal entry carry the market its source names? (R1, 16.11.2026)

Perp journals (``*perp*``, ``*xmr*``) must say USDM, the others SPOT. Entries written before 16.11.2026 keep their old
label (the journal is never rewritten); pass ``--since`` to look only at newer entries.
Usage: python -m src.dashboard.journal_market_check [DIR] [--since ISO_TIME]. Exit 1 on a mismatch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def expected(name: str) -> str:
    return "USDM" if ("perp" in name or "xmr" in name) else "SPOT"


def check(directory: Path, since: str = "") -> list[str]:
    problems: list[str] = []
    for path in sorted(directory.glob("tim_plan_journal*.json")):
        want = expected(path.name)
        for entry in json.loads(path.read_text(encoding="utf-8")).get("entries", []):
            if since and str(entry.get("created_at") or "") < since:
                continue
            got = entry.get("market_type")
            if got != want:
                problems.append(f"{path.name} {entry.get('id')}: market_type {got}, expected {want}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default="data/journal")
    parser.add_argument("--since", default="")
    args = parser.parse_args()
    problems = check(Path(args.directory), args.since)
    print(f"{len(problems)} Abweichungen")
    for line in problems[:50]:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
