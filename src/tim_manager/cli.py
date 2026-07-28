from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ARTIFACT_ROOT, CONFIG_ROOT, PROJECT_ROOT
from .query import answer, search
from .reporting import diff_snapshots, load_snapshot, persist_scan
from .scanner import scan_project
from .security import safe_output_path
from .state import build_snapshot


def run_scan() -> dict:
    scan = scan_project()
    snapshot = build_snapshot(scan)
    outputs = persist_scan(scan, snapshot)
    return {"scan": scan, "snapshot": snapshot, "outputs": outputs}


def doctor() -> dict:
    checks = {
        "config": all((CONFIG_ROOT / name).exists() for name in ("sources.yaml", "protected_paths.yaml", "module_registry.yaml", "classification_rules.yaml", "routing.yaml")),
        "project_root": PROJECT_ROOT.exists(),
        "storage_parent": ARTIFACT_ROOT.parent.exists(),
        "protected_write_check": False,
        "snapshot": (ARTIFACT_ROOT / "snapshots" / "current.json").exists(),
        "mcp": True,
        "external_models": "optional_disabled",
    }
    try:
        safe_output_path("data/forbidden.txt")
    except PermissionError:
        checks["protected_write_check"] = True
    return {"status": "PASS" if all(value is True or value == "optional_disabled" for value in checks.values()) else "FAIL", "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tim-manager")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "sources", "scan", "validate", "status", "brief", "timeline", "risks", "decisions", "experiments", "evals", "doctor"):
        sub.add_parser(name)
    search_parser = sub.add_parser("search"); search_parser.add_argument("query")
    query_parser = sub.add_parser("query"); query_parser.add_argument("question")
    diff_parser = sub.add_parser("diff"); diff_parser.add_argument("old"); diff_parser.add_argument("new")
    export_parser = sub.add_parser("export"); export_parser.add_argument("--output", required=True)
    sub.add_parser("serve-mcp")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            print(json.dumps({"status": "READY", "config_root": str(CONFIG_ROOT), "writes": "TIM-IM only"}, indent=2)); return 0
        if args.command == "scan":
            result = run_scan()
            print(json.dumps({"scan_id": result["scan"]["scan_id"], "snapshot_id": result["snapshot"]["snapshot_id"], "stats": result["scan"]["stats"], "outputs": result["outputs"]}, indent=2)); return 0
        if args.command == "sources":
            data = load_snapshot(); print(json.dumps(data["source_health"], indent=2)); return 0
        if args.command == "validate" or args.command == "doctor":
            result = doctor(); print(json.dumps(result, indent=2)); return 0 if result["status"] == "PASS" else 2
        if args.command == "status":
            print(json.dumps(load_snapshot(), indent=2)); return 0
        if args.command == "brief":
            print((ARTIFACT_ROOT / "reports" / "executive_brief.md").read_text()); return 0
        if args.command in {"timeline", "risks", "decisions", "experiments", "evals"}:
            key = {"timeline": "recent_changes"}.get(args.command, args.command)
            print(json.dumps(load_snapshot().get(key, []), indent=2)); return 0
        if args.command == "search":
            print(json.dumps(search(args.query), indent=2)); return 0
        if args.command == "query":
            print(json.dumps(answer(args.question), indent=2)); return 0
        if args.command == "diff":
            print(json.dumps(diff_snapshots(load_snapshot(Path(args.old)), load_snapshot(Path(args.new))), indent=2)); return 0
        if args.command == "export":
            target = safe_output_path(args.output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(load_snapshot(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(target); return 0
        if args.command == "serve-mcp":
            from .mcp_server import serve
            serve(); return 0
    except (FileNotFoundError, ValueError, PermissionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

