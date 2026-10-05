"""TIM OPS MCP server (#152 M3): line-delimited JSON-RPC 2.0 over stdio,
same conventions and argument validation as src/graph_mcp/mcp_server.py.
Every tool is read-only; errors are structured results, never tracebacks."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from src.graph_mcp.mcp_server import PROTOCOL_VERSION, ToolError, _validate_arguments
from src.ops_mcp import SCHEMA_VERSION, SERVER_NAME
from src.ops_mcp.readers import MAX_LIMIT, ResearchReader, SourceError, TaskReader
from src.task_engine.model import TaskState


def _schema(properties: dict, required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


_LIMIT = {"limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT}}

TOOLS: list[dict[str, Any]] = [
    {"name": "ops_health", "description": "Server liveness and which sources are configured",
     "inputSchema": _schema({}, [])},
    {"name": "task_summary", "description": "Task Engine counts by state (read-only)",
     "inputSchema": _schema({}, [])},
    {"name": "task_list", "description": "Task Engine tasks, filtered by state/type, bounded",
     "inputSchema": _schema({"state": {"type": "string",
                                       "enum": [s.value for s in TaskState]},
                             "type": {"type": "string", "minLength": 1}, **_LIMIT}, [])},
    {"name": "task_get", "description": "One task with transition history, evidence, checkpoints",
     "inputSchema": _schema({"task_id": {"type": "string", "minLength": 1}}, ["task_id"])},
    {"name": "tool_health", "description": "Agent tool probes (Serena, graph, Obsidian, Ollama, ...)",
     "inputSchema": _schema({}, [])},
    {"name": "research_register", "description": "Research Lab hypothesis register: chain check, m, statuses",
     "inputSchema": _schema({}, [])},
    {"name": "research_reports", "description": "Committed Research Lab report files",
     "inputSchema": _schema({}, [])},
    {"name": "research_report", "description": "Per-variant train/validation summary of one report",
     "inputSchema": _schema({"name": {"type": "string", "minLength": 1}, **_LIMIT}, ["name"])},
]


def _default_health() -> dict:
    from src.agent_infra.health import ToolHealthRegistry
    return ToolHealthRegistry().refresh()


class OpsMcpServer:
    def __init__(self, tasks: TaskReader, research: ResearchReader,
                 health: Callable[[], dict] = _default_health) -> None:
        self.tasks = tasks
        self.research = research
        self.health = health
        self._initialized = False

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        if method == "notifications/initialized":
            return None
        request_id = message.get("id")
        try:
            result = self._dispatch(method, message.get("params") or {})
        except ToolError as error:
            return self._error(request_id, -32000, str(error))
        except SourceError as error:
            return self._error(request_id, -32001, str(error))
        except Exception as error:  # never leak tracebacks
            return self._error(request_id, -32603, f"internal error: {type(error).__name__}")
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
        schema = next((tool for tool in TOOLS if tool["name"] == name), None)
        if schema is None:
            raise ToolError(f"unknown tool: {name}")
        _validate_arguments(schema["inputSchema"], arguments)
        if name == "ops_health":
            payload = {"status": "ok", "read_only_tim": True, "schema_version": SCHEMA_VERSION,
                       "task_store": "configured" if self.tasks.path else "not_configured"}
        elif name == "task_summary":
            payload = self.tasks.summary()
        elif name == "task_list":
            payload = self.tasks.list(arguments.get("state"), arguments.get("type"),
                                      arguments.get("limit"))
        elif name == "task_get":
            payload = self.tasks.get(arguments["task_id"])
        elif name == "tool_health":
            payload = {"status": "ok", "tools": self.health()}
        elif name == "research_register":
            payload = self.research.register()
        elif name == "research_reports":
            payload = self.research.reports()
        else:
            payload = self.research.report(arguments["name"], arguments.get("limit"))
        return {"content": [{"type": "text",
                             "text": json.dumps(payload, indent=2, sort_keys=True, default=str)}],
                "isError": False}

    @staticmethod
    def _error(request_id, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

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
                response = (self.handle(message) if isinstance(message, dict)
                            else self._error(None, -32600, "invalid request"))
            if response is not None:
                stream_out.write(json.dumps(response, default=str) + "\n")
                stream_out.flush()


def main() -> int:
    root = Path(os.environ.get("TIM_OPS_MCP_ROOT", ".")).resolve()
    task_db = os.environ.get("TIM_OPS_TASK_DB") or None
    OpsMcpServer(TaskReader(Path(task_db) if task_db else None), ResearchReader(root)).serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
