"""Run the research lab on training and validation data (R4/R5).

Example:
    python scripts/research_lab_run.py --split train,validation
    python scripts/research_lab_run.py --split train,validation --only M3 --random-runs 1000

The holdout (R6) is refused here; it runs exactly once, later, after Uzi's go.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore  # noqa: E402
from src.research_lab.hypotheses.registry import VARIANTS  # noqa: E402
from src.research_lab.runner import RunConfig, commit_statuses, ensure_registered, run, write_report  # noqa: E402
from src.research_lab.stats.register import HypothesisRegister  # noqa: E402

REGISTER = Path("docs/research_lab/REGISTER.jsonl")
REPORTS = Path("docs/research_lab/reports")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", required=True)
    parser.add_argument("--only", help="comma-separated hypotheses, e.g. L1,M3 (the register still counts all 48)")
    parser.add_argument("--random-runs", type=int, default=10_000)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=REPORTS)
    parser.add_argument("--register", type=Path, default=REGISTER)
    parser.add_argument("--commit-register", action="store_true",
                        help="write final statuses into the register (only for the official run of all variants)")
    args = parser.parse_args(argv)
    if "holdout" in args.split.split(","):
        parser.error("holdout is R6 and runs exactly once after an explicit go; not available here")
    if set(args.split.split(",")) != {"train", "validation"}:
        parser.error("use --split train,validation")
    specs = VARIANTS
    if args.only:
        wanted = set(args.only.split(","))
        specs = tuple(s for s in VARIANTS if s.hypothesis in wanted)
        if args.commit_register:
            parser.error("--commit-register needs the full run without --only")
    register = HypothesisRegister(args.register)
    if args.commit_register:
        ensure_registered(register)  # a trial run leaves the register file untouched
    config = RunConfig(random_runs=args.random_runs)
    results, candidates, context = run(ArchiveStore(args.root), specs=specs, config=config,
                                       progress=lambda line: print(line, flush=True))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    report = write_report(args.out, results, candidates, context, config, register.m or len(VARIANTS), commit or "unknown")
    if args.commit_register:
        commit_statuses(register, results)
    print(f"report: {report}")
    print(f"candidates: {', '.join(candidates) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
