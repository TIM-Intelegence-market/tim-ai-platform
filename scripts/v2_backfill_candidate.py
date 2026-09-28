#!/usr/bin/env python3
"""Build V2_BACKFILL_CANDIDATE_V1 from official, checksum-bound archives."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.backfill_candidate import (
    add_fixed_window_coverage,
    build_candidate,
    load_gap_windows,
)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gap-ledger",
        type=Path,
        default=ROOT / "artifacts/v2_readiness/data_gap_ledger.jsonl",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "artifacts/v2_completion/baseline_manifest.json",
    )
    parser.add_argument(
        "--quarantine-root",
        type=Path,
        default=ROOT / "data/v2_completion/backfill_quarantine",
    )
    parser.add_argument(
        "--candidate-root",
        type=Path,
        default=ROOT / "data/v2_completion/backfill_candidate/V2_BACKFILL_CANDIDATE_V1",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/v2_completion/backfill_candidate_manifest.json",
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    gaps = load_gap_windows(args.gap_ledger)
    manifest = build_candidate(
        gaps=gaps,
        quarantine_root=args.quarantine_root,
        candidate_root=args.candidate_root,
        timeout=args.timeout,
    )
    add_fixed_window_coverage(
        manifest, json.loads(args.baseline.read_text(encoding="utf-8"))
    )
    atomic_json(args.output, manifest)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "dataset_id": manifest["dataset_id"],
                "archives_imported": sum(
                    item["status"] == "IMPORTED_TO_IMMUTABLE_CANDIDATE"
                    for item in manifest["archives"]
                ),
                "candidate_minutes": manifest["candidate_minutes"],
                "remaining_gap_minutes": manifest["remaining_gap_minutes"],
                "readiness_counted": manifest["readiness_counted"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
