"""CLI for building, querying and exporting the TIM graph (tests, runbook,
STEP 37 final verification). The MCP server is `python -m src.graph_mcp.mcp_server`."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.graph_mcp import export as export_module  # noqa: E402
from src.graph_mcp.mcp_server import build_service  # noqa: E402

DEFAULT_VAULT = "/Users/tim/Documents/TIM/TIM OBSIDIAN"
DEFAULT_KI_TOOLS = str(Path.home() / "Desktop/KI TOOLS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=".runtime/graph/graph.sqlite")
    parser.add_argument("--root", default=".")
    parser.add_argument("--vault", default=DEFAULT_VAULT)
    parser.add_argument("--ki-tools", default=DEFAULT_KI_TOOLS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("refresh-all", help="code + docs + runtime (read-only towards TIM)")
    sub.add_parser("refresh-code")
    sub.add_parser("refresh-docs")
    sub.add_parser("refresh-runtime")
    sub.add_parser("health")
    sub.add_parser("stats")
    query = sub.add_parser("query")
    query.add_argument("tool", choices=["search", "neighbors", "dependencies",
                                        "dependents", "impact", "path",
                                        "mission-context", "incident-context",
                                        "gate-context", "agent-context", "get-node"])
    query.add_argument("args", nargs="*")
    export = sub.add_parser("export")
    export.add_argument("--out", default=".runtime/graph/exports")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    service = build_service(root, Path(args.db), vault=Path(args.vault),
                            ki_tools=Path(args.ki_tools))
    if args.command == "refresh-all":
        results = [service.refresh_code(), service.refresh_docs(),
                   service.refresh_runtime_readonly()]
        print(json.dumps(results, indent=2, default=str))
    elif args.command == "refresh-code":
        print(json.dumps(service.refresh_code(), indent=2, default=str))
    elif args.command == "refresh-docs":
        print(json.dumps(service.refresh_docs(), indent=2, default=str))
    elif args.command == "refresh-runtime":
        print(json.dumps(service.refresh_runtime_readonly(), indent=2, default=str))
    elif args.command == "health":
        print(json.dumps(service.health(), indent=2, default=str))
    elif args.command == "stats":
        print(json.dumps(service.stats(), indent=2, default=str))
    elif args.command == "export":
        written = export_module.write_exports(service, Path(args.out))
        print(json.dumps({k: str(v) for k, v in written.items()}, indent=2))
    elif args.command == "query":
        print(json.dumps(_query(service, args.tool, args.args), indent=2, default=str))
    return 0


def _query(service, tool: str, argv: list[str]):
    if tool == "search":
        return service.search(argv[0], node_type=argv[1] if len(argv) > 1 else None)
    if tool == "get-node":
        return service.get_node(argv[0])
    if tool == "neighbors":
        return service.neighbors(argv[0])
    if tool in ("dependencies", "dependents"):
        return getattr(service, tool)(argv[0])
    if tool == "impact":
        return service.impact(argv[0])
    if tool == "path":
        return service.path(argv[0], argv[1])
    if tool == "mission-context":
        return service.mission_context(argv[0])
    if tool == "incident-context":
        return service.incident_context(argv[0])
    if tool == "gate-context":
        return service.gate_context(argv[0])
    if tool == "agent-context":
        return service.agent_context(argv[0])
    raise SystemExit(f"unknown query: {tool}")


if __name__ == "__main__":
    raise SystemExit(main())
