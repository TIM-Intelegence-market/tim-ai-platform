#!/usr/bin/env python3
"""Review a unified diff with the TIM Review Agent (report only, never an approval).

Usage:
    git diff origin/platform-main...HEAD | python scripts/tim_review_agent.py
    python scripts/tim_review_agent.py --diff-file change.diff --record-path review.json
    python scripts/tim_review_agent.py --replay review.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.contract import PolicyViolation, ReplayMismatch, RunRecord, replay, run_task  # noqa: E402
from src.agents.review import (  # noqa: E402
    INPUT_SCHEMA,
    READ_DIFF,
    SPEC,
    WRITE_REPORT,
    ReviewInputError,
    render_report,
    review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--diff-file", type=Path, help="unified diff to review (default: stdin)")
    parser.add_argument("--record-path", type=Path, help="write the replayable run record here")
    parser.add_argument("--replay", type=Path, metavar="RECORD", help="re-run a recorded review and verify it")
    args = parser.parse_args()
    try:
        if args.replay:
            record = RunRecord.from_dict(json.loads(args.replay.read_text(encoding="utf-8")))
            replay(SPEC, review, record)
            print(f"Replay OK: output {record.output_hash}")
            return 0
        diff = args.diff_file.read_text(encoding="utf-8") if args.diff_file else sys.stdin.read()
        record = run_task(SPEC, review, {"schema": INPUT_SCHEMA, "diff": diff}, action=READ_DIFF)
        if args.record_path:
            SPEC.authorize(WRITE_REPORT)
            args.record_path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8")
    except (OSError, ValueError, KeyError, ReviewInputError, PolicyViolation, ReplayMismatch) as error:
        print(f"Review agent stopped safely: {error}", file=sys.stderr)
        return 1
    print(render_report(record.to_dict()["output"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
