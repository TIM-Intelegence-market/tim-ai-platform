"""Reproduce vol_4h.SIGMA_REF: median GARCH-4h sigma in validation 2023-2024 with the frozen S15 parameters.

Reads only the 5m data up to 2024-12 (the S15 store refuses the holdout) and the last fit of the
S15 result report. Writes docs/research_lab/reports/s15_sigma_ref_<date>.json and prints it.
Usage: python scripts/research_lab_s15_sigma_ref.py [--root DATA_ROOT]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore  # noqa: E402
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS  # noqa: E402
from src.research_lab.vol_4h import PARAMS, SOURCE_REPORT, WARMUP  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    spec = importlib.util.spec_from_file_location("research_lab_s15", Path(__file__).with_name("research_lab_s15.py"))
    s15_script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s15_script)
    series, _ = s15_script.load_periods(ArchiveStore(args.root))
    out = {}
    for symbol, periods in series["S15-4h"].items():
        omega, alpha, beta = PARAMS[symbol]
        rets = [p.ret for p in periods]
        h = statistics.fmean(r * r for r in rets[:WARMUP])
        sigmas = []
        for t, p in enumerate(periods):
            if t >= WARMUP and VALIDATION_START_MS <= p.start < HOLDOUT_START_MS:
                sigmas.append(math.sqrt(h))
            h = omega + alpha * rets[t] ** 2 + beta * h
        out[symbol] = {"n": len(sigmas), "median": round(statistics.median(sigmas), 4)}
    payload = {"created": datetime.now(timezone.utc).isoformat(), "params_from": SOURCE_REPORT, "warmup": WARMUP, "sigma_ref": out}
    path = Path("docs/research_lab/reports") / f"s15_sigma_ref_{datetime.now(timezone.utc):%Y-%m-%d}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
