"""TIM_TOOL_ROUTER_V1 (STEPS 7-9).

Deterministic: same ContextRequest + same tool availability always yields
the same RoutingDecision (verified by decision hash). The router chooses
CONTEXT TOOLS only — it never grants write or production authority."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from src.agent_infra import TOOL_ROUTER_VERSION


class Intent(StrEnum):
    SYMBOL_DEFINITION = "symbol_definition"
    REFERENCES = "references"
    TESTS_FOR_SYMBOL = "tests_for_symbol"
    MISSION = "mission"
    INCIDENT = "incident"
    IMPACT = "impact"
    PAST_DECISION = "past_decision"
    VISUALIZATION = "visualization"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    CODE_SEARCH = "code_search"
    RUNTIME_STATE = "runtime_state"


class Tool(StrEnum):
    SERENA = "Serena"
    GRAPH_MCP = "TIMGraphMCP"
    GRAPHIFY = "Graphify"
    OBSIDIAN = "Obsidian"
    QWEN = "Qwen"
    OPENCODE = "OpenCode"
    GLM = "GLM"
    PYTEST = "pytest"
    NATIVE_SEARCH = "NativeSearch"
    OPS_MCP = "TIMOpsMCP"


@dataclass(frozen=True, slots=True)
class ContextRequest:
    intent: Intent
    entity: str = ""
    symbol: str = ""
    path: str = ""
    mission: str = ""
    incident: str = ""
    max_results: int = 50
    need_history: bool = False
    need_visualization: bool = False
    need_review: bool = False

    def canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    primary_tool: Tool
    secondary_tools: tuple[Tool, ...] = ()
    fallback: Tool | None = None
    reason: str = ""
    availability: dict[str, str] = field(default_factory=dict)
    blocked: bool = False
    router_version: str = TOOL_ROUTER_VERSION

    def decision_hash(self, request: ContextRequest) -> str:
        payload = {"request": request.canonical(),
                   "primary": self.primary_tool.value,
                   "secondary": [t.value for t in self.secondary_tools],
                   "fallback": self.fallback.value if self.fallback else None,
                   "blocked": self.blocked}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


# Canonical route table: intent -> (primary, secondary, fallback)
ROUTES: dict[Intent, tuple[Tool, tuple[Tool, ...], Tool | None]] = {
    Intent.SYMBOL_DEFINITION: (Tool.SERENA, (Tool.GRAPH_MCP,), Tool.NATIVE_SEARCH),
    Intent.REFERENCES: (Tool.SERENA, (Tool.GRAPH_MCP,), Tool.NATIVE_SEARCH),
    Intent.TESTS_FOR_SYMBOL: (Tool.SERENA, (Tool.GRAPH_MCP,), Tool.NATIVE_SEARCH),
    Intent.MISSION: (Tool.GRAPH_MCP, (Tool.OBSIDIAN,), None),
    Intent.INCIDENT: (Tool.GRAPH_MCP, (Tool.OBSIDIAN,), None),
    Intent.IMPACT: (Tool.GRAPH_MCP, (Tool.SERENA,), None),
    Intent.PAST_DECISION: (Tool.OBSIDIAN, (Tool.GRAPH_MCP,), None),
    Intent.VISUALIZATION: (Tool.GRAPHIFY, (Tool.GRAPH_MCP,), None),
    Intent.IMPLEMENTATION: (Tool.OPENCODE, (Tool.GLM,), None),
    Intent.REVIEW: (Tool.QWEN, (), None),
    Intent.CODE_SEARCH: (Tool.NATIVE_SEARCH, (Tool.SERENA,), None),
    Intent.RUNTIME_STATE: (Tool.OPS_MCP, (Tool.GRAPH_MCP,), None),
}

AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"
UNKNOWN = "UNKNOWN"


class ToolRouter:
    """Same request + same availability map -> same decision, always."""

    def route(self, request: ContextRequest,
              availability: dict[str, str]) -> RoutingDecision:
        primary, secondary, fallback = ROUTES[request.intent]
        state = {tool.value: availability.get(tool.value, UNKNOWN)
                 for tool in Tool}
        reason = f"canonical route for {request.intent.value}"

        if state[primary.value] != AVAILABLE:
            # explicit fallback or honest BLOCKED — never fake availability
            for candidate in (*secondary, fallback) if fallback else secondary:
                if state.get(candidate.value) == AVAILABLE:
                    return RoutingDecision(
                        candidate, (), primary,
                        reason=f"primary {primary.value} unavailable "
                               f"({state[primary.value]}); routed to fallback "
                               f"{candidate.value}",
                        availability=state)
            return RoutingDecision(
                primary, secondary, fallback,
                reason=f"no available tool for {request.intent.value} "
                       f"(primary {primary.value}={state[primary.value]}) — BLOCKED",
                availability=state, blocked=True)

        usable_secondary = tuple(t for t in secondary
                                 if state.get(t.value) == AVAILABLE)
        return RoutingDecision(primary, usable_secondary, fallback,
                               reason=reason, availability=state)
