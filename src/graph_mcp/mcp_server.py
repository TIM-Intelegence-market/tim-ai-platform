"""TIM GRAPH MCP server (STEP 15): line-delimited JSON-RPC 2.0 over stdio,
following the repo's existing MCP conventions (initialize ->
notifications/initialized -> tools/list -> tools/call; see
src/tim_manager/graphify_mcp.py). Read-only towards TIM: the only writes
are refreshes of this package's own local SQLite index.

No SDK dependency (the repo venv has none); no Python tracebacks ever
leave this process — errors are structured tool results."""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from src.graph_mcp import SCHEMA_VERSION, SERVER_NAME
from src.graph_mcp import export as export_module
from src.graph_mcp.service import GraphService
from src.graph_mcp.store import GraphStore, GraphStoreError

PROTOCOL_VERSION = "2025-11-25"


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Enforce the declared inputSchema server-side (STEP 31): invalid input
    is a structured error, never a silent fallback or a traceback."""
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be an object")
    for key in schema.get("required", []):
        if key not in arguments:
            raise ToolError(f"missing required argument: {key}")
    properties = schema.get("properties", {})
    for key, value in arguments.items():
        if key not in properties:
            raise ToolError(f"unknown argument: {key}")
        spec = properties[key]
        kind = spec.get("type")
        if kind == "string" and not isinstance(value, str):
            raise ToolError(f"argument {key} must be a string")
        if kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ToolError(f"argument {key} must be an integer")
        if kind == "array" and not isinstance(value, list):
            raise ToolError(f"argument {key} must be an array")
        if kind == "object" and not isinstance(value, dict):
            raise ToolError(f"argument {key} must be an object")
        if isinstance(value, str):
            if "enum" in spec and value not in spec["enum"]:
                raise ToolError(f"argument {key} must be one of {spec['enum']}")
            if len(value) < spec.get("minLength", 0):
                raise ToolError(f"argument {key} is too short")
        if isinstance(value, int) and not isinstance(value, bool):
            if value < spec.get("minimum", -(2 ** 63)):
                raise ToolError(f"argument {key} below minimum")
            if value > spec.get("maximum", 2 ** 63 - 1):
                raise ToolError(f"argument {key} above maximum")


def _text(payload: Any) -> list[dict[str, str]]:
    return [{"type": "text",
             "text": json.dumps(payload, indent=2, sort_keys=True, default=str)}]


def _schema(properties: dict, required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


_NODE_ARG = {"node": {"type": "string",
                      "description": "stable node id, e.g. class:src/...:Name"}}
_LIMIT_ARG = {"limit": {"type": "integer", "minimum": 1, "maximum": 200}}


class ToolError(Exception):
    pass


TOOLS: list[dict[str, Any]] = [
    {"name": "graph_health", "description": "Liveness and store summary",
     "inputSchema": _schema({}, [])},
    {"name": "graph_stats", "description": "Node/edge counts by type + set hashes",
     "inputSchema": _schema({}, [])},
    {"name": "graph_get_node", "description": "Fetch one node record by stable id",
     "inputSchema": _schema(_NODE_ARG, ["node"])},
    {"name": "graph_neighbors",
     "description": "Neighbors of a node with direction and edge-type filters",
     "inputSchema": _schema({**_NODE_ARG,
                             "direction": {"type": "string", "enum": ["in", "out", "both"]},
                             "edge_types": {"type": "array", "items": {"type": "string"}},
                             **_LIMIT_ARG}, ["node"])},
    {"name": "graph_search",
     "description": "Search nodes by id/name/path/metadata with why_matched",
     "inputSchema": _schema({"query": {"type": "string", "minLength": 1},
                             "mode": {"type": "string",
                                      "enum": ["name", "id", "path", "metadata"]},
                             "node_type": {"type": "string"}, **_LIMIT_ARG}, ["query"])},
    {"name": "graph_path", "description": "Bounded shortest path between two nodes",
     "inputSchema": _schema({"source": {"type": "string"}, "target": {"type": "string"},
                             "max_depth": {"type": "integer", "minimum": 1,
                                           "maximum": 8}},
                            ["source", "target"])},
    {"name": "graph_dependencies", "description": "What this node depends on",
     "inputSchema": _schema({**_NODE_ARG, **_LIMIT_ARG}, ["node"])},
    {"name": "graph_dependents", "description": "What depends on this node",
     "inputSchema": _schema({**_NODE_ARG, **_LIMIT_ARG}, ["node"])},
    {"name": "graph_impact",
     "description": "STATIC_GRAPH_IMPACT analysis for a node (no runtime claim)",
     "inputSchema": _schema(_NODE_ARG, ["node"])},
    {"name": "graph_incident_context", "description": "Incident context bundle",
     "inputSchema": _schema({"incident": {"type": "string"}}, ["incident"])},
    {"name": "graph_mission_context", "description": "Mission context bundle",
     "inputSchema": _schema({"mission": {"type": "string"}}, ["mission"])},
    {"name": "graph_gate_context", "description": "Gate context bundle",
     "inputSchema": _schema({"gate": {"type": "string"}}, ["gate"])},
    {"name": "graph_agent_context", "description": "Agent context bundle",
     "inputSchema": _schema({"agent": {"type": "string"}}, ["agent"])},
    {"name": "graph_refresh_code",
     "description": "Incremental code re-index (own store only)", "inputSchema": _schema({}, [])},
    {"name": "graph_refresh_docs",
     "description": "Re-index Obsidian/recipes/agents (own store only)", "inputSchema": _schema({}, [])},
    {"name": "graph_refresh_runtime_readonly",
     "description": "Re-index runtime services + DB schema (own store only)",
     "inputSchema": _schema({}, [])},
    {"name": "graph_export",
     "description": "Export the graph: json, mermaid, dot, graphml",
     "inputSchema": _schema({"format": {"type": "string",
                                        "enum": ["json", "mermaid", "dot", "graphml"]}},
                            ["format"])},
    {"name": "graph_index_github_payload",
     "description": "Map a provider GitHub payload into the graph (offline adapter)",
     "inputSchema": _schema({"payload": {"type": "object"}}, ["payload"])},
]


class GraphMcpServer:
    def __init__(self, service: GraphService) -> None:
        self.service = service
        self._initialized = False

    # -- request handling ------------------------------------------------

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if method == "notifications/initialized":
            return None
        request_id = message.get("id")
        try:
            result = self._dispatch(method, message.get("params") or {})
        except ToolError as error:
            return self._error(request_id, -32000, str(error))
        except GraphStoreError as error:
            return self._error(request_id, -32001, str(error))
        except Exception as error:  # never leak tracebacks (STEP 31)
            return self._error(request_id, -32603,
                               f"internal error: {type(error).__name__}")
        if request_id is None:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            self._initialized = True
            return {"protocolVersion": PROTOCOL_VERSION,
                    "serverInfo": {"name": SERVER_NAME, "version": SCHEMA_VERSION},
                    "capabilities": {"tools": {}}}
        if not self._initialized:
            raise ToolError("server not initialized")
        if method == "tools/list":
            return {"tools": TOOLS}
        if method == "tools/call":
            return self._call_tool(params.get("name"), params.get("arguments") or {})
        if method == "ping":
            return {}
        raise ToolError(f"unknown method: {method}")

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        service = self.service
        schema = next((tool for tool in TOOLS if tool["name"] == name), None)
        if schema is None:
            raise ToolError(f"unknown tool: {name}")
        _validate_arguments(schema["inputSchema"], arguments)
        try:
            if name == "graph_health":
                payload = service.health()
            elif name == "graph_stats":
                payload = service.stats()
            elif name == "graph_get_node":
                payload = service.get_node(self._required(arguments, "node"))
            elif name == "graph_neighbors":
                payload = service.neighbors(self._required(arguments, "node"),
                                            arguments.get("direction", "both"),
                                            arguments.get("edge_types"),
                                            arguments.get("limit"))
            elif name == "graph_search":
                payload = service.search(self._required(arguments, "query"),
                                         arguments.get("node_type"),
                                         arguments.get("limit"),
                                         arguments.get("mode", "name"))
            elif name == "graph_path":
                payload = service.path(self._required(arguments, "source"),
                                       self._required(arguments, "target"),
                                       arguments.get("max_depth"))
            elif name == "graph_dependencies":
                payload = service.dependencies(self._required(arguments, "node"),
                                               arguments.get("limit"))
            elif name == "graph_dependents":
                payload = service.dependents(self._required(arguments, "node"),
                                             arguments.get("limit"))
            elif name == "graph_impact":
                payload = service.impact(self._required(arguments, "node"))
            elif name == "graph_incident_context":
                payload = service.incident_context(self._required(arguments, "incident"))
            elif name == "graph_mission_context":
                payload = service.mission_context(self._required(arguments, "mission"))
            elif name == "graph_gate_context":
                payload = service.gate_context(self._required(arguments, "gate"))
            elif name == "graph_agent_context":
                payload = service.agent_context(self._required(arguments, "agent"))
            elif name == "graph_refresh_code":
                payload = service.refresh_code()
            elif name == "graph_refresh_docs":
                payload = service.refresh_docs()
            elif name == "graph_refresh_runtime_readonly":
                payload = service.refresh_runtime_readonly()
            elif name == "graph_export":
                fmt = self._required(arguments, "format")
                if fmt == "json":
                    payload = export_module.export_json(service)
                elif fmt == "mermaid":
                    payload = {"format": "mermaid",
                               "content": export_module.export_mermaid(service)}
                elif fmt == "dot":
                    payload = {"format": "dot",
                               "content": export_module.export_dot(service)}
                elif fmt == "graphml":
                    payload = {"format": "graphml",
                               "content": export_module.export_graphml(service)}
                else:
                    raise ToolError(f"unsupported export format: {fmt}")
            elif name == "graph_index_github_payload":
                payload = service.index_github_payload(
                    self._required(arguments, "payload"))
            else:
                raise ToolError(f"unknown tool: {name}")
        except ToolError:
            raise
        except (KeyError, ValueError, TypeError) as error:
            raise ToolError(f"invalid arguments: {error}") from None
        return {"content": _text(payload), "isError": False}

    @staticmethod
    def _required(arguments: dict[str, Any], key: str) -> Any:
        if key not in arguments:
            raise ToolError(f"missing required argument: {key}")
        return arguments[key]

    def _error(self, request_id, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": code, "message": message}}

    # -- stdio loop --------------------------------------------------------

    def serve(self, stream_in=None, stream_out=None) -> None:
        stream_in = stream_in or sys.stdin
        stream_out = stream_out or sys.stdout
        for line in stream_in:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                response = self._error(None, -32700, "parse error")
            else:
                if not isinstance(message, dict):
                    response = self._error(None, -32600, "invalid request")
                else:
                    response = self.handle(message)
            if response is not None:
                stream_out.write(json.dumps(response, default=str) + "\n")
                stream_out.flush()


def build_service(root, db_path, vault=None, ki_tools=None) -> GraphService:
    return GraphService(GraphStore(db_path), root, vault=vault, ki_tools=ki_tools)


def main() -> int:
    import os
    from pathlib import Path
    root = Path(os.environ.get("TIM_GRAPH_MCP_ROOT", ".")).resolve()
    db_path = Path(os.environ.get("TIM_GRAPH_MCP_DB", root / ".runtime/graph/graph.sqlite"))
    vault = os.environ.get("TIM_GRAPH_MCP_VAULT")
    ki_tools = os.environ.get("TIM_GRAPH_MCP_KI_TOOLS",
                              str(Path.home() / "Desktop/KI TOOLS"))
    service = build_service(root, db_path,
                            vault=Path(vault) if vault else None,
                            ki_tools=Path(ki_tools) if ki_tools else None)
    server = GraphMcpServer(service)
    server.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
