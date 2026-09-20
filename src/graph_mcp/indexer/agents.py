"""Agent graph indexer (STEP 12): agents and tools from the KI TOOLS
datapacket + locally verifiable availability. Only AVAILABLE/CONNECTED/
WORKING states with actual local evidence are set; everything else stays
'unknown'. No invented executions, no secrets."""
from __future__ import annotations

import socket
from pathlib import Path

from src.graph_mcp.indexer import IndexResult
from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now

# Roles from mission briefs / KI TOOLS README; capability details live in
# the Obsidian tool notes, this graph records identity + relations only.
AGENTS: tuple[dict, ...] = (
    {"id": "chatgpt", "name": "ChatGPT", "role": "central coordinator / quality control",
     "evidence": "mission briefs 2026-09-17/18"},
    {"id": "opencode", "name": "OpenCode", "role": "verifier / patcher; loads KI TOOLS skills",
     "evidence": "KI TOOLS README"},
    {"id": "zcode-glm", "name": "Zcode GLM", "role": "local terminal/code/execution worker",
     "evidence": "workspace AGENTS.md"},
    {"id": "qwen", "name": "Qwen", "role": "local analysis/repair stage (qwen2.5:7b)",
     "evidence": "Qwen Self Repair Gate 2026-09-17"},
    {"id": "ollama", "name": "Ollama", "role": "local model runtime :11434",
     "evidence": "KI TOOLS context-mode SKILL; gate mission"},
    {"id": "graphify", "name": "Graphify", "role": "architecture/relationship visualization",
     "evidence": "graphify-out artifacts; graphify CLI (project PATH, e.g. ~/.local/bin/graphify)"},
    {"id": "obsidian", "name": "Obsidian", "role": "persistent human-readable knowledge layer",
     "evidence": "TIM OBSIDIAN vault"},
    {"id": "serena", "name": "Serena",
     "role": "semantic code intelligence (symbol lookup, references, "
             "precise navigation, scoped edits)",
     "evidence": "serena 2.0.0.dev0 process; KI TOOLS serena role 2026-09-18"},
)
KI_TOOLS_PACKAGES: tuple[str, ...] = ("caveman", "ponytail", "context-mode", "RTK")
AVAILABILITY_CHECKS = {
    "ollama": ("127.0.0.1", 11434),
}


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class AgentIndexer:
    source = "agents"

    def __init__(self, ki_tools: Path | None = None, vault: Path | None = None,
                 graph_mcp_present: bool = False) -> None:
        self.ki_tools = Path(ki_tools) if ki_tools else None
        self.vault = Path(vault) if vault else None
        self.graph_mcp_present = graph_mcp_present

    def _serena_relations(self, result: IndexResult) -> None:
        """Serena integration edges (agent-infrastructure-v1, 2026-09-18),
        emitted only when the Graph MCP service is part of the indexed tree
        (no dangling endpoints by construction). Only evidenced relations:
        GLM used Serena live (acceptance + controlled edit), OpenCode's
        profile routes Serena as preferred tool, and the bridge connects
        Serena to the Graph MCP service."""
        serena_id = stable_id("agent", "serena")
        result.edges.append(Edge(
            stable_id("agent", "zcode-glm"), serena_id, EdgeType.USES_TOOL,
            {"resolution_method": "mission_usage"},
            evidence=["agent_infra_acceptance.py PASS 2026-09-18",
                      "controlled edit via serena replace_content 2026-09-18"]).record())
        result.edges.append(Edge(
            stable_id("agent", "opencode"), serena_id, EdgeType.USES_TOOL,
            {"resolution_method": "agent_profile"},
            evidence=["OpenCode profile preferred_tools (Step 17)"]).record())
        result.edges.append(Edge(
            serena_id, stable_id("service", "graph_mcp"), EdgeType.RELATED_TO,
            {"resolution_method": "stable_id_bridge"},
            evidence=["src/agent_infra/bridge.py; SERENA_GRAPH_BRIDGE=PASS"]).record())

    def _vault_tool_notes(self) -> dict[str, str]:
        """Frontmatter-typed `tool` notes keyed by note title -> vault path.
        Only names; note bodies are never read here."""
        from src.graph_mcp.indexer.obsidian import parse_frontmatter
        notes: dict[str, str] = {}
        if not self.vault:
            return notes
        content = self.vault / "TIM"
        if not content.is_dir():
            return notes
        for path in sorted(content.rglob("*.md")):
            if any(part.startswith(".") for part in path.parts):
                continue
            try:
                frontmatter = parse_frontmatter(
                    path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if frontmatter.get("type", "").lower() == "tool":
                notes[path.stem] = path.relative_to(self.vault).as_posix()
        return notes

    def index(self) -> IndexResult:
        result = IndexResult(source=self.source)
        observed = utc_now()
        src = self.source
        vault_tool_notes = self._vault_tool_notes()
        for agent in AGENTS:
            availability = "unknown"
            check = AVAILABILITY_CHECKS.get(agent["id"])
            if check and _port_open(*check):
                availability = "AVAILABLE"
            elif agent["id"] == "obsidian" and self.vault and self.vault.is_dir():
                availability = "AVAILABLE"
            elif agent["id"] == "graphify":
                graphify_bin = Path.home() / ".local/bin/graphify"
                if graphify_bin.is_file():
                    availability = "AVAILABLE"
            elif agent["id"] == "serena":
                import subprocess
                probe = subprocess.run(["pgrep", "-f", "serena start-mcp-server"],
                                       capture_output=True)
                if probe.returncode == 0:
                    availability = "AVAILABLE"
            node_id = stable_id("agent", agent["id"])
            result.nodes.append(Node(
                node_id, NodeType.AGENT, agent["name"], src, "",
                {"role": agent["role"], "role_evidence": agent["evidence"],
                 "availability": availability}).record(observed))
            note = vault_tool_notes.get(agent["name"])
            if note:
                # evidence: the vault note of type `tool` documenting this agent
                result.edges.append(Edge(
                    node_id, stable_id("agent-tool", note),
                    EdgeType.DOCUMENTED_BY,
                    {"resolution_method": "vault_tool_note_by_name"},
                    evidence=[note]).record())
        opencode_id = stable_id("agent", "opencode")
        if self.ki_tools and self.ki_tools.is_dir():
            for package in KI_TOOLS_PACKAGES:
                if (self.ki_tools / package).is_dir() or (
                        self.ki_tools / f"{package}-SKILL.md").is_file():
                    tool_id = stable_id("tool", package)
                    result.nodes.append(Node(
                        tool_id, NodeType.TOOL, package, src,
                        str(self.ki_tools / package),
                        {"datapacket": str(self.ki_tools)}).record(observed))
                    result.edges.append(Edge(
                        opencode_id, tool_id, EdgeType.USES_TOOL,
                        {"resolution_method": "ki_tools_readme"},
                        evidence=["KI TOOLS/README.md"]).record())
        if self.graph_mcp_present:
            self._serena_relations(result)
        result.metrics.update({"AGENTS": len(AGENTS),
                               "NODES_ADDED": len(result.nodes),
                               "EDGES_ADDED": len(result.edges)})
        return result
