"""R4 search regression suite — proves the old prefix-scan bug stays dead.

Historical defect: search loaded only the first ~800 nodes alphabetically,
so late-id classes (note:...) could never be found even though they were
fully indexed. The fix filters inside SQLite; these tests would fail on
the old implementation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.graph_mcp.mcp_server import GraphMcpServer
from src.graph_mcp.schema import NodeType, Node, stable_id, utc_now
from src.graph_mcp.service import GraphService
from src.graph_mcp.store import GraphStore

OBSOLETE_SCAN_BOUNDARY = 800


@pytest.fixture
def big_service(tmp_path: Path) -> GraphService:
    """Graph with >800 nodes AND a matching note node positioned beyond the
    old alphabetical scan boundary (note:* sorts after class:*/file:*/...)."""
    store = GraphStore(tmp_path / "big.sqlite")
    nodes = []
    observed = utc_now()
    for index in range(OBSOLETE_SCAN_BOUNDARY + 200):
        nodes.append(Node(stable_id("class", f"src/gen{index:04d}.py", f"Gen{index}"),
                          NodeType.CLASS, f"Gen{index}", "code",
                          f"src/gen{index:04d}.py", {"i": index}).record(observed))
    nodes.append(Node(stable_id("note", "TIM/30 Missions/LONG History Extension Design.md"),
                      NodeType.OBSIDIAN_NOTE, "LONG History Extension Design",
                      "obsidian", "TIM/30 Missions/LONG History Extension Design.md",
                      {"type": "mission", "status": "active"}).record(observed))
    nodes.append(Node(stable_id("note", "TIM/50 Data & QA/Weird 'quoted' \"note\".md"),
                      NodeType.OBSIDIAN_NOTE, "Weird 'quoted' \"note\"",
                      "obsidian", "TIM/50 Data & QA/Weird 'quoted' \"note\".md",
                      {}).record(observed))
    nodes.append(Node(stable_id("file", "src/ünïcode pfad.py"),
                      NodeType.FILE, "ünïcode pfad.py", "code",
                      "src/ünïcode pfad.py", {}).record(observed))
    store.apply(nodes, [], "code")
    return GraphService(store, tmp_path)


def test_1_nodes_beyond_old_boundary_found(big_service):
    assert big_service.store.stats()["nodes_total"] > OBSOLETE_SCAN_BOUNDARY
    late = [n for n in big_service.store.nodes(limit=10 ** 6)
            if n["id"].startswith("note:")]
    assert len(late) == 2  # fixture sanity: targets exist beyond the boundary


def test_2_obsidian_note_beyond_prefix_found(big_service):
    result = big_service.search("LONG History Extension Design")
    assert any(m["id"].startswith("note:") for m in result["matches"]), (
        "Obsidian nodes must be findable — the old prefix scan lost them")


def test_3_exact_node_id(big_service):
    # the canonical id is percent-encoded (spaces -> %20); search it verbatim
    encoded = "note:TIM/30%20Missions/LONG%20History%20Extension%20Design.md"
    result = big_service.search(encoded, mode="id")
    match = result["matches"][0]
    assert match["why_matched"] == "exact id" and match["type"] == "ObsidianNote"


def test_4_partial_name(big_service):
    assert big_service.search("History Extension")["matches"]


def test_5_type_filter(big_service):
    result = big_service.search("Gen0001", node_type="Class")
    assert result["matches"] and all(m["type"] == "Class" for m in result["matches"])
    nothing = big_service.search("Gen0001", node_type="Mission")
    assert nothing["matches"] == []


def test_6_path_search(big_service):
    result = big_service.search("Data & QA", mode="path")
    assert any("Weird" in m["name"] for m in result["matches"])


def test_7_no_matches(big_service):
    result = big_service.search("definitely-not-anywhere")
    assert result["matches"] == [] and result["truncated"] is False


def test_8_limit_respected(big_service):
    result = big_service.search("Gen0", limit=5)
    assert len(result["matches"]) == 5 and result["truncated"] is True


def test_9_deterministic_ordering(big_service):
    first = big_service.search("Gen0", limit=50)
    second = big_service.search("Gen0", limit=50)
    assert [m["id"] for m in first["matches"]] == [m["id"] for m in second["matches"]]


def test_10_apostrophe_input(big_service):
    assert big_service.search("Weird 'quoted'")["matches"]


def test_11_double_quotes_input(big_service):
    assert big_service.search('quoted\' "note"', mode="path")["matches"]


def test_12_sql_text_is_only_search_text(big_service):
    malicious = "' OR 1=1 --"
    result = big_service.search(malicious)
    ids = [m["id"] for m in result["matches"]]
    assert len(ids) == 0 or all(malicious.strip("' ") not in m["id"] for m in result["matches"])
    # and it certainly did not dump the graph:
    assert len(result["matches"]) <= 50
    injection = "'; DROP TABLE nodes; --"
    dumped = big_service.search(injection)
    assert len(dumped["matches"]) <= 50
    assert big_service.store.stats()["nodes_total"] > 0  # table still there


def test_13_unicode(big_service):
    assert big_service.search("ünïcode")["matches"]


def test_14_space_containing_path(big_service):
    assert big_service.search("30 Missions/LONG", mode="path")["matches"]


def test_15_ampersand_vault_path(big_service):
    result = big_service.search("Data & QA", mode="path")
    assert result["matches"]
    assert all("%26" in m["id"] for m in result["matches"])  # encoded, collision-free


def test_16_secret_like_values_stay_redacted(big_service, tmp_path: Path):
    from src.graph_mcp.redaction import redact
    poisoned = Node(stable_id("file", "src/leak.py"), NodeType.FILE, "leak.py",
                    "code", "src/leak.py",
                    {"note": "ghp_" + "A" * 40})
    clean = {**poisoned.record(utc_now()), "metadata": redact(poisoned.metadata)}
    big_service.store.apply([clean], [], "code")
    found = big_service.search("leak.py")["matches"]
    blob = json.dumps(big_service.store.nodes(limit=10 ** 6))
    assert found and "ghp_" not in blob


def test_17_invalid_input_structured_error(tmp_path: Path):
    server = GraphMcpServer(GraphService(GraphStore(tmp_path / "m.sqlite"), tmp_path))
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "graph_search",
                                         "arguments": {"query": ""}}})
    assert "error" in response  # schema requires minLength 1
    response = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": "graph_search",
                                         "arguments": {"query": "x",
                                                       "mode": "gremlin"}}})
    assert "error" in response


def test_18_no_traceback_through_mcp(big_service, tmp_path: Path, monkeypatch):
    server = GraphMcpServer(big_service)
    server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    def explode(query, *args, **kwargs):
        raise RuntimeError("boom /Users/secret")
    monkeypatch.setattr(server.service, "search", explode)
    response = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "graph_search",
                                         "arguments": {"query": "x"}}})
    blob = json.dumps(response)
    assert response["error"]["code"] == -32603
    assert "Traceback" not in blob and "boom" not in blob
