#!/usr/bin/env python3
"""Launch the offline worker and attach the machine-wide 20% CPU ceiling."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
# This Mac exposes eight logical CPUs; 800 is cpulimit's full-machine ceiling.
LIMIT_PERCENT = 800


def main() -> int:
    worker = subprocess.Popen([sys.executable, str(ROOT / "scripts/run_coverage_worker.py")], cwd=ROOT)
    limiter = subprocess.Popen(
        ["/opt/homebrew/bin/cpulimit", "-l", str(LIMIT_PERCENT), "-i", "-p", str(worker.pid), "-z"]
    )
    status = worker.wait()
    try:
        limiter.wait(timeout=5)
    except subprocess.TimeoutExpired:
        limiter.terminate()
        limiter.wait(timeout=5)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
