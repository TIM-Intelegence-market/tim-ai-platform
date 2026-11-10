"""OFX command line (PS5, paper only).

    python -m src.research_lab.ofx loop --bars <S8 root 1.2.0> --out <dir> [--configs 1000] [--filters 300] [--workers 16]

Ends after ``--configs`` configurations or when ``<out>/STOP`` exists; a new call continues where it stopped.

    python -m src.research_lab.ofx gesamt <out> <out> ... [--json <file>]

Joint view over several searches (PS5 + PS4, different seeds): sums the configurations and re-checks every
candidate against the joint multiple-testing threshold.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from src.research_lab.ofx.gesamt import combine
from src.research_lab.ofx.loop import (
    run_loop,
    store_engine_run,
    store_random_p,
    training_bounds,
)
from src.research_lab.ofx.trend import store_trend

TREND_LEAD_DAYS = 120


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ofx")
    sub = parser.add_subparsers(dest="cmd", required=True)
    lp = sub.add_parser("loop")
    lp.add_argument("--bars", required=True)
    lp.add_argument("--out", required=True, type=Path)
    lp.add_argument("--configs", type=int, default=1000)
    lp.add_argument("--filters", type=int, default=300)
    lp.add_argument("--workers", type=int, default=16)
    lp.add_argument("--seed", type=int, default=2026_11_10)
    gp = sub.add_parser("gesamt")
    gp.add_argument("outs", nargs="+", type=Path)
    gp.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "gesamt":
        joint = combine(args.outs)
        if args.json:
            args.json.write_text(json.dumps(joint, indent=1, sort_keys=True) + "\n")
        for run in joint["laeufe"]:
            print(f"{run['ordner']}: seed {run['seed']}, {run['configs_tried']} Konfigurationen")
        print(f"gesamt {joint['configs_gesamt']} Konfigurationen, t-Schwelle {joint['t_schwelle']}, "
              f"Kandidaten gemeinsam {joint['kandidaten']} von {len(joint['liste'])}")
        return 0
    first, last = training_bounds()
    args.out.mkdir(parents=True, exist_ok=True)
    # daily closes for the direction filters: lead days before the first training day up to the training end, never later
    trend = store_trend(args.bars, first - timedelta(days=TREND_LEAD_DAYS), last, args.out / "tagesschluss.json",
                        workers=args.workers)
    state = run_loop(args.out, store_engine_run(args.bars, args.workers), store_random_p(args.bars, args.workers),
                     configs=args.configs, filters_per_config=args.filters, seed=args.seed,
                     log=lambda s: print(s, flush=True), trend=trend)
    print(state, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
