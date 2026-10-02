"""GraphService: refresh orchestration + query API behind the MCP tools
(STEPS 15-24). All traversal is depth- and size-bounded; impact is labeled
STATIC_GRAPH_IMPACT unless runtime evidence exists."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from src.graph_mcp import SCHEMA_VERSION
from src.graph_mcp.indexer.agents import AgentIndexer
from src.graph_mcp.indexer.code import CodeIndexer
from src.graph_mcp.indexer.database import DatabaseIndexer
from src.graph_mcp.indexer.github import GithubIndexer
from src.graph_mcp.indexer.obsidian import ObsidianIndexer, RecipeIndexer
from src.graph_mcp.indexer.runtime import RuntimeIndexer
from src.graph_mcp.redaction import redact
from src.graph_mcp.schema import utc_now
from src.graph_mcp.store import GraphStore

MAX_DEPTH = 4
HARD_MAX_DEPTH = 8
DEFAULT_LIMIT = 50
HARD_MAX_LIMIT = 200


def _why_matched(node: dict[str, Any], needle: str, mode: str) -> str | None:
    """Why this row matched (STEP 16). Rows arrive SQL-filtered, so the
    label describes the applied filter; exact-id gets the precise label."""
    if mode == "id":
        return "exact id" if node["id"].lower() == needle else "id substring"
    if mode == "path":
        return "path substring"
    if mode == "metadata":
        return "metadata substring"
    return "name/path substring"


def _bounded_limit(limit: int | None) -> int:
    return max(1, min(HARD_MAX_LIMIT, limit or DEFAULT_LIMIT))


def _bounded_depth(depth: int | None) -> int:
    return max(1, min(HARD_MAX_DEPTH, depth or MAX_DEPTH))


class GraphService:
    def __init__(self, store: GraphStore, root: Path, vault: Path | None = None,
                 ki_tools: Path | None = None) -> None:
        self.store = store
        self.root = Path(root).resolve()
        self.vault = Path(vault) if vault else None
        self.ki_tools = Path(ki_tools) if ki_tools else None

    # -- refresh (own index only) ------------------------------------

    def refresh_code(self) -> dict[str, Any]:
        started = time.monotonic()
        previous = self.store.file_states("code")
        result = CodeIndexer(self.root).index(previous or None)
        if result.metrics.get("UNCHANGED"):
            applied = {"nodes_added": 0, "nodes_updated": 0, "nodes_removed": 0,
                       "edges_added": 0, "edges_removed": 0}
        else:
            applied = self._apply(result, redact_all=True)
        self.store.forget_stale("code", result.files)
        for path, digest in result.files.items():
            self.store.record_file_state(path, digest, utc_now(), source="code")
        return self._metrics("refresh_code", started, result, applied)

    def refresh_docs(self) -> dict[str, Any]:
        started = time.monotonic()
        results = [ObsidianIndexer(self.vault, repo_root=self.root).index()
                   if self.vault else None,
                   RecipeIndexer(self.root).index(),
                   AgentIndexer(self.ki_tools, self.vault,
                                graph_mcp_present=(self.root / 'src' / 'graph_mcp').is_dir()).index()]
        metrics: dict[str, Any] = {"mode": "refresh_docs"}
        totals = {"nodes_added": 0, "nodes_updated": 0, "nodes_removed": 0,
                  "edges_added": 0, "edges_removed": 0}
        for result in results:
            if result is None:
                continue
            applied = self._apply(result, redact_all=True)
            for key in totals:
                totals[key] += applied.get(key, 0)
            metrics.update(result.metrics)
        metrics.update(totals)
        metrics.update({"duration_seconds": round(time.monotonic() - started, 3),
                        "schema_version": SCHEMA_VERSION})
        return metrics

    def refresh_runtime_readonly(self) -> dict[str, Any]:
        """Runtime + database schema graph. Read-only by construction:
        schema comes from the repository file, services from import graph."""
        started = time.monotonic()
        results = [RuntimeIndexer(self.root).index(), DatabaseIndexer(self.root).index()]
        metrics: dict[str, Any] = {"mode": "refresh_runtime_readonly"}
        for result in results:
            applied = self._apply(result, redact_all=True)
            metrics.update(result.metrics)
            metrics.update(applied)
        metrics.update({"duration_seconds": round(time.monotonic() - started, 3),
                        "schema_version": SCHEMA_VERSION})
        return metrics

    def index_github_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = GithubIndexer().index_payload(payload)
        applied = self._apply(result, redact_all=True)
        return {**result.metrics, **applied}

    def _metrics(self, mode: str, started: float, result, applied: dict[str, int]) -> dict[str, Any]:
        return {"mode": mode, **result.metrics, **applied,
                "duration_seconds": round(time.monotonic() - started, 3),
                "schema_version": SCHEMA_VERSION}

    def _apply(self, result, redact_all: bool) -> dict[str, int]:
        nodes = result.nodes
        if redact_all:
            nodes = [{**node, "metadata": redact(node["metadata"])} for node in nodes]
        return self.store.apply(nodes, result.edges, source_prefix=result.source)

    # -- health / stats -------------------------------------------------

    def health(self) -> dict[str, Any]:
        stats = self.store.stats()
        return {"status": "ok" if stats["nodes_total"] else "empty",
                "nodes_total": stats["nodes_total"],
                "edges_total": stats["edges_total"],
                "store": str(self.store.path),
                "read_only_tim": True, "schema_version": SCHEMA_VERSION}

    def stats(self) -> dict[str, Any]:
        return {**self.store.stats(), "set_hashes": self.store.set_hashes()}

    # -- queries (STEPS 16-20) -------------------------------------------

    def get_node(self, node_id: str) -> dict[str, Any]:
        node = self.store.node(node_id)
        if node is None:
            return {"error": "not_found", "id": node_id}
        return node

    def search(self, query: str, node_type: str | None = None,
               limit: int | None = None, mode: str = "name") -> dict[str, Any]:
        limit = _bounded_limit(limit)
        needle = query.strip().lower()
        rows = self.store.search_nodes(needle, node_type, mode, limit + 1)
        truncated = len(rows) > limit
        matches = [
            {"id": node["id"], "type": node["type"], "name": node["name"],
             "why_matched": _why_matched(node, needle, mode),
             "source": node["source"]}
            for node in rows[:limit]
        ]
        return {"query": query, "mode": mode, "matches": matches,
                "truncated": truncated, "total_returned": len(matches)}

    def neighbors(self, node_id: str, direction: str = "both",
                  edge_types: list[str] | None = None, limit: int | None = None) -> dict[str, Any]:
        limit = _bounded_limit(limit)
        if self.store.node(node_id) is None:
            return {"error": "not_found", "id": node_id}
        types = tuple(edge_types) if edge_types else None
        edges: list[dict[str, Any]] = []
        if direction in ("out", "both"):
            edges.extend(self.store.edges_from(node_id, types))
        if direction in ("in", "both"):
            edges.extend(self.store.edges_to(node_id, types))
        edges = edges[:limit]
        node_ids = {e["from"] for e in edges} | {e["to"] for e in edges}
        nodes = {n["id"]: n for n in (self.store.node(i) for i in node_ids) if n}
        return {"node": node_id, "direction": direction, "nodes": list(nodes.values()),
                "edges": edges, "truncated": len(edges) >= limit}

    def dependencies(self, node_id: str, limit: int | None = None) -> dict[str, Any]:
        return self.neighbors(node_id, direction="out",
                              edge_types=["DEPENDS_ON", "IMPORTS", "REQUIRES",
                                          "READS", "WRITES", "USES_TOOL"],
                              limit=limit)

    def dependents(self, node_id: str, limit: int | None = None) -> dict[str, Any]:
        return self.neighbors(node_id, direction="in",
                              edge_types=["DEPENDS_ON", "IMPORTS", "REQUIRES",
                                          "READS", "WRITES", "TESTS", "CALLS",
                                          "DEFINES"],
                              limit=limit)

    def path(self, source: str, target: str, max_depth: int | None = None) -> dict[str, Any]:
        depth = _bounded_depth(max_depth)
        if self.store.node(source) is None or self.store.node(target) is None:
            return {"error": "not_found", "source": source, "target": target}
        frontier = [(source, [source])]
        visited = {source}
        while frontier:
            node, trail = frontier.pop(0)
            if len(trail) > depth:
                break
            for edge in self.store.edges_from(node):
                nxt = edge["to"]
                if nxt in visited:
                    continue
                if nxt == target:
                    return {"found": True, "depth": len(trail), "path": trail + [nxt],
                            "max_depth": depth}
                visited.add(nxt)
                frontier.append((nxt, trail + [nxt]))
            if len(visited) > HARD_MAX_LIMIT * 4:
                break
        return {"found": False, "source": source, "target": target, "max_depth": depth}

    def impact(self, node_id: str) -> dict[str, Any]:
        """STEP 20: static impact only — labeled as such."""
        if self.store.node(node_id) is None:
            return {"error": "not_found", "id": node_id}
        direct = self.store.edges_to(node_id)
        categories: dict[str, list[str]] = {"direct_dependents": [], "tests": [],
                                            "missions": [], "runtime_components": [],
                                            "incidents": [], "documentation": []}
        for edge in direct:
            node = self.store.node(edge["from"])
            if node is None:
                continue
            bucket = {
                "Test": "tests", "Mission": "missions", "Service": "runtime_components",
                "Process": "runtime_components", "Incident": "incidents",
                "ObsidianNote": "documentation", "Gate": "missions",
            }.get(node["type"], "direct_dependents")
            categories[bucket].append(node["id"])
        # notes that document this node (`<node> DOCUMENTED_BY <note>`)
        for edge in self.store.edges_from(node_id, ("DOCUMENTED_BY",)):
            if edge["to"] not in categories["documentation"]:
                categories["documentation"].append(edge["to"])
        return {"node": node_id, "analysis": "STATIC_GRAPH_IMPACT",
                "runtime_evidence": False, **categories,
                "note": "static graph impact; no runtime evidence implied"}

    # -- context tools (STEPS 21-23) --------------------------------------

    def mission_context(self, mission_id: str) -> dict[str, Any]:
        node = self.store.node(mission_id)
        if node is None:
            alternative = self.search(mission_id.split(":")[-1], node_type="Mission")
            return {"error": "not_found", "id": mission_id,
                    "search_suggestions": alternative["matches"][:5]}
        context = self._context(node)
        context["gates"] = [e["to"] for e in self.store.edges_from(
            mission_id, ("DEPENDS_ON", "REQUIRES", "BLOCKS"))]
        context["blocked_gates"] = [e["to"] for e in self.store.edges_from(
            mission_id, ("BLOCKS",))]
        context["incidents"] = [n["id"] for n in context.pop("nodes", [])
                                if n["type"] == "Incident"]
        context["notes"] = [e["to"] for e in self.store.edges_from(
            mission_id, ("DOCUMENTED_BY",))]
        context["agents"] = [e["from"] for e in self.store.edges_to(
            mission_id, ("ASSIGNED_TO",))]
        return context

    def incident_context(self, incident_id: str) -> dict[str, Any]:
        node = self.store.node(incident_id)
        if node is None:
            return {"error": "not_found", "id": incident_id}
        context = self._context(node)
        context["classification"] = node["metadata"].get("status", "unknown")
        context["known_recipes"] = [e["to"] for e in self.store.edges_from(
            incident_id, ("REPAIRED_BY",))]
        context["blocked_gates"] = [e["to"] for e in self.store.edges_from(
            incident_id, ("BLOCKS",))]
        context["prior_occurrences"] = [e["from"] for e in self.store.edges_to(
            incident_id, ("RELATED_TO",))]
        context["evidence_refs"] = sorted({ev for e in self.store.edges_from(incident_id)
                                           for ev in e["evidence"]})
        return context

    def gate_context(self, gate_id: str) -> dict[str, Any]:
        node = self.store.node(gate_id)
        if node is None:
            return {"error": "not_found", "id": gate_id}
        context = self._context(node)
        context["depends_on"] = [e["to"] for e in self.store.edges_from(
            gate_id, ("DEPENDS_ON",))]
        context["blocked_by"] = [e["from"] for e in self.store.edges_to(
            gate_id, ("BLOCKS",))]
        context["missions"] = [e["from"] for e in self.store.edges_to(
            gate_id, ("DEPENDS_ON", "REQUIRES", "BLOCKS"))]
        return context

    def agent_context(self, agent: str) -> dict[str, Any]:
        node_id = agent if agent.startswith("agent:") else f"agent:{agent}"
        node = self.store.node(node_id)
        if node is None:
            return {"error": "not_found", "id": node_id}
        context = self._context(node)
        context["role"] = node["metadata"].get("role", "unknown")
        context["verified_tools"] = [e["to"] for e in self.store.edges_from(
            node_id, ("USES_TOOL",))]
        context["known_limitations"] = node["metadata"].get("limitations", [])
        context["related_missions"] = [e["to"] for e in self.store.edges_from(
            node_id, ("ASSIGNED_TO",))]
        return context

    def _context(self, node: dict[str, Any]) -> dict[str, Any]:
        neighbors = self.neighbors(node["id"], limit=DEFAULT_LIMIT)
        return {**node, "nodes": neighbors["nodes"], "edges": neighbors["edges"]}
