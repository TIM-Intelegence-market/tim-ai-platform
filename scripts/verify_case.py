#!/usr/bin/env python3
"""Verify an exported research case: recompute output_hash from its content.

    python3 scripts/verify_case.py case_abc123.json

Exit code 0 = content matches the hash, 1 = mismatch or unreadable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research.case_export import verify_case_export  # noqa: E402


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 1
    try:
        export = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"FEHLER: nicht lesbar ({exc})")
        return 1
    if isinstance(export, dict) and verify_case_export(export):
        print(f"OK: Inhalt stimmt mit output_hash {export['output_hash']} überein")
        return 0
    print("FEHLER: Inhalt stimmt NICHT mit output_hash überein")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
