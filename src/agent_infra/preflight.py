"""TIM_AGENT_CONTEXT_PREFLIGHT_V1 (STEPS 12, 16).

Orchestrates the bounded pre-coding context flow:

  mission -> Graph MCP mission context
  component -> Serena symbol lookup (scoped read-only instance)
  references/tests -> Serena
  cross-system impact -> Graph MCP
  historical decisions -> Graph MCP Decision nodes (Obsidian-indexed)
  tool health -> ToolHealthRegistry

Result: one bounded AgentContextPack. No repository dumps, no vault
dumps, no secret paths. Serena access is injected so tests run against
fakes; the live path spawns a scoped SerenaClient per call."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from src.agent_infra import PREFLIGHT_VERSION
from src.agent_infra.bridge import serena_symbol_to_graph_id
from src.agent_infra.health import ToolHealthRegistry
from src.agent_infra.packs import DEFAULT_BUDGET, AgentContextPack, ContextBudget
from src.agent_infra.router import AVAILABLE, ContextRequest, Intent, ToolRouter
from src.agent_infra.serena_client import SerenaClient, flatten_references
from src.graph_mcp.service import GraphService


class SerenaAdapter(Protocol):
    def find_symbol(self, pattern: str, relative_path: str = "",
                    substring_matching: bool = False) -> list[dict]: ...
    def find_referencing_symbols(self, name_path: str, relative_path: str) -> dict: ...


class LiveSerena:
    """Scoped read-only serena instance against the canonical read source."""

    def __init__(self, read_root: str | None = None) -> None:
        self.read_root = read_root or os.environ.get(
            "TIM_SERENA_READ_ROOT",
            str(Path.home() / "Documents/TIM/tim"))

    def __call__(self) -> "LiveSerena._Session":
        return self._Session(self.read_root)

    class _Session:
        def __init__(self, read_root: str) -> None:
            self._client = SerenaClient(read_root, timeout=120)

        def __enter__(self) -> "LiveSerena._Session":
            self._client.start()
            self._client.initialize()
            return self

        def __exit__(self, *_) -> None:
            self._client.stop()

        def find_symbol(self, pattern: str, relative_path: str = "",
                        substring_matching: bool = False) -> list[dict]:
            return self._client.find_symbol(pattern, relative_path,
                                            substring_matching)

        def find_referencing_symbols(self, name_path: str,
                                     relative_path: str) -> dict:
            return self._client.find_referencing_symbols(name_path, relative_path)


SAFETY_CONSTRAINTS = [
    "production database is out of scope (read-only at most)",
    "TIM runtime must not be restarted by workers",
    "writes only inside the isolated worker worktree",
    "no secrets in packs, logs or evidence",
    "trading remains disabled; no order paths",
]


class ContextPreflight:
    def __init__(self, graph: GraphService, serena_factory=None,
                 registry: ToolHealthRegistry | None = None,
                 budget: ContextBudget | None = None) -> None:
        self.graph = graph
        self.serena_factory = serena_factory or LiveSerena()
        self.registry = registry or ToolHealthRegistry()
        self.router = ToolRouter()
        self.budget = budget or DEFAULT_BUDGET

    # -- routing view ----------------------------------------------------

    def plan(self, request: ContextRequest) -> dict[str, Any]:
        statuses = self.registry.refresh()
        decision = self.router.route(request, self.registry.availability)
        return {"request": request.canonical(), "decision": {
            "primary_tool": decision.primary_tool.value,
            "secondary_tools": [t.value for t in decision.secondary_tools],
            "fallback": decision.fallback.value if decision.fallback else None,
            "reason": decision.reason, "blocked": decision.blocked,
        }, "tool_status": statuses}

    # -- full preflight pack ----------------------------------------------

    def build_pack(self, summary: str, *, mission_query: str = "",
                   symbol: str = "", symbol_path: str = "",
                   max_results: int = 50) -> AgentContextPack:
        self.registry.refresh()
        availability = self.registry.availability
        pack = AgentContextPack(request_summary=summary, _budget=self.budget)
        pack.tool_status = self.registry.status()
        pack.safety_constraints = list(SAFETY_CONSTRAINTS)

        if mission_query:
            pack.source_provenance["mission"] = "TIMGraphMCP"
            self._attach_mission(pack, mission_query)

        if symbol:
            if availability.get("Serena") != AVAILABLE:
                pack.source_provenance["symbols"] = (
                    "BLOCKED: Serena unavailable "
                    f"({availability.get('Serena')}) — explicit fallback required")
            else:
                pack.source_provenance["symbols"] = "Serena"
                self._attach_symbols(pack, symbol, symbol_path)

        pack.enforce_budget()
        pack.serialize()  # hard budget enforcement (raises if impossible)
        return pack

    def _attach_mission(self, pack: AgentContextPack, mission_query: str) -> None:
        matches = self.graph.search(mission_query, node_type="Mission",
                                    limit=self.budget.MAX_NOTES)["matches"]
        if not matches:
            pack.blockers.append(f"mission not found in graph: {mission_query!r}")
            return
        context = self.graph.mission_context(matches[0]["id"])
        pack.mission = {"id": matches[0]["id"], "name": matches[0]["name"],
                        "status": context.get("metadata", {}).get("status")}
        pack.gates = [{"id": g} for g in context.get("gates", [])]
        pack.incidents = [{"id": i} for i in context.get("incidents", [])]
        pack.docs = list(context.get("notes", []))
        decisions = self.graph.search("", node_type="Decision",
                                      limit=self.budget.MAX_NOTES)
        pack.decisions = [{"id": d["id"], "name": d["name"]}
                          for d in decisions["matches"]]

    def _attach_symbols(self, pack: AgentContextPack, symbol: str,
                        symbol_path: str) -> None:
        with self.serena_factory() as serena:
            found = serena.find_symbol(symbol, symbol_path)
            if not found:
                pack.blockers.append(f"symbol not found: {symbol!r}")
                return
            primary = found[0]
            pack.symbols = [{
                "name_path": primary.get("name_path"),
                "kind": primary.get("kind"),
                "relative_path": primary.get("relative_path"),
                "canonical_graph_id": serena_symbol_to_graph_id(primary),
                "lines": primary.get("body_location"),
            }] + [{"name_path": s.get("name_path"), "kind": s.get("kind"),
                   "relative_path": s.get("relative_path")}
                  for s in found[1:self.budget.MAX_SYMBOLS]]
            references = flatten_references(
                serena.find_referencing_symbols(
                    primary["name_path"], primary["relative_path"]))
            pack.references = references[:self.budget.MAX_REFERENCES]
            pack.tests = [r for r in references
                          if r["file"].startswith("tests/")][:self.budget.MAX_TESTS]
            canonical = serena_symbol_to_graph_id(primary)
            node = self.graph.get_node(canonical)
            if "error" not in node:
                pack.impact = self.graph.impact(canonical)
                pack.source_provenance["impact"] = "TIMGraphMCP"
