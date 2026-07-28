from __future__ import annotations

import json
import sys
from typing import Any

from .query import answer, search
from .reporting import load_snapshot


TOOLS = [
    {"name": "tim_get_status", "description": "Read the current canonical TIM project snapshot", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "tim_get_module_status", "description": "Read evidenced status for one module", "inputSchema": {"type": "object", "properties": {"module_id": {"type": "string"}}, "required": ["module_id"]}},
    {"name": "tim_get_risks", "description": "Read current risk records", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "tim_get_source_health", "description": "Read configured source health", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "tim_search", "description": "Read-only full-text search", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "tim_query", "description": "Grounded deterministic management query", "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}},
]


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    snapshot = load_snapshot()
    if name == "tim_get_status":
        return snapshot
    if name == "tim_get_module_status":
        return next((item for item in snapshot["module_states"] if item["module_id"] == arguments["module_id"]), {"status": "unknown", "evidence_refs": []})
    if name == "tim_get_risks":
        return snapshot["risks"]
    if name == "tim_get_source_health":
        return snapshot["source_health"]
    if name == "tim_search":
        return search(arguments["query"])
    if name == "tim_query":
        return answer(arguments["question"], snapshot)
    raise ValueError(f"unknown read-only tool: {name}")


def handle(message: dict[str, Any]) -> dict[str, Any]:
    request_id = message.get("id")
    method = message.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}, "resources": {}}, "serverInfo": {"name": "tim-intelligence-manager", "version": "1.0.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params", {})
        payload = call_tool(params["name"], params.get("arguments", {}))
        result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}], "isError": False}
    elif method == "resources/list":
        result = {"resources": [{"uri": "tim://snapshot/current", "name": "Current TIM snapshot", "mimeType": "application/json"}]}
    elif method == "resources/read" and message.get("params", {}).get("uri") == "tim://snapshot/current":
        result = {"contents": [{"uri": "tim://snapshot/current", "mimeType": "application/json", "text": json.dumps(load_snapshot(), ensure_ascii=False, sort_keys=True)}]}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def serve() -> None:
    for line in sys.stdin:
        try:
            response = handle(json.loads(line))
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(exc)}}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()

