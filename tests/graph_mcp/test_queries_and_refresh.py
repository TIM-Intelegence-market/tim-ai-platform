"""STEP 30/31: query layer, contexts, bounded traversal, incremental
refresh, deleted files, determinism, idempotency."""
from __future__ import annotations

import json
from pathlib import Path

from src.graph_mcp.export import export_graphml, export_json, export_mermaid, export_dot
from src.graph_mcp.service import HARD_MAX_DEPTH, HARD_MAX_LIMIT, GraphService
from src.graph_mcp.store import GraphStore


def test_search_modes_and_bounded(service):
    result = service.search("Engine")
    assert result["matches"] and result["matches"][0]["why_matched"]
    assert service.search("class:src/demo/core.py:Engine", mode="id")["matches"]
    assert service.search("core.py", mode="path")["matches"]
    assert service.search("nonexistent")["matches"] == []
    bounded = service.search("e", limit=2)
    assert len(bounded["matches"]) <= 2 and bounded["truncated"]


def test_get_node_and_missing(service):
    node = service.get_node("class:src/demo/core.py:Engine")
    assert node["type"] == "Class"
    assert service.get_node("class:nope") == {"error": "not_found", "id": "class:nope"}


def test_neighbors_directions_and_filters(service):
    both = service.neighbors("class:src/demo/core.py:Engine")
    assert both["nodes"] and both["edges"]
    outgoing = service.neighbors("class:src/demo/core.py:Engine", direction="out")
    assert all(e["from"] == "class:src/demo/core.py:Engine" for e in outgoing["edges"])
    filtered = service.neighbors("class:src/demo/core.py:Engine",
                                 edge_types=["DEFINES"])
    assert all(e["type"] == "DEFINES" for e in filtered["edges"])
    assert service.neighbors("nope")["error"] == "not_found"


def test_dependencies_and_dependents(service):
    deps = service.dependencies("module:tests.test_core")
    types = {e["type"] for e in deps["edges"]}
    assert "IMPORTS" in types
    dependents = service.dependents("module:src.demo.core")
    assert any(e["type"] == "IMPORTS" and e["from"] == "module:tests.test_core"
               for e in dependents["edges"])


def test_path_bounded_and_missing(service):
    found = service.path("file:src/demo/core.py", "module:src.demo.core")
    assert found["found"] and found["depth"] <= HARD_MAX_DEPTH
    # existing but unreachable target -> honest "no path" (not an error)
    gate = _first(service, "Gate")
    assert service.path("file:src/demo/core.py", gate["id"])["found"] is False
    assert service.path("missing", "module:src.demo.core")["error"] == "not_found"
    assert HARD_MAX_DEPTH <= 8  # runaway traversal impossible by construction


def test_impact_is_static_labeled(service):
    impact = service.impact("class:src/demo/core.py:Engine")
    assert impact["analysis"] == "STATIC_GRAPH_IMPACT"
    assert impact["runtime_evidence"] is False
    assert "tests" in impact
    assert service.impact("nothing")["error"] == "not_found"


def test_mission_incident_gate_agent_context(service):
    mission = [n for n in [service.get_node(i["id"]) for i in
              _ids(service, "Mission")] if n and n.get("error") is None]
    assert mission
    context = service.mission_context(mission[0]["id"])
    assert context["gates"] or context["notes"] or context["incidents"]
    missing = service.mission_context("mission:nope")
    assert missing["error"] == "not_found" and "search_suggestions" in missing

    incident = _first(service, "Incident")
    incident_context = service.incident_context(incident["id"])
    assert incident_context["classification"] == "resolved"
    # the only evidence is the note that carries the wikilink
    assert incident_context["evidence_refs"] == ["TIM/20 Incidents/Demo Incident.md"]

    mission_id = "mission:TIM/30%20Missions/Demo%20Mission.md"
    bundle = service.mission_context(mission_id)
    assert bundle["gates"] == ["gate:TIM/00%20HOME/Demo%20Gate.md"]
    assert bundle["incidents"] == [incident["id"]]
    assert service.gate_context(bundle["gates"][0])["missions"] == [mission_id]

    gate = _first(service, "Gate")
    gate_context = service.gate_context(gate["id"])
    assert "depends_on" in gate_context and "blocked_by" in gate_context

    agent = service.agent_context("qwen")
    assert agent["role"] and agent["verified_tools"] == []
    assert service.agent_context("nope")["error"] == "not_found"


