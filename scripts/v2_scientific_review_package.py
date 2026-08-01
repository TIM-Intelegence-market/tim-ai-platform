#!/usr/bin/env python3
"""Materialize the completion case audit and unsigned human review workbook."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v2_completion.independent_cases import (
    build_completion_audit,
    build_review_workbook,
    validate_review_workbook,
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
        "--baseline", type=Path,
        default=ROOT / "artifacts/v2_completion/baseline_manifest.json",
    )
    parser.add_argument(
        "--preregistration", type=Path,
        default=ROOT / "artifacts/v2_completion/qualification_preregistration.json",
    )
    parser.add_argument(
        "--sample", type=Path,
        default=ROOT / "artifacts/v2_readiness/manual_review_sample_manifest.json",
    )
    parser.add_argument(
        "--audit-output", type=Path,
        default=ROOT / "artifacts/v2_completion/independent_case_audit.json",
    )
    parser.add_argument(
        "--workbook-output", type=Path,
        default=ROOT / "artifacts/v2_completion/manual_review_workbook.json",
    )
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    prereg = json.loads(args.preregistration.read_text(encoding="utf-8"))
    sample = json.loads(args.sample.read_text(encoding="utf-8"))
    audit = build_completion_audit(baseline=baseline, preregistration=prereg)
    workbook = build_review_workbook(sample)
    check = validate_review_workbook(workbook)
    atomic_json(args.audit_output, audit)
    atomic_json(args.workbook_output, workbook)
    print(json.dumps({
        "audit_output": str(args.audit_output),
        "workbook_output": str(args.workbook_output),
        "frozen_independent": audit["frozen"]["strict_independent_units"],
        "current_independent": audit["current"]["strict_independent_units"],
        "qualification_independent": audit["qualification"]["strict_independent_units"],
        "selected_for_manual_review": check["selected_count"],
        "human_decisions": check["complete_human_decisions"],
        "human_approval": check["approval"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
