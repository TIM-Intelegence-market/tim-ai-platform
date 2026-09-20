"""Router determinism/routes/fallbacks, tool health, packs, profiles,
bridge mapping (STEPS 7-14, 17, 23)."""
from __future__ import annotations

import json

import pytest

from src.agent_infra.bridge import BridgeError, serena_symbol_to_graph_id
from src.agent_infra.health import ToolHealthRegistry
from src.agent_infra.packs import DEFAULT_BUDGET, AgentContextPack, RepairContextPack
from src.agent_infra.profiles import OPENCODE, GLM, PROFILES, QWEN
from src.agent_infra.router import (AVAILABLE, UNAVAILABLE, ContextRequest,
                                    Intent, Tool, ToolRouter)

ALL_AVAILABLE = {tool.value: AVAILABLE for tool in Tool}


# ---- router ---------------------------------------------------------------

def test_canonical_routes():
    router = ToolRouter()
    decision = router.route(ContextRequest(intent=Intent.SYMBOL_DEFINITION,
                                           symbol="CandleAggregator"), ALL_AVAILABLE)
    assert decision.primary_tool is Tool.SERENA
    assert router.route(ContextRequest(intent=Intent.MISSION), ALL_AVAILABLE).primary_tool is Tool.GRAPH_MCP
    assert router.route(ContextRequest(intent=Intent.INCIDENT), ALL_AVAILABLE).primary_tool is Tool.GRAPH_MCP
    assert router.route(ContextRequest(intent=Intent.VISUALIZATION), ALL_AVAILABLE).primary_tool is Tool.GRAPHIFY
    assert router.route(ContextRequest(intent=Intent.PAST_DECISION), ALL_AVAILABLE).primary_tool is Tool.OBSIDIAN
    assert router.route(ContextRequest(intent=Intent.IMPLEMENTATION), ALL_AVAILABLE).primary_tool is Tool.OPENCODE
    assert router.route(ContextRequest(intent=Intent.CODE_SEARCH), ALL_AVAILABLE).primary_tool is Tool.NATIVE_SEARCH


def test_router_deterministic():
    request = ContextRequest(intent=Intent.TESTS_FOR_SYMBOL, symbol="X")
    router = ToolRouter()
    run1 = router.route(request, ALL_AVAILABLE)
    run2 = router.route(request, ALL_AVAILABLE)
    assert run1.decision_hash(request) == run2.decision_hash(request)
    assert run1.decision_hash(request) == run1.decision_hash(request)


def test_router_falls_back_when_serena_unavailable():
    availability = dict(ALL_AVAILABLE, Serena=UNAVAILABLE)
    decision = ToolRouter().route(
        ContextRequest(intent=Intent.SYMBOL_DEFINITION), availability)
    assert decision.primary_tool is Tool.GRAPH_MCP  # secondary is available
    assert "unavailable" in decision.reason


def test_router_blocked_when_nothing_available():
    availability = {tool.value: UNAVAILABLE for tool in Tool}
    decision = ToolRouter().route(
        ContextRequest(intent=Intent.MISSION), availability)
    assert decision.blocked is True
    assert "BLOCKED" in decision.reason


def test_router_review_blocked_when_qwen_unavailable():
    availability = dict(ALL_AVAILABLE, Qwen=UNAVAILABLE)
    decision = ToolRouter().route(ContextRequest(intent=Intent.REVIEW),
                                  availability)
    assert decision.blocked is True  # honest BLOCKED, no substitute reviewer


# ---- health ----------------------------------------------------------------

def test_health_registry_states_with_evidence():
    registry = ToolHealthRegistry(probes={
        "Serena": lambda: (AVAILABLE, "pid 1"),
        "Qwen": lambda: (UNAVAILABLE, "qwen2.5:7b NOT installed"),
        "Boom": lambda: (_ for _ in ()).throw(RuntimeError("x")),
    })
    statuses = registry.refresh()
    assert statuses["Serena"]["state"] == AVAILABLE
    assert statuses["Serena"]["evidence"] == "pid 1"
    assert statuses["Serena"]["observed_at"]
    assert statuses["Qwen"]["state"] == UNAVAILABLE
    assert statuses["Boom"]["state"] == "UNKNOWN"  # probe failure fails closed
    assert registry.availability == {"Serena": AVAILABLE, "Qwen": UNAVAILABLE,
                                     "Boom": "UNKNOWN"}


# ---- packs -----------------------------------------------------------------

def test_pack_budget_truncates():
    pack = AgentContextPack(request_summary="t")
    pack.references = [{"i": i} for i in range(100)]
    pack.tests = [{"i": i} for i in range(50)]
    pack.enforce_budget()
    assert len(pack.references) == DEFAULT_BUDGET.MAX_REFERENCES
    assert len(pack.tests) == DEFAULT_BUDGET.MAX_TESTS
    assert pack.truncated.get("references") is True


def test_pack_serialize_char_cap():
    pack = AgentContextPack(request_summary="t")
    pack.docs = ["x" * 5000 for _ in range(100)]
    pack.enforce_budget()
    text = pack.serialize()
    assert len(text) <= DEFAULT_BUDGET.MAX_CONTEXT_CHARS + 2000  # final json overhead


def test_repair_pack_validation():
    complete = RepairContextPack(incident={"id": "i"}, fingerprint="f",
                                 classification="DATA_QUALITY",
                                 affected_graph_nodes=["n"],
                                 affected_symbols=[{"s": 1}], tests=[{"t": 1}],
                                 prior_repairs=[], mission_gates=[{"g": 1}],
                                 safety_constraints=["no prod writes"])
    assert complete.validate() == []
    empty = RepairContextPack(incident={}, fingerprint="", classification="")
    problems = empty.validate()
    assert "missing required field: incident" in problems
    assert "missing required field: fingerprint" in problems


# ---- profiles ---------------------------------------------------------------

def test_agent_profiles_complete():
    for profile in (OPENCODE, GLM, QWEN):
        assert profile.preferred_tools and profile.write_authority
        assert "production_db_writes" in profile.forbidden_actions
    assert QWEN.write_authority.startswith("none")
    assert "blind_full_repository_parsing" in QWEN.forbidden_actions
    assert set(PROFILES) == {"OpenCode", "GLM", "Qwen"}


# ---- bridge -----------------------------------------------------------------

def test_bridge_maps_serena_symbols_to_canonical_ids():
    assert serena_symbol_to_graph_id({
        "relative_path": "src/data_ingestion/aggregator.py",
        "name_path": "CandleAggregator", "kind": "Class"}
    ) == "class:src/data_ingestion/aggregator.py:CandleAggregator"
    assert serena_symbol_to_graph_id({
        "relative_path": "src/x.py", "name_path": "Cls/method",
        "kind": "Method"}).endswith("Cls.method")
    assert serena_symbol_to_graph_id({
        "relative_path": "src/x.py", "name_path": "foo", "kind": "Function"}
    ) == "function:src/x.py:foo"
    assert serena_symbol_to_graph_id({
        "relative_path": "tests/test_x.py", "name_path": "test_it",
        "kind": "Test"}) == "test:tests/test_x.py:test_it"


def test_bridge_unknown_kind_falls_to_file_identity():
    assert serena_symbol_to_graph_id({
        "relative_path": "src/x.py", "name_path": "odd", "kind": "Module"}
    ) == "file:src/x.py"


def test_bridge_rejects_incomplete_symbols():
    with pytest.raises(BridgeError):
        serena_symbol_to_graph_id({"relative_path": "", "name_path": "x",
                                   "kind": "Class"})