def _ids(service, node_type):
    return service.search("", node_type=node_type)["matches"] or \
           [{"id": None}]


def _first(service, node_type):
    for node in service.store.nodes(node_type):
        return node
    raise AssertionError(f"no {node_type} node")


def test_exports_deterministic_and_valid(service):
    payload = export_json(service)
    assert payload["nodes"] and payload["edges"]
    mermaid = export_mermaid(service)
    assert mermaid.startswith("graph TD") and "-->" in mermaid
    assert export_mermaid(service) == mermaid  # stable ids -> stable export
    dot = export_dot(service)
    assert dot.startswith("digraph tim {")
    graphml = export_graphml(service)
    assert graphml.startswith("<?xml") and "</graphml>" in graphml


def test_incremental_refresh_and_deletion(service, code_tree: Path):
    before = service.stats()
    second = service.refresh_code()
    assert second["FILES_SCANNED"] == 0
    assert second["nodes_added"] == 0 and second["edges_added"] == 0

    # modify a file -> only that slice updates
    target = code_tree / "src" / "demo" / "core.py"
    target.write_text(target.read_text() + "\n\ndef extra():\n    return 2\n")
    changed = service.refresh_code()
    assert changed["FILES_SCANNED"] == 1
    assert changed["nodes_added"] >= 1  # new function node

    # delete a file -> symbols retired, no stale edges
    (code_tree / "src" / "demo" / "extra.py").write_text("def gone():\n    return 0\n")
    service.refresh_code()
    assert service.get_node("function:src/demo/extra.py:gone").get("id")
    (code_tree / "src" / "demo" / "extra.py").unlink()
    service.refresh_code()
    assert service.get_node("function:src/demo/extra.py:gone") == {
        "error": "not_found", "id": "function:src/demo/extra.py:gone"}
    for edge in service.store.edges_from("module:src.demo.extra"):
        assert edge["to"] != "function:src/demo/extra.py:gone"

    after = service.refresh_docs()
    assert after["nodes_added"] == 0  # docs unchanged -> idempotent


def test_determinism_double_run(service):
    first = service.stats()["set_hashes"]
    service.refresh_code()
    service.refresh_docs()
    service.refresh_runtime_readonly()
    second = service.stats()["set_hashes"]
    assert first == second


def test_secret_metadata_never_stored(service, code_tree: Path):
    poisoned = code_tree / "src" / "demo" / "secret.py"
    poisoned.write_text('SECRET_TOKEN = "ghp_' + "A" * 40 + '"\n')
    service.refresh_code()
    blob = json.dumps(service.store.nodes(limit=100000))
    assert "ghp_" not in blob
    poisoned.unlink()
    service.refresh_code()


def test_bounded_limits_enforced(service):
    neighbors = service.neighbors("module:src.demo.core", limit=1)
    assert len(neighbors["edges"]) <= HARD_MAX_LIMIT
    huge = service.neighbors("module:src.demo.core", limit=10 ** 9)
    assert len(huge["edges"]) <= HARD_MAX_LIMIT


def test_store_has_no_dangling_edges(service):
    """Graph integrity invariant: every edge endpoint is an existing node
    (R12: the old CALLS resolver violated this in the real graph)."""
    ids = {node["id"] for node in service.store.nodes(limit=10 ** 6)}
    for node in service.store.nodes(limit=10 ** 6):
        for edge in service.store.edges_from(node["id"]):
            assert edge["to"] in ids, edge
            assert edge["from"] in ids, edge


def test_code_field_shows_up_in_impact(code_tree, vault_tree, tmp_path):
    note = vault_tree / "TIM" / "40 Systeme" / "Demo Engine.md"
    note.parent.mkdir()
    note.write_text("---\ntype: system\nstatus: active\ncode: [src/demo/core.py]\n---\n# x\n")
    service = GraphService(GraphStore(tmp_path / "impact.sqlite"), code_tree, vault=vault_tree)
    service.refresh_code()
    service.refresh_docs()
    impact = service.impact("file:src/demo/core.py")
    assert impact["documentation"] == ["note:TIM/40%20Systeme/Demo%20Engine.md"]
