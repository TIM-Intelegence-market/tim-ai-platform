"""RUNTIME_STATE intent routing (OPS_MCP primary, GRAPH_MCP fallback)."""
from __future__ import annotations

from src.agent_infra.router import (AVAILABLE, ROUTES, UNAVAILABLE,
                                    ContextRequest, Intent, Tool, ToolRouter)

ALL_AVAILABLE = {tool.value: AVAILABLE for tool in Tool}


def test_runtime_state_primary_is_ops_mcp_when_all_available():
    decision = ToolRouter().route(
        ContextRequest(intent=Intent.RUNTIME_STATE), ALL_AVAILABLE)
    assert decision.primary_tool is Tool.OPS_MCP
    assert decision.blocked is False


def test_runtime_state_routes_to_graph_mcp_when_ops_unavailable():
    availability = dict(ALL_AVAILABLE, **{Tool.OPS_MCP.value: UNAVAILABLE})
    decision = ToolRouter().route(
        ContextRequest(intent=Intent.RUNTIME_STATE), availability)
    assert decision.primary_tool is Tool.GRAPH_MCP
    assert decision.fallback is Tool.OPS_MCP
    assert decision.blocked is False


def test_runtime_state_blocked_when_both_unavailable():
    availability = dict(ALL_AVAILABLE, **{Tool.OPS_MCP.value: UNAVAILABLE,
                                          Tool.GRAPH_MCP.value: UNAVAILABLE})
    decision = ToolRouter().route(
        ContextRequest(intent=Intent.RUNTIME_STATE), availability)
    assert decision.blocked is True
    assert "BLOCKED" in decision.reason


def test_runtime_state_decision_hash_is_stable():
    request = ContextRequest(intent=Intent.RUNTIME_STATE)
    router = ToolRouter()
    first = router.route(request, ALL_AVAILABLE)
    second = router.route(request, ALL_AVAILABLE)
    assert first.decision_hash(request) == second.decision_hash(request)


def test_every_intent_has_a_route():
    for intent in Intent:
        assert intent in ROUTES
    assert ROUTES[Intent.RUNTIME_STATE] == (
        Tool.OPS_MCP, (Tool.GRAPH_MCP,), None)
