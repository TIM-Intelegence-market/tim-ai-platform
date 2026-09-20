"""Obsidian connector (STEP 13) + mission/gate/incident/decision graph
(STEPS 10-11 input) + bugfixer recipe indexing.

Reads note frontmatter and wikilinks only. Never writes the vault. The
vault path is configuration, so tests use fixtures and production uses the
real vault path."""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.graph_mcp.indexer import IndexResult
from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\]\n|#]+)(?:#[^\]\n|]*)?(?:\|[^\]\n]*)?\]\]")
_CODE_SPAN = re.compile(r"`[^`\n]*`")

_TYPE_TO_NODE = {
    "mission": NodeType.MISSION,
    "gate": NodeType.GATE,
    "incident": NodeType.INCIDENT,
    "decision": NodeType.DECISION,
    "decision-log": NodeType.DECISION,
    "moc": NodeType.OBSIDIAN_NOTE,
    "tool": NodeType.TOOL,
    "report": NodeType.OBSIDIAN_NOTE,
}
_KNOWN = {"mission", "gate", "incident", "decision", "decision-log", "moc",
          "tool", "report"}


def parse_frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "-", "\t")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip("\"'")
    return fields


class ObsidianIndexer:
    source = "obsidian"

    def __init__(self, vault: Path, content_root: str = "TIM") -> None:
        self.vault = Path(vault)
        self.content_root = self.vault / content_root

    def index(self) -> IndexResult:
        result = IndexResult(source=self.source)
        observed = utc_now()
        src = self.source
        notes: dict[str, dict] = {}
        if not self.content_root.is_dir():
            result.metrics["VAULT_FOUND"] = False
            return result
        result.metrics["VAULT_FOUND"] = True
        for path in sorted(self.content_root.rglob("*.md")):
            if any(part.startswith(".") for part in path.parts):
                continue
            relative = path.relative_to(self.vault).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            frontmatter = parse_frontmatter(text)
            title = path.stem
            note_id = stable_id("note", relative)
            # STEP 13: only structural metadata, never note bodies/secrets
            metadata = {key: frontmatter[key] for key in
                        ("type", "status", "created", "updated", "area", "verdict",
                         "severity", "system", "evidence", "owner")
                        if key in frontmatter}
            notes[note_id] = {"id": note_id, "title": title, "path": relative,
                              "frontmatter": frontmatter, "metadata": metadata}
            result.nodes.append(Node(note_id, NodeType.OBSIDIAN_NOTE, title, src,
                                     relative, metadata).record(observed))
            note_type = frontmatter.get("type", "").lower()
            if note_type in _KNOWN and note_type not in ("moc", "report"):
                node_type = _TYPE_TO_NODE[note_type]
                typed_id = stable_id(
                    {"mission": "mission", "gate": "gate", "incident": "incident",
                     "decision": "decision", "decision-log": "decision",
                     "tool": "agent-tool"}[note_type],
                    relative)
                result.nodes.append(Node(
                    typed_id, node_type, title, src, relative,
                    {"note": note_id, **metadata}).record(observed))
                result.edges.append(Edge(typed_id, note_id,
                                         EdgeType.DOCUMENTED_BY).record())
        self._references(result, notes, observed)
        result.metrics.update({"NOTES": len(notes), "NODES_ADDED": len(result.nodes),
                               "EDGES_ADDED": len(result.edges)})
        return result

    def _references(self, result: IndexResult, notes: dict[str, dict],
                    observed: str) -> None:
        by_title = {note["title"]: note for note in notes.values()}
        for note in notes.values():
            path = self.vault / note["path"]
            text = _CODE_SPAN.sub("", path.read_text(encoding="utf-8", errors="replace"))
            for target in sorted({t.strip() for t in _WIKILINK.findall(text)}):
                destination = notes.get(stable_id("note", self._resolve(target)))
                if destination is None:
                    destination = by_title.get(target)
                if destination and destination["id"] != note["id"]:
                    result.edges.append(Edge(
                        note["id"], destination["id"], EdgeType.REFERENCES,
                        {"resolution_method": "wikilink"},
                        evidence=[note["path"]]).record())

    def _resolve(self, title: str) -> str:
        candidates = [p for p in self.content_root.rglob(f"{title}.md")]
        if candidates:
            return candidates[0].relative_to(self.vault).as_posix()
        return title  # unresolved; caller treats missing gracefully


class RecipeIndexer:
    """STEP 11: Bugfixer repair recipes -> RepairRecipe nodes with
    VALIDATED_BY test-name edges where the recipe declares them."""

    source = "bugfixer"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def index(self) -> IndexResult:
        result = IndexResult(source=self.source)
        observed = utc_now()
        recipes_root = self.root / "schemas/bugfixer/recipes"
        if not recipes_root.is_dir():
            result.metrics["RECIPES"] = 0
            return result
        for path in sorted(recipes_root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            for entry in payload.get("entries", []):
                recipe_id = entry.get("remediation_id")
                if not recipe_id:
                    continue
                node_id = stable_id("recipe", recipe_id, entry.get("version", ""))
                metadata = {
                    "category": entry.get("matching_rules", {}).get("category", ""),
                    "risk": entry.get("risk", ""), "autonomy_level":
                        entry.get("autonomy_level", ""),
                    "forbidden_actions_count": len(entry.get("forbidden_actions", [])),
                    "production_auto_apply": "NO",
                }
                result.nodes.append(Node(node_id, NodeType.REPAIR_RECIPE, recipe_id,
                                         self.source,
                                         path.relative_to(self.root).as_posix(),
                                         metadata).record(observed))
                for test_name in entry.get("targeted_tests", []):
                    # declared-by-recipe Test nodes: real declarations, file
                    # resolution explicitly unresolved (never guessed)
                    test_id = stable_id("test-name", test_name)
                    result.nodes.append(Node(
                        test_id, NodeType.TEST, test_name, self.source,
                        path.relative_to(self.root).as_posix(),
                        {"declared_in": recipe_id,
                         "resolved_to_file": None}).record(observed))
                    result.edges.append(Edge(
                        node_id, test_id, EdgeType.VALIDATED_BY,
                        {"resolution_method": "recipe_declaration"},
                        evidence=[path.name]).record())
            result.metrics["RECIPES"] = result.metrics.get("RECIPES", 0) + len(
                payload.get("entries", []))
        return result
