"""STEP 30: stable identities, record contracts, store behavior, corrupt DB,
concurrent read, redaction."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.graph_mcp import SCHEMA_VERSION
from src.graph_mcp.redaction import contains_secret, redact
from src.graph_mcp.schema import (Edge, EdgeType, Node, NodeType, edge_set_hash,
                                  node_set_hash, stable_id)
from src.graph_mcp.store import GraphStore, GraphStoreError


def test_stable_ids_deterministic_and_encoded():
    first = stable_id("file", "src/00 HOME/a&b.md")
    second = stable_id("file", "src/00 HOME/a&b.md")
    assert first == second
    assert " " not in first and "&" not in first
    assert first.startswith("file:")


def test_stable_id_rejects_empty():
    with pytest.raises(ValueError):
        stable_id("file")


def test_node_contract_and_content_hash():
    node = Node(stable_id("class", "a.py", "X"), NodeType.CLASS, "X", "code", "a.py",
                {"lineno": 3})
    record = node.record("2026-09-18T00:00:00+00:00")
    assert set(record) == {"id", "type", "name", "source", "path", "metadata",
                           "content_hash", "observed_at", "schema_version"}
    assert record["schema_version"] == SCHEMA_VERSION
    # same content -> same hash; different metadata -> different hash
    same = Node(node.id, NodeType.CLASS, "X", "code", "a.py", {"lineno": 3})
    other = Node(node.id, NodeType.CLASS, "X", "code", "a.py", {"lineno": 4})
    assert node.identity_hash() == same.identity_hash()
    assert node.identity_hash() != other.identity_hash()


def test_edge_evidence_enforced():
    with pytest.raises(ValueError, match="requires evidence"):
        Edge("file:a", "module:b", EdgeType.READS)  # semantic claim without provenance
    edge = Edge("file:a", "module:b", EdgeType.CONTAINS)
    assert edge.record()["type"] == "CONTAINS"


def test_edge_self_loop_refused():
    with pytest.raises(ValueError):
        Edge("file:a", "file:a", EdgeType.REFERENCES)


def test_set_hashes_order_independent():
    nodes = [{"id": "a", "type": "File", "content_hash": "1"},
             {"id": "b", "type": "File", "content_hash": "2"}]
    edges = [{"from": "a", "to": "b", "type": "CONTAINS", "metadata": "{}"}]
    flipped = list(reversed(nodes))
    assert node_set_hash(nodes) == node_set_hash(flipped)
    assert edge_set_hash(edges) == edge_set_hash(list(reversed(edges)))


def test_store_apply_diff_counters(tmp_path: Path):
    store = GraphStore(tmp_path / "g.sqlite")

    def node(node_id: str, name: str, meta=None):
        return Node(node_id, NodeType.FILE, name, "code", node_id, meta or {}
                    ).record("2026-09-18T00:00:00+00:00")

    first = store.apply([node("file:a", "a"), node("file:b", "b")], [], "code")
    assert first["nodes_added"] == 2
    second = store.apply([node("file:a", "a"), node("file:b", "b")], [], "code")
    assert all(value == 0 for value in second.values())  # idempotent replace
    third = store.apply([node("file:a", "a2"), node("file:c", "c")], [], "code")
    assert third["nodes_updated"] == 1 and third["nodes_removed"] == 1
    assert third["nodes_added"] == 1
    with pytest.raises(GraphStoreError):
        store.apply([node("file:x", "x")], [], "")  # prefix required
    store.close()


def test_store_rejects_corrupt_database(tmp_path: Path):
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"this is not a database" * 100)
    with pytest.raises(GraphStoreError):
        GraphStore(corrupt)


def test_store_rejects_non_sqlite_name(tmp_path: Path):
    with pytest.raises(GraphStoreError):
        GraphStore(tmp_path / "graph.txt")


def test_concurrent_read(tmp_path: Path):
    first = GraphStore(tmp_path / "g.sqlite")
    first.apply([Node("file:a", NodeType.FILE, "a", "code", "a").record(
        "2026-09-18T00:00:00+00:00")], [], "code")
    second = GraphStore(tmp_path / "g.sqlite")  # WAL: concurrent reader
    assert second.node("file:a") is not None
    first.close()
    second.close()


def test_retire_source_cleans_edges(tmp_path: Path):
    store = GraphStore(tmp_path / "g.sqlite")
    nodes = [Node("file:a", NodeType.FILE, "a", "code", "a").record(
        "2026-09-18T00:00:00+00:00"),
        Node("module:m", NodeType.MODULE, "m", "code", "a").record(
            "2026-09-18T00:00:00+00:00")]
    edge = Edge("file:a", "module:m", EdgeType.DEFINES).record()
    store.apply(nodes, [edge], "code")
    assert store.retire_source("code") == 2
    assert store.stats()["nodes_total"] == 0
    assert store.edges_from("file:a") == []
    store.close()


def test_redaction():
    assert contains_secret({"password": "hunter2"})
    assert contains_secret("token=abc123def456ghi789")
    redacted = redact({"api_key": "sk-1234567890abcdef", "note": "clean",
                       "nested": ["ghp_" + "A" * 30]})
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["note"] == "clean"
    assert "ghp_" not in json.dumps(redacted)
