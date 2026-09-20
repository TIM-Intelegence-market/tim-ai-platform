"""Preflight flows + all failure modes (STEPS 12, 16, 23): bounded packs,
mission/symbol attachment, honest BLOCKED on unavailable tools, ambiguous
and missing symbols, secret exclusion."""
from __future__ import annotations

import json

from src.agent_infra.health import ToolHealthRegistry
from src.agent_infra.packs import AgentContextPack
from src.agent_infra.preflight import ContextPreflight
from src.agent_infra.router import AVAILABLE, UNAVAILABLE

from _fakes import FakeSerena, fake_serena_factory


def make_preflight(graph_service, serena: FakeSerena | None,
                   overrides: dict | None = None) -> ContextPreflight:
    probes = {
        "Serena": lambda: (AVAILABLE if serena is not None else UNAVAILABLE,
                           "fake"),
        "TIMGraphMCP": lambda: (AVAILABLE, "store seeded"),
        "Graphify": lambda: (AVAILABLE, "binary"),
        "Obsidian": lambda: (AVAILABLE, "vault"),
        "Qwen": lambda: (UNAVAILABLE, "qwen2.5:7b NOT installed"),
        "Ollama": lambda: (AVAILABLE, "up"),
        "NativeSearch": lambda: (AVAILABLE, "grep"),
        "pytest": lambda: (AVAILABLE, "venv"),
    }
    probes.update(overrides or {})
    return ContextPreflight(graph_service,
                            serena_factory=fake_serena_factory(serena) if serena else None,
                            registry=ToolHealthRegistry(probes=probes))


def test_preflight_builds_bounded_pack(graph_service, fake_serena):
    preflight = make_preflight(graph_service, fake_serena)
    pack = preflight.build_pack("Work on CandleAggregator",
                                mission_query="Demo Mission",
                                symbol="CandleAggregator",
                                symbol_path="src/data_ingestion/aggregator.py")
    assert pack.mission["name"] == "Demo Mission"
    assert pack.symbols[0]["canonical_graph_id"] == \
        "class:src/data_ingestion/aggregator.py:CandleAggregator"
    assert pack.tests and all(t["file"].startswith("tests/") for t in pack.tests)
    assert pack.impact["analysis"] == "STATIC_GRAPH_IMPACT"
    assert pack.tool_status["Qwen"]["state"] == UNAVAILABLE
    assert "production database" in pack.safety_constraints[0]
    serialized = pack.serialize()
    assert len(serialized) <= 24000 + 2000
    assert "password" not in serialized.lower()
    assert pack.source_provenance["symbols"] == "Serena"


def test_preflight_mission_missing_is_honest_blocker(graph_service, fake_serena):
    preflight = make_preflight(graph_service, fake_serena)
    pack = preflight.build_pack("x", mission_query="No Such Mission")
    assert pack.mission is None
    assert any("mission not found" in b for b in pack.blockers)


def test_preflight_symbol_missing(graph_service):
    empty = FakeSerena(symbols=[])
    preflight = make_preflight(graph_service, empty)
    pack = preflight.build_pack("x", symbol="MissingThing")
    assert any("symbol not found" in b for b in pack.blockers)


def test_preflight_ambiguous_symbol_takes_first_and_bounds(graph_service):
    two = FakeSerena(symbols=[
        {"name_path": "CandleAggregator", "kind": "Class",
         "relative_path": "src/a.py"},
        {"name_path": "CandleAggregator", "kind": "Class",
         "relative_path": "src/b.py"},
    ])
    preflight = make_preflight(graph_service, two)
    pack = preflight.build_pack("x", symbol="CandleAggregator")
    assert len(pack.symbols) == 2  # primary + one extra, bounded by MAX_SYMBOLS
    assert pack.symbols[0]["relative_path"] == "src/a.py"  # deterministic pick


def test_preflight_serena_unavailable_explicit_blocked(graph_service):
    preflight = make_preflight(graph_service, None)  # Serena UNAVAILABLE
    pack = preflight.build_pack("x", symbol="CandleAggregator")
    assert pack.source_provenance["symbols"].startswith("BLOCKED: Serena unavailable")
    assert pack.symbols == []


def test_preflight_graph_unavailable_mission_blocked(tmp_path):
    from src.graph_mcp.service import GraphService
    from src.graph_mcp.store import GraphStore
    empty_service = GraphService(GraphStore(tmp_path / "empty.sqlite"), tmp_path)
    preflight = make_preflight(empty_service, FakeSerena())
    pack = preflight.build_pack("x", mission_query="Demo Mission")
    assert pack.mission is None
    assert any("mission not found" in b for b in pack.blockers)


def test_plan_reports_routing_and_health(graph_service, fake_serena):
    from src.agent_infra.router import ContextRequest, Intent
    preflight = make_preflight(graph_service, fake_serena)
    plan = preflight.plan(ContextRequest(intent=Intent.TESTS_FOR_SYMBOL,
                                         symbol="CandleAggregator"))
    assert plan["decision"]["primary_tool"] == "Serena"
    assert plan["decision"]["secondary_tools"] == ["TIMGraphMCP"]
    assert plan["tool_status"]["Qwen"]["state"] == UNAVAILABLE


def test_pack_excludes_secret_paths(graph_service, fake_serena):
    preflight = make_preflight(graph_service, fake_serena)
    pack = preflight.build_pack("x", symbol="CandleAggregator")
    blob = json.dumps(pack.to_dict())
    for forbidden in (".env", "password", "token=", "private_key",
                      "database-password"):
        assert forbidden not in blob.lower()
