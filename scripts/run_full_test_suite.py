#!/usr/bin/env python3
"""Run pytest once with durable evidence and a bounded process group."""

from __future__ import annotations

import argparse
import asyncio
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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings


def repository_root() -> Path:
    return ROOT


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


def pytest_warning_count(output: str) -> int:
    summary = re.search(r"(\d+) warnings? in [^\n]+", output)
    if summary is not None:
        return int(summary.group(1))
    values = [int(value) for value in re.findall(r"(\d+) warnings?", output)]
    return max(values, default=0)


ISOLATED_SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
PROTECTED_SCHEMAS = {"public", "pg_catalog", "information_schema"}


def validate_isolated_schema(schema: str) -> None:
    if schema in PROTECTED_SCHEMAS or not ISOLATED_SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError("isolated schema must be a safe lowercase PostgreSQL identifier")


def isolated_database_url(database_url: str, schema: str) -> str:
    validate_isolated_schema(schema)
    parsed = urlsplit(database_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema}"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


async def create_isolated_schema(database_url: str, schema: str) -> None:
    validate_isolated_schema(schema)
    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=30)
    try:
        exists = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.schemata WHERE schema_name=$1)",
            schema,
        )
        if exists:
            raise RuntimeError(f"isolated test schema already exists: {schema}")
        await connection.execute(f'CREATE SCHEMA "{schema}" AUTHORIZATION CURRENT_USER')
    finally:
        await connection.close()


async def drop_isolated_schema(database_url: str, schema: str) -> None:
    validate_isolated_schema(schema)
    connection = await asyncpg.connect(database_url, timeout=10, command_timeout=30)
    try:
        await connection.execute(f'DROP SCHEMA "{schema}" CASCADE')
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--label", default="full_suite")
    parser.add_argument("--isolated-schema")
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
    base_database_url = env.get("TIM_DATABASE_URL", settings.database_url)
    isolated_schema_created = False
    isolated_schema_cleaned = False
    if args.isolated_schema:
        asyncio.run(create_isolated_schema(base_database_url, args.isolated_schema))
        isolated_schema_created = True
        env["TIM_DATABASE_URL"] = isolated_database_url(base_database_url, args.isolated_schema)
    command = [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit}", *args.pytest_args]
    started = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    timed_out = False
    try:
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
    finally:
        if isolated_schema_created:
            asyncio.run(drop_isolated_schema(base_database_url, args.isolated_schema))
            isolated_schema_cleaned = True
    finished = datetime.now(timezone.utc)
    output = stdout_path.read_text(encoding="utf-8", errors="replace") + stderr_path.read_text(encoding="utf-8", errors="replace")
    counts = junit_counts(junit)
    warning_count = pytest_warning_count(output)
    summary = {
        "command": " ".join(command), "python_version": sys.version.split()[0], "pytest_version": pytest_version(sys.executable, env),
        "started_at": started.isoformat(), "finished_at": finished.isoformat(), "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "exit_code": return_code, **counts, "warnings": warning_count,
        "complete": not timed_out and return_code is not None, "timed_out": timed_out, "temporary_directory": str(tmpdir),
        "database_isolation": {
            "schema": args.isolated_schema,
            "created": isolated_schema_created,
            "cleaned": isolated_schema_cleaned,
            "production_schema_used_by_tests": False if args.isolated_schema else None,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 124 if timed_out else return_code


if __name__ == "__main__":
    raise SystemExit(main())
