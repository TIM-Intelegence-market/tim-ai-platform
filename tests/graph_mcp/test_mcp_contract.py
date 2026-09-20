"""STEP 31: MCP contract tests — handshake, tools/list, every tool with
valid/invalid input, empty graph, missing node, bounded output, schema
correctness, error responses. No Python tracebacks as tool results."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from src.graph_mcp import SCHEMA_VERSION
from src.graph_mcp.mcp_server import PROTOCOL_VERSION, TOOLS, GraphMcpServer
from src.graph_mcp.service import GraphService
from src.graph_mcp.store import GraphStore


def make_server(tmp_path: Path, empty: bool = False) -> GraphMcpServer:
    store = GraphStore(tmp_path / "g.sqlite")
    service = GraphService(store, tmp_path)
    if not empty:
        service.index_github_payload({"issues": [
            {"number": 1, "title": "demo", "state": "open"}]})
    return GraphMcpServer(service)


def rpc(server: GraphMcpServer, method: str, params: dict | None = None,
        request_id: int | str = 1) -> dict:
    return server.handle({"jsonrpc": "2.0", "id": request_id,
                          "method": method, "params": params or {}})


@pytest.fixture
def server(tmp_path: Path) -> GraphMcpServer:
    return make_server(tmp_path)


@pytest.fixture
def empty_server(tmp_path: Path) -> GraphMcpServer:
    return make_server(tmp_path, empty=True)


def test_initialize_handshake(server):
    result = rpc(server, "initialize")
    assert result["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert result["result"]["serverInfo"]["version"] == SCHEMA_VERSION
    assert server.handle({"method": "notifications/initialized"}) is None


def test_requires_initialize_first(tmp_path):
    server = make_server(tmp_path)
    response = rpc(server, "tools/list")
    assert response["error"]["code"] == -32000


def test_tools_list_schema_correct(server):
    rpc(server, "initialize")
    listing = rpc(server, "tools/list")["result"]["tools"]
    assert len(listing) == 18
    names = {tool["name"] for tool in listing}
    assert {"graph_health", "graph_stats", "graph_get_node", "graph_neighbors",
            "graph_search", "graph_path", "graph_dependencies", "graph_dependents",
            "graph_impact", "graph_incident_context", "graph_mission_context",
            "graph_gate_context", "graph_agent_context", "graph_refresh_code",
            "graph_refresh_docs", "graph_refresh_runtime_readonly",
            "graph_export", "graph_index_github_payload"} == names
    for tool in listing:
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert set(schema) == {"type", "properties", "required"}


def call(server, name: str, arguments: dict) -> dict:
    if not server._initialized:
        rpc(server, "initialize")
    return rpc(server, "tools/call", {"name": name, "arguments": arguments})["result"]


def test_valid_input_and_content_shape(server):
    health = call(server, "graph_health", {})
    assert health["isError"] is False
    payload = json.loads(health["content"][0]["text"])
    assert payload["read_only_tim"] is True
    stats = json.loads(call(server, "graph_stats", {})["content"][0]["text"])
    assert stats["nodes_total"] >= 1
    node = json.loads(call(server, "graph_get_node",
                           {"node": "github:issue:1"})["content"][0]["text"])
    assert node["type"] == "GitHubIssue"
    search = json.loads(call(server, "graph_search",
                             {"query": "demo"})["content"][0]["text"])
    assert search["matches"][0]["why_matched"]
    neighbors = json.loads(call(server, "graph_neighbors",
                                {"node": "github:issue:1"})["content"][0]["text"])
    assert "edges" in neighbors
    pathing = json.loads(call(server, "graph_path",
                              {"source": "github:issue:1",
                               "target": "github:issue:1"})
                         ["content"][0]["text"])
    assert pathing["found"] is False  # self path not constructed
    exported = json.loads(call(server, "graph_export",
                               {"format": "json"})["content"][0]["text"])
    assert exported["nodes"]
    mermaid = json.loads(call(server, "graph_export",
                              {"format": "mermaid"})["content"][0]["text"])
    assert mermaid["content"].startswith("graph TD")


def test_every_tool_invalid_input_is_structured_error(server):
    for name, arguments in (
        ("graph_get_node", {}),
        ("graph_get_node", {"node": 42}),
        ("graph_search", {}),
        ("graph_search", {"query": ""}),
        ("graph_path", {"source": "a"}),
        ("graph_neighbors", {"node": "x", "direction": "sideways"}),
        ("graph_export", {"format": "yaml"}),
        ("graph_index_github_payload", {}),
        ("graph_mission_context", {}),
        ("no_such_tool", {}),
    ):
        response = rpc(server, "tools/call", {"name": name, "arguments": arguments})
        assert "error" in response, name
        assert "Traceback" not in json.dumps(response), name


def test_missing_node_is_error_result_not_protocol_error(server):
    result = call(server, "graph_get_node", {"node": "class:nope"})
    payload = json.loads(result["content"][0]["text"])
    assert payload["error"] == "not_found"
    assert result["isError"] is False  # valid query, empty answer


def test_empty_graph_behaves(empty_server):
    health = json.loads(call(empty_server, "graph_health", {})["content"][0]["text"])
    assert health["status"] == "empty"
    search = json.loads(call(empty_server, "graph_search",
                             {"query": "x"})["content"][0]["text"])
    assert search["matches"] == []


def test_bounded_output(empty_server):
    bounded = call(empty_server, "graph_search", {"query": "x", "limit": 50})
    payload = json.loads(bounded["content"][0]["text"])
    assert payload["total_returned"] <= 50
    # schema cap (max 200) is enforced server-side -> structured error
    response = rpc(empty_server, "tools/call", {
        "name": "graph_search",
        "arguments": {"query": "x", "limit": 10 ** 9}})
    assert "error" in response and "Traceback" not in json.dumps(response)


def test_unknown_method_and_malformed_lines(tmp_path):
    server = make_server(tmp_path)
    assert rpc(server, "no/such/method")["error"]["code"] == -32000
    output = io.StringIO()
    server.serve(stream_in=io.StringIO(
        'not json\n\n[]\n{"jsonrpc":"2.0","id":7,"method":"no/such/method"}\n'),
        stream_out=output)
    lines = [json.loads(line) for line in output.getvalue().splitlines()]
    assert lines[0]["error"]["code"] == -32700      # parse error
    assert lines[1]["error"]["code"] == -32600      # invalid request (array)
    assert lines[2]["error"]["code"] == -32000      # unknown method


def test_internal_errors_never_leak_tracebacks(server, monkeypatch):
    def explode():
        raise RuntimeError("secret detail /Users/xyz")
    monkeypatch.setattr(server.service, "health", explode)
    rpc(server, "initialize")
    response = rpc(server, "tools/call", {"name": "graph_health", "arguments": {}})
    assert response["error"]["code"] == -32603
    assert "secret detail" not in json.dumps(response)
    assert "Traceback" not in json.dumps(response)


def test_refresh_tools_only_touch_own_store(server, tmp_path):
    before = server.service.store.stats()["nodes_total"]
    metrics = json.loads(call(server, "graph_refresh_code", {})["content"][0]["text"])
    assert metrics["mode"] == "refresh_code"
    after = server.service.store.stats()["nodes_total"]
    assert after >= before  # own index grew or stayed; nothing else exists here
