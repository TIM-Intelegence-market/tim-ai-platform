"""Obsidian connector (STEP 13) + mission/gate/incident/decision graph
(STEPS 10-11 input) + bugfixer recipe indexing.

Reads note frontmatter and wikilinks only. Never writes the vault. The
vault path is configuration, so tests use fixtures and production uses the
real vault path.

Wikilinks between typed notes become typed edges (mission -> gate is
REQUIRES, other typed pairs REFERENCES), so context bundles see gates and
incidents. A `code:` frontmatter list links a note to repository files or
services (`<file> DOCUMENTED_BY <note>`); entries are only linked when they
exist under the repository root, never guessed."""
from __future__ import annotations

import json
import re
from pathlib import Path

from src.graph_mcp.indexer import IndexResult
from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_WIKILINK = re.compile(r"\[\[([^\]\n|#]+)(?:#[^\]\n|]*)?(?:\|[^\]\n]*)?\]\]")
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_CODE_FIELD = re.compile(r"^code:[ \t]*(.*)$", re.MULTILINE)
_PACKAGE = re.compile(r"^[A-Za-z0-9_]+$")

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
# Template folders hold placeholder notes (type: mission etc.); indexing
# them would create fake Mission/Gate/Incident nodes.
TEMPLATE_DIRS = frozenset({"99 Vorlagen", "Templates"})
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


def parse_code_field(text: str) -> list[str]:
    """`code:` as inline list (`[a, b]`), comma list, or YAML block list."""
    match = _FRONTMATTER.match(text)
    if not match:
        return []
    block = match.group(1)
    field = _CODE_FIELD.search(block)
    if not field:
        return []
    inline = field.group(1).strip()
    if inline:
        items = inline.strip("[]").split(",")
    else:
        items = []
        for line in block[field.end():].splitlines()[1:]:
            stripped = line.strip()
            if not stripped.startswith("- "):
                break
            items.append(stripped[2:])
    return [item.strip().strip("\"'") for item in items if item.strip().strip("\"'")]


class ObsidianIndexer:
    source = "obsidian"

    def __init__(self, vault: Path, content_root: str = "TIM",
                 repo_root: Path | None = None) -> None:
        self.vault = Path(vault)
        self.content_root = self.vault / content_root
        self.repo_root = Path(repo_root).resolve() if repo_root else None

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
            if path.relative_to(self.content_root).parts[0] in TEMPLATE_DIRS:
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
                              "frontmatter": frontmatter, "metadata": metadata,
                              "typed": None, "code": parse_code_field(text)}
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
                notes[note_id]["typed"] = (typed_id, note_type)
        self._references(result, notes, observed)
        self._code_links(result, notes)
        result.metrics.update({"NOTES": len(notes), "NODES_ADDED": len(result.nodes),
                               "EDGES_ADDED": len(result.edges)})
        return result

    def _references(self, result: IndexResult, notes: dict[str, dict],
                    observed: str) -> None:
        by_title = {note["title"]: note for note in notes.values()}
        typed_pairs: set[tuple[str, str, str]] = set()
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
                    self._typed_link(result, note, destination, typed_pairs)

    @staticmethod
    def _typed_link(result: IndexResult, note: dict, destination: dict,
                    seen: set[tuple[str, str, str]]) -> None:
        if not (note["typed"] and destination["typed"]):
            return
        (src_id, src_type), (dst_id, dst_type) = note["typed"], destination["typed"]
        if {src_type, dst_type} == {"mission", "gate"}:
            # a mission needs its gate, whichever note carries the link
            edge_type = EdgeType.REQUIRES
            if src_type == "gate":
                src_id, dst_id = dst_id, src_id
        else:
            edge_type = EdgeType.REFERENCES
        key = (src_id, dst_id, str(edge_type))
        if src_id == dst_id or key in seen:
            return
        seen.add(key)
        result.edges.append(Edge(src_id, dst_id, edge_type,
                                 {"resolution_method": "wikilink_typed"},
                                 evidence=[note["path"]]).record())

    def _code_links(self, result: IndexResult, notes: dict[str, dict]) -> None:
        linked: set[tuple[str, str]] = set()
        unresolved = 0
        for note in notes.values():
            for entry in note["code"]:
                target = self._code_target(entry)
                if target is None:
                    unresolved += 1
                    continue
                if (target, note["id"]) in linked:
                    continue
                linked.add((target, note["id"]))
                result.edges.append(Edge(target, note["id"], EdgeType.DOCUMENTED_BY,
                                         {"resolution_method": "frontmatter_code"},
                                         evidence=[note["path"]]).record())
        result.metrics.update({"CODE_LINKS": len(linked), "CODE_LINKS_UNRESOLVED": unresolved})

    def _code_target(self, entry: str) -> str | None:
        """Only existing repository paths are linked; nothing is guessed."""
        if self.repo_root is None:
            return None
        if entry.startswith("service:"):
            package = entry.removeprefix("service:").strip()
            if _PACKAGE.match(package) and (self.repo_root / "src" / package).is_dir():
                return stable_id("service", package)
            return None
        relative = entry.strip().strip("/")
        candidate = (self.repo_root / relative).resolve()
        if not relative or not candidate.is_relative_to(self.repo_root):
            return None
        if candidate.is_file():
            return stable_id("file", relative)
        parts = Path(relative).parts
        if candidate.is_dir() and len(parts) == 2 and parts[0] == "src":
            return stable_id("service", parts[1])
        return None

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
