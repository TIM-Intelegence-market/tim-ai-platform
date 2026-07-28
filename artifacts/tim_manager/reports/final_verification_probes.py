from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASELINE = Path(
    "/Users/tim/Documents/TIM/backups/"
    "tim_pre_intelligence_manager_20260728T072133Z/protected_data_hashes.txt"
)
PARENT_COMMIT = "a418894d33ba2426afe0f31d119332043bddd406"
PROTECTED_PROBES = (
    "data/operational/runtime_launchd.err.log",
    "data/research/module_a_cache.jsonl",
    "data/research/trigger_events.jsonl",
    "data/research/trigger_state.json",
    "artifacts/provenance/TIM-V1-UNFREEZE-20260727T170852Z.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def baseline_entries() -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []
    for line in BASELINE.read_text(encoding="utf-8").splitlines():
        expected, relative = line.split(maxsplit=1)
        entries.append((expected, PROJECT_ROOT / relative))
    return entries


def protected_digest() -> str:
    digest = hashlib.sha256()
    for _, path in baseline_entries():
        digest.update(path.relative_to(PROJECT_ROOT).as_posix().encode("utf-8"))
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def check_protected() -> int:
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.tim_manager.security import assert_write_allowed

    same = 0
    changed = 0
    missing = 0
    for expected, path in baseline_entries():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        if not path.is_file():
            print(f"MISSING\t{relative}")
            missing += 1
            continue
        actual = sha256(path)
        if actual == expected:
            same += 1
        else:
            changed += 1
            stat = path.stat()
            modified_at = datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat()
            print(
                f"CHANGED\t{relative}\t{expected}\t{actual}"
                f"\t{stat.st_size}\t{modified_at}"
            )

    denied = 0
    for relative in PROTECTED_PROBES:
        try:
            assert_write_allowed(PROJECT_ROOT / relative)
            print(f"UNEXPECTED_ALLOWED\t{relative}")
        except PermissionError as exc:
            denied += 1
            print(f"DENIED\t{relative}\t{exc}")

    print(
        f"SUMMARY\tsame={same}\tchanged={changed}\tmissing={missing}"
        f"\tdenied={denied}\tprobes={len(PROTECTED_PROBES)}"
    )
    return 0 if (same, changed, missing, denied) == (44, 4, 0, 5) else 1


def check_mcp() -> int:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "tim_get_status", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "tim_get_module_status",
                "arguments": {"module_id": "orderflow"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "tim_get_risks", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "tim_get_source_health", "arguments": {}},
        },
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "tim_search", "arguments": {"query": "orderflow"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "tim_query",
                "arguments": {"question": "How is Orderflow?"},
            },
        },
        {"jsonrpc": "2.0", "id": 9, "method": "resources/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "resources/read",
            "params": {"uri": "tim://snapshot/current"},
        },
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "write",
            "params": {"path": "data/forbidden"},
        },
    ]
    expected_tools = (
        "tim_get_status",
        "tim_get_module_status",
        "tim_get_risks",
        "tim_get_source_health",
        "tim_search",
        "tim_query",
    )
    database = PROJECT_ROOT / "artifacts/tim_manager/indexes/tim_manager.sqlite3"
    protected_before = protected_digest()
    database_before = (sha256(database), database.stat().st_size, database.stat().st_mtime_ns)
    payload = "".join(json.dumps(item) + "\n" for item in requests)
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv/bin/python"),
            "-m",
            "src.tim_manager.cli",
            "serve-mcp",
        ],
        cwd=PROJECT_ROOT,
        input=payload,
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    protected_after = protected_digest()
    database_after = (sha256(database), database.stat().st_size, database.stat().st_mtime_ns)
    tools = tuple(item["name"] for item in responses[1]["result"]["tools"])
    write_capabilities = tuple(
        name
        for name in tools
        if any(token in name.casefold() for token in ("write", "set", "create", "delete", "update"))
    )
    write_error = responses[10]["error"]["code"]
    resource = responses[8]["result"]["resources"][0]["uri"]
    print(f"SERVER_EXIT\t{process.returncode}")
    print(f"RESPONSE_COUNT\t{len(responses)}")
    print(f"TOOLS\t{','.join(tools)}")
    print(f"WRITE_CAPABILITIES\t{len(write_capabilities)}")
    print(f"RESOURCE\t{resource}")
    print(f"WRITE_METHOD_ERROR\t{write_error}")
    print(f"PROTECTED_BEFORE\t{protected_before}")
    print(f"PROTECTED_AFTER\t{protected_after}")
    print(f"PROTECTED_IDENTICAL\t{protected_before == protected_after}")
    print(f"DATABASE_SHA256_BEFORE\t{database_before[0]}")
    print(f"DATABASE_SHA256_AFTER\t{database_after[0]}")
    print(f"DATABASE_STAT_IDENTICAL\t{database_before[1:] == database_after[1:]}")
    valid = (
        process.returncode == 0
        and len(responses) == len(requests)
        and tools == expected_tools
        and not write_capabilities
        and resource == "tim://snapshot/current"
        and write_error == -32601
        and protected_before == protected_after
        and database_before == database_after
    )
    return 0 if valid else 1


