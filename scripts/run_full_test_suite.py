#!/usr/bin/env python3
"""Run pytest once with durable evidence and a bounded process group."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def pytest_version(python: str, env: dict[str, str]) -> str:
    result = subprocess.run([python, "-m", "pytest", "--version"], text=True, capture_output=True, check=True, env=env)
    return result.stdout.strip()


def junit_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {key: 0 for key in ("passed", "failed", "skipped", "xfailed", "xpassed")}
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = failures = errors = skipped = 0
    for suite in suites:
        tests += int(suite.attrib.get("tests", 0))
        failures += int(suite.attrib.get("failures", 0))
        errors += int(suite.attrib.get("errors", 0))
        skipped += int(suite.attrib.get("skipped", 0))
    return {"passed": max(0, tests - failures - errors - skipped), "failed": failures + errors, "skipped": skipped, "xfailed": 0, "xpassed": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--label", default="full_suite")
    parser.add_argument("pytest_args", nargs="*")
    args = parser.parse_args()
    root = repository_root()
    reports = root / "artifacts" / "test_reports"
    reports.mkdir(parents=True, exist_ok=True)
    prefix = args.label
    junit = reports / f"{prefix}.junit.xml"
    stdout_path = reports / f"{prefix}.stdout.log"
    stderr_path = reports / f"{prefix}.stderr.log"
    summary_path = reports / f"{prefix}_summary.json"
    tmpdir = Path(tempfile.mkdtemp(prefix="tim-pytest-"))
    env = os.environ.copy()
    env.update({"TMPDIR": str(tmpdir), "TMP": str(tmpdir), "TEMP": str(tmpdir)})
    command = [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}", *args.pytest_args]
    started = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    timed_out = False
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(command, cwd=root, env=env, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            return_code = process.wait(timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                return_code = process.wait()
    finished = datetime.now(timezone.utc)
    output = stdout_path.read_text(encoding="utf-8", errors="replace") + stderr_path.read_text(encoding="utf-8", errors="replace")
    counts = junit_counts(junit)
    warnings_match = re.search(r"(\d+) warnings?", output)
    summary = {
        "command": " ".join(command), "python_version": sys.version.split()[0], "pytest_version": pytest_version(sys.executable, env),
        "started_at": started.isoformat(), "finished_at": finished.isoformat(), "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "exit_code": return_code, **counts, "warnings": int(warnings_match.group(1)) if warnings_match else 0,
        "complete": not timed_out and return_code is not None, "timed_out": timed_out, "temporary_directory": str(tmpdir),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 124 if timed_out else return_code


if __name__ == "__main__":
    raise SystemExit(main())
