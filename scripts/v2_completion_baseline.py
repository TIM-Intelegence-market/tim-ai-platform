#!/usr/bin/env python3
"""Capture the read-only recovery point for the V2 finish-first program.

The output deliberately excludes passwords, password hashes, connection URLs,
environment values, SQL text from active sessions, and full process command
lines.  It is safe to commit as completion evidence.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import sys
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from config.settings import settings
from scripts.v2_readiness_audit import collect as collect_readiness


UTC = timezone.utc
PROGRAM_ID = "TIM-V2-FINISH-FIRST-20260801"
SOURCE_BRANCH = "codex/v2-final-readiness"
EXPECTED_SOURCE_COMMIT = "d347140620287613e3bac24d0b9412ba38206ca8"
COMPLETION_BRANCH = "codex/v2-finish-first"
FROZEN_START = datetime(2026, 7, 22, 20, 14, tzinfo=UTC)
PROTECTED_PATHS = (
    "config/core_manifest.json",
    "TIM_V2_READINESS_CHECKLIST.md",
    "data/research/snapshots/2026-07.in_progress.json",
    "data/research/status/tim_v1_readiness.json",
    "data/operational/state.json",
    "data/operational/validation_report.json",
    "graphify-out/graph.json",
)
RECOVERY_INPUTS = (
    "config/settings.py",
    "config/core_manifest.json",
    "config/governance_roles.json",
    "artifacts/v2_readiness/coverage_definition.json",
    "artifacts/v2_readiness/coverage_final.json",
    "artifacts/v2_readiness/data_gap_ledger.jsonl",
    "artifacts/v2_readiness/validated_case_audit.json",
    "artifacts/v2_readiness/manual_review_sample_manifest.json",
    "artifacts/v2_readiness/final_test_summary.json",
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(relative: str) -> dict[str, Any]:
    path = ROOT / relative
    if not path.is_file():
        return {"path": relative, "status": "ABSENT"}
    stat = path.stat()
    return {
        "path": relative,
        "status": "PRESENT",
        "size_bytes": stat.st_size,
        "sha256": sha256(path),
    }


def run(*args: str) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return result.stdout.strip()


def git(*args: str) -> str:
    return run("git", *args)


def safe_remote(value: str) -> str:
    if "://" not in value:
        return value
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def dashboard_snapshot(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=3) as response:
            value = json.loads(response.read())
            operational = value.get("operational", value.get("operational_health", {}))
            governance = value.get("governance", {})
            return {
                "http_status": response.status,
                "mode": value.get("mode"),
                "dashboard_version": value.get("dashboard_version"),
                "operational": operational,
                "governance": {
                    "observe_only": governance.get("observe_only", value.get("mode") == "OBSERVE"),
                    "trading_actions": governance.get("trading_actions", 0),
                },
            }
    except Exception as exc:  # evidence records the failure class, never content
        return {"http_status": None, "status": "UNAVAILABLE", "error_type": type(exc).__name__}


def port_probe(host: str, port: int) -> dict[str, Any]:
    started = now_utc()
    try:
        with socket.create_connection((host, port), timeout=2):
            reachable = True
            error = None
    except OSError as exc:
        reachable = False
        error = type(exc).__name__
    return {
        "host": host,
        "port": port,
        "reachable": reachable,
        "error_type": error,
        "tested_at_utc": iso(started),
    }


def local_lan_address() -> str | None:
    try:
        value = run("ipconfig", "getifaddr", "en0")
    except (OSError, subprocess.SubprocessError):
        return None
    return value or None


def launchd_record() -> dict[str, Any]:
    path = Path.home() / "Library/LaunchAgents/com.tim.runtime.plist"
    record: dict[str, Any] = {
        "label": "com.tim.runtime",
        "path": str(path),
        "exists": path.is_file(),
    }
    if path.is_file():
        record["sha256"] = sha256(path)
        try:
            payload = plistlib.loads(path.read_bytes())
            record.update(
                {
                    "program": payload.get("Program"),
                    "program_arguments": payload.get("ProgramArguments", []),
                    "working_directory": payload.get("WorkingDirectory"),
                    "run_at_load": payload.get("RunAtLoad"),
                    "keep_alive": payload.get("KeepAlive"),
                    "stdout_path": payload.get("StandardOutPath"),
                    "stderr_path": payload.get("StandardErrorPath"),
                    "environment_values_captured": False,
                }
            )
        except (OSError, ValueError, plistlib.InvalidFileException) as exc:
            record["parse_error_type"] = type(exc).__name__
    try:
        label = run("launchctl", "list", "com.tim.runtime")
        record["launchctl_registered"] = "com.tim.runtime" in label
        for line in label.splitlines():
            if '"PID"' in line and "=" in line:
                candidate = line.split("=", 1)[1].strip(" ;")
                if candidate.isdigit():
                    record["pid"] = int(candidate)
            if '"LastExitStatus"' in line and "=" in line:
                candidate = line.split("=", 1)[1].strip(" ;")
                if candidate.lstrip("-").isdigit():
                    record["last_exit_status"] = int(candidate)
    except (OSError, subprocess.SubprocessError):
        record["launchctl_registered"] = False
    return record


async def database_evidence(database_url: str) -> tuple[dict[str, Any], dict[str, Any]]:
    connection = await asyncpg.connect(database_url, timeout=5, command_timeout=60)
    try:
        settings_out: dict[str, Any] = {}
        for name in (
            "server_version",
            "listen_addresses",
            "port",
            "ssl",
            "password_encryption",
            "config_file",
            "hba_file",
            "data_directory",
        ):
            try:
                settings_out[name] = await connection.fetchval(f"SHOW {name}")
            except asyncpg.InsufficientPrivilegeError:
                settings_out[name] = "UNAVAILABLE_TO_TIM_ROLE"
        identity = dict(
            await connection.fetchrow(
                "SELECT current_user, current_database(), inet_server_addr()::text AS server_addr, inet_server_port() AS server_port"
            )
        )
        current_role = dict(
            await connection.fetchrow(
                """SELECT rolname, rolsuper, rolinherit, rolcreaterole,
                          rolcreatedb, rolcanlogin, rolreplication, rolbypassrls
                   FROM pg_roles WHERE rolname=current_user"""
            )
        )
        databases = [
            dict(row)
            for row in await connection.fetch(
                """SELECT datname, pg_get_userbyid(datdba) AS owner, datallowconn
                   FROM pg_database WHERE NOT datistemplate ORDER BY datname"""
            )
        ]
        roles = [
            dict(row)
            for row in await connection.fetch(
                """SELECT rolname, rolsuper, rolcreaterole, rolcreatedb,
                          rolcanlogin, rolreplication, rolbypassrls
                   FROM pg_roles ORDER BY rolname"""
            )
        ]
        activity = [
            dict(row)
            for row in await connection.fetch(
                """SELECT datname, usename, coalesce(application_name,'') AS application_name,
                          coalesce(client_addr::text,'LOCAL_SOCKET') AS client_addr,
                          state, count(*) AS sessions
                   FROM pg_stat_activity WHERE pid<>pg_backend_pid()
                   GROUP BY datname,usename,application_name,client_addr,state
                   ORDER BY datname,usename,application_name"""
            )
        ]
        hba: Any
        try:
            hba = [
                dict(row)
                for row in await connection.fetch(
                    """SELECT line_number,type,database,user_name,address,auth_method,error
                       FROM pg_hba_file_rules ORDER BY line_number"""
                )
            ]
        except asyncpg.InsufficientPrivilegeError:
            hba = {"status": "UNAVAILABLE_TO_TIM_ROLE"}
        columns = [
            dict(row)
            for row in await connection.fetch(
                """SELECT table_schema,table_name,column_name,ordinal_position,
                          data_type,is_nullable,column_default
                   FROM information_schema.columns
                   WHERE table_schema NOT IN ('pg_catalog','information_schema')
                   ORDER BY table_schema,table_name,ordinal_position"""
            )
        ]
        constraints = [
            dict(row)
            for row in await connection.fetch(
                """SELECT n.nspname AS schema_name,c.relname AS table_name,
                          con.conname AS constraint_name,con.contype::text AS constraint_type,
                          pg_get_constraintdef(con.oid,true) AS definition
                   FROM pg_constraint con
                   JOIN pg_class c ON c.oid=con.conrelid
                   JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname NOT IN ('pg_catalog','information_schema')
                   ORDER BY n.nspname,c.relname,con.conname"""
            )
        ]
        indexes = [
            dict(row)
            for row in await connection.fetch(
                """SELECT schemaname AS schema_name,tablename AS table_name,
                          indexname AS index_name,indexdef AS definition
                   FROM pg_indexes
                   WHERE schemaname NOT IN ('pg_catalog','information_schema')
                   ORDER BY schemaname,tablename,indexname"""
            )
        ]
        db_size = await connection.fetchval("SELECT pg_database_size(current_database())")
    finally:
        await connection.close()
    database = {
        "settings": settings_out,
        "identity": identity,
        "current_role": current_role,
        "databases": databases,
        "roles_without_password_metadata": roles,
        "active_sessions_without_query_text": activity,
        "hba_rules": hba,
        "database_size_bytes": db_size,
        "instance_classification": "UNKNOWN",
        "classification_reason": (
            "The service is a system-level PostgreSQL installation, the TIM role is not "
            "administrative, HBA/config paths are not readable, and exclusive TIM ownership "
            "cannot be proven. It must not be stopped as a dedicated instance."
        ),
        "password_values_captured": False,
        "password_hashes_captured": False,
        "active_query_text_captured": False,
    }
    schema = {
        "schema_dump_format": "INFORMATION_SCHEMA_AND_PG_CATALOG_JSON_V1",
        "captured_at_utc": iso(now_utc()),
        "columns": columns,
        "constraints": constraints,
        "indexes": indexes,
    }
    schema["content_sha256"] = hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return database, schema


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "artifacts/v2_completion"
    )
    parser.add_argument(
        "--docs-dir", type=Path, default=ROOT / "docs/v2_completion"
    )
    args = parser.parse_args()
    captured_at = now_utc()
    cutoff = captured_at.replace(second=0, microsecond=0)
    database, schema = await database_evidence(settings.database_url)
    readiness = await collect_readiness(
        SimpleNamespace(
            start=iso(FROZEN_START),
            end=iso(cutoff),
            label="baseline",
            output_dir=args.output_dir,
            downtime_evidence=ROOT / "artifacts/v2_readiness/system_downtime_evidence.json",
            database_url=settings.database_url,
            no_write=True,
        )
    )
    launchd = launchd_record()
    lan = local_lan_address()
    listener_before = {
        "captured_at_utc": iso(captured_at),
        "listen_addresses": database["settings"]["listen_addresses"],
        "port": int(database["settings"]["port"]),
        "ipv4_wildcard_detected": database["settings"]["listen_addresses"] == "*",
        "ipv6_wildcard_detected": database["settings"]["listen_addresses"] == "*",
        "localhost_probe": port_probe("127.0.0.1", 5432),
        "lan_probe": port_probe(lan, 5432) if lan else {"status": "NO_EN0_ADDRESS"},
        "ssl": database["settings"]["ssl"],
        "result": "FAIL" if database["settings"]["listen_addresses"] == "*" else "REQUIRES_ADMIN_VALIDATION",
    }
    dashboard = dashboard_snapshot("http://127.0.0.1:8765/api/health")
    repository = {
        "root": str(ROOT),
        "source_branch": SOURCE_BRANCH,
        "completion_branch": git("branch", "--show-current"),
        "head": git("rev-parse", "HEAD"),
        "expected_source_commit": EXPECTED_SOURCE_COMMIT,
        "head_matches_expected_source": git("rev-parse", "HEAD") == EXPECTED_SOURCE_COMMIT,
        "source_pre_change_worktree_status": "CLEAN_VERIFIED_BEFORE_BRANCH_CREATION",
        "source_pre_change_worktree_clean": True,
        "capture_time_tracked_worktree_clean": not bool(
            git("status", "--porcelain", "--untracked-files=no")
        ),
        "capture_time_note": (
            "Capture occurred after the completion branch and isolated implementation "
            "worktrees were opened; the source branch was independently verified clean first."
        ),
        "remote": safe_remote(git("remote", "get-url", "origin")),
        "source_remote_commit": git("rev-parse", f"refs/remotes/origin/{SOURCE_BRANCH}"),
    }
    baseline = {
        "schema_version": "1.0.0",
        "program_id": PROGRAM_ID,
        "captured_at_utc": iso(captured_at),
        "evidence_cutoff_utc": iso(cutoff),
        "mode": "OBSERVE",
        "trading_actions": 0,
        "core_state": "FROZEN",
        "repository": repository,
        "runtime": {
            "launchd": launchd,
            "dashboard_url": "http://127.0.0.1:8765",
            "dashboard_binding": "127.0.0.1:8765",
            "dashboard": dashboard,
            "ollama_tim_policy": "DISABLED_BY_POLICY",
            "durable_cursor_at_baseline": "ABSENT",
            "durable_outbox_at_baseline": "ABSENT",
        },
        "database": database,
        "postgres_listener_before": listener_before,
        "coverage": readiness["coverage"],
        "scientific_case_audit": readiness["cases"],
        "recovery_inputs": [file_record(path) for path in RECOVERY_INPUTS],
        "protected_state": [file_record(path) for path in PROTECTED_PATHS],
        "security_status": "FAIL — LAN EXPOSED; POSTGRES ADMIN ACTION REQUIRED",
        "v2_approved": False,
        "trading_approved": False,
    }
    implementation = {
        "schema_version": "1.0.0",
        "program_id": PROGRAM_ID,
        "updated_at_utc": iso(captured_at),
        "branch": repository["completion_branch"],
        "source_commit": repository["head"],
        "phase": "PHASE_0_RECOVERY_POINT_CAPTURED",
        "machine_work_status": "IN_PROGRESS",
        "security_status": "BLOCKED — POSTGRES ADMIN ACTION REQUIRED",
        "runtime_status": "REMEDIATION_IN_PROGRESS",
        "data_status": "REMEDIATION_IN_PROGRESS",
        "science_status": "PREREGISTRATION_AND_REVIEW_PACKAGE_IN_PROGRESS",
        "ui_status": "REMEDIATION_IN_PROGRESS",
        "mcp_status": "BLOCKED — EXTERNAL OPENAI ACTION REQUIRED",
        "qualification_campaign": "NOT_STARTED_SECURITY_GATE_FAILED",
        "v2_approved": False,
        "trading_approved": False,
        "next_safe_action": "Complete all non-privileged remediation and hand the idempotent security bundle to an authorized PostgreSQL administrator.",
    }
    atomic_json(args.output_dir / "recovery/database_schema_catalog_before.json", schema)
    atomic_json(args.output_dir / "recovery/roles_and_rights_before.json", {
        "captured_at_utc": iso(captured_at),
        "roles": database["roles_without_password_metadata"],
        "databases": database["databases"],
        "password_values_captured": False,
        "password_hashes_captured": False,
    })
    atomic_json(args.output_dir / "recovery/dashboard_baseline.json", dashboard)
    atomic_json(args.output_dir / "postgres_listener_before.json", listener_before)
    atomic_json(args.output_dir / "baseline_manifest.json", baseline)
    atomic_json(args.output_dir / "implementation_state.json", implementation)
    print(json.dumps({
        "output": str(args.output_dir / "baseline_manifest.json"),
        "branch": repository["completion_branch"],
        "head": repository["head"],
        "coverage": readiness["coverage"]["product_calculation"]["coverage"],
        "current_independent_cases": readiness["cases"]["current_cutoff_audit"]["strict_independent_30m_windows"],
        "postgres_listener": database["settings"]["listen_addresses"],
        "lan_reachable": listener_before["lan_probe"].get("reachable"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
