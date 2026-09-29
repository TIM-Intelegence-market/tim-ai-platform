#!/usr/bin/env python3
"""Write one read-only TIM health report (Monitoring Agent V1).

Usage:
    python scripts/tim_monitoring_agent.py --orchestration-state artifacts/orchestration/state.json
    python scripts/tim_monitoring_agent.py --readiness-manifest path/manifest.json --record-path health.json
    python scripts/tim_monitoring_agent.py --replay health.json

Exit code 0 means the report was written, whatever its status; it never
restarts, repairs or releases anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.contract import PolicyViolation, ReplayMismatch, RunRecord, replay, run_task  # noqa: E402
from src.agents.monitoring import (  # noqa: E402
    BUILD_REPORT,
    SPEC,
    WRITE_REPORT,
    assess,
    collect_snapshot,
    render_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orchestration-state", type=Path, help="orchestrator state.json to read")
    parser.add_argument("--readiness-manifest", type=Path, help="bugfixer readiness manifest to evaluate")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="repository root for the readiness gate")
    parser.add_argument("--no-tool-probes", action="store_true", help="skip agent_infra tool probes")
    parser.add_argument("--max-state-age", type=int, default=900, help="seconds before state.json counts as stale")
    parser.add_argument("--record-path", type=Path, help="write the replayable run record here")
    parser.add_argument("--replay", type=Path, metavar="RECORD", help="re-run a recorded report and verify it")
    args = parser.parse_args()
    try:
        if args.replay:
            record = RunRecord.from_dict(json.loads(args.replay.read_text(encoding="utf-8")))
            replay(SPEC, assess, record)
            print(f"Replay OK: output {record.output_hash}")
            return 0
        snapshot = collect_snapshot(
            orchestration_state=args.orchestration_state, readiness_manifest=args.readiness_manifest,
            repo_root=args.repo_root, probe_tools=not args.no_tool_probes,
            max_state_age_seconds=args.max_state_age)
        record = run_task(SPEC, assess, snapshot, action=BUILD_REPORT)
        if args.record_path:
            SPEC.authorize(WRITE_REPORT)
            args.record_path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8")
    except (OSError, ValueError, KeyError, PolicyViolation, ReplayMismatch) as error:
        print(f"Monitoring agent stopped safely: {error}", file=sys.stderr)
        return 1
    print(render_report(record.to_dict()["output"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