def check_schema() -> int:
    import jsonschema

    schema_path = PROJECT_ROOT / "schemas/tim_manager/project_snapshot.schema.json"
    current = PROJECT_ROOT / "artifacts/tim_manager/snapshots/current.json"
    current_data = json.loads(current.read_text(encoding="utf-8"))
    snapshot = (
        PROJECT_ROOT
        / "artifacts/tim_manager/snapshots"
        / f"{current_data['snapshot_id']}.json"
    )
    exported = (
        PROJECT_ROOT
        / "artifacts/tim_manager/reports/final_acceptance_snapshot_export.json"
    )
    legacy = (
        PROJECT_ROOT
        / "artifacts/tim_manager/snapshots/d3102d52-0073-589c-831a-56fdce53e722.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    for path in (current, snapshot, exported):
        jsonschema.validate(json.loads(path.read_text(encoding="utf-8")), schema)
    jsonschema.validate(json.loads(legacy.read_text(encoding="utf-8")), schema)
    hashes = tuple(sha256(path) for path in (current, snapshot, exported))
    print(f"JSONSCHEMA_VERSION\t{importlib.metadata.version('jsonschema')}")
    print(f"VALIDATED_FILES\t3")
    print("LEGACY_SCHEMA_1_0_VALID\tTrue")
    print(f"SHA256\t{','.join(hashes)}")
    print(f"IDENTICAL\t{len(set(hashes)) == 1}")
    return 0 if len(set(hashes)) == 1 else 1


def check_provenance() -> int:
    snapshot_path = PROJECT_ROOT / "artifacts/tim_manager/snapshots/current.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    scan_path = (
        PROJECT_ROOT
        / "artifacts/tim_manager/scans"
        / f"{snapshot['provenance']['scan_id']}.json"
    )
    scan = json.loads(scan_path.read_text(encoding="utf-8"))
    manifest = [
        {
            "source_id": item["source_id"],
            "normalized_path": item["normalized_path"],
            "content_hash": item["content_hash"],
            "size_bytes": item["size_bytes"],
            "status": item["status"],
        }
        for item in sorted(
            scan["artifacts"],
            key=lambda item: (item["source_id"], item["normalized_path"]),
        )
    ]
    manifest_json = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    reproduced_manifest_hash = hashlib.sha256(
        manifest_json.encode("utf-8")
    ).hexdigest()
    git_root = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    parent_commit = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    tracked = subprocess.run(
        ["git", "-C", "/Users/tim", "ls-files", "--", "Documents/TIM/tim"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.splitlines()
    database = PROJECT_ROOT / "artifacts/tim_manager/indexes/tim_manager.sqlite3"
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        artifact_count = connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
        commit_count = connection.execute(
            """
            SELECT COUNT(*) FROM artifacts
            WHERE json_extract(record_json, '$.provenance.repository_commit') IS NOT NULL
            """
        ).fetchone()[0]
        authoritative_count = connection.execute(
            """
            SELECT COUNT(*) FROM artifacts
            WHERE json_extract(
                record_json,
                '$.provenance.authoritative_git_repository'
            ) = 1
            """
        ).fetchone()[0]
        parent_context_count = connection.execute(
            """
            SELECT COUNT(*) FROM artifacts
            WHERE json_extract(
                record_json,
                '$.provenance.parent_git_context.commit'
            ) = ?
            """,
            (PARENT_COMMIT,),
        ).fetchone()[0]
    finally:
        connection.close()
    result = {
        "tim_dot_git": (PROJECT_ROOT / ".git").exists(),
        "parent_git_root": git_root,
        "parent_commit": parent_commit,
        "tracked_tim_files": len(tracked),
        "repository_status": snapshot["repository_status"],
        "repository_commit": snapshot["repository_commit"],
        "authoritative_git_repository": snapshot["authoritative_git_repository"],
        "content_manifest_hash": snapshot["content_manifest_hash"],
        "reproduced_content_manifest_hash": reproduced_manifest_hash,
        "sqlite_artifact_count": artifact_count,
        "sqlite_non_null_repository_commit": commit_count,
        "sqlite_authoritative_true": authoritative_count,
        "sqlite_parent_context": parent_context_count,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    valid = (
        not result["tim_dot_git"]
        and result["parent_git_root"] == "/Users/tim"
        and result["parent_commit"] == PARENT_COMMIT
        and result["tracked_tim_files"] == 0
        and result["repository_status"] == "unversioned"
        and result["repository_commit"] is None
        and result["authoritative_git_repository"] is False
        and result["content_manifest_hash"]
        == result["reproduced_content_manifest_hash"]
        and result["sqlite_non_null_repository_commit"] == 0
        and result["sqlite_authoritative_true"] == 0
        and result["sqlite_parent_context"] == result["sqlite_artifact_count"]
    )
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "probe",
        choices=("protected", "mcp", "schema", "provenance"),
    )
    arguments = parser.parse_args()
    return {
        "protected": check_protected,
        "mcp": check_mcp,
        "schema": check_schema,
        "provenance": check_provenance,
    }[arguments.probe]()


if __name__ == "__main__":
    raise SystemExit(main())
