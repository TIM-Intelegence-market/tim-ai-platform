"""Code graph indexer (STEP 7): AST-based, deterministic, incremental.

Nodes: Repository, Directory, File, Module, Class, Function, Method, Test.
Edges: CONTAINS, DEFINES, IMPORTS, TESTS, CALLS (only attribute-resolvable,
same-module or same-class calls; anything ambiguous is skipped, never
guessed — STEP 7's honesty rule)."""
from __future__ import annotations

import ast
import time
from pathlib import Path

from src.graph_mcp import SCHEMA_VERSION
from src.graph_mcp.indexer import IndexResult
from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules",
             ".runtime", "graphify-out", ".mypy_cache", ".ruff_cache", "work"}


def iter_python_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def module_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    return ".".join(relative.parts)


class CodeIndexer:
    source = "code"

    def __init__(self, root: Path, repo_name: str = "tim") -> None:
        self.root = root.resolve()
        self.repo_name = repo_name

    def index(self, file_hashes: dict[str, str] | None = None) -> IndexResult:
        started = time.monotonic()
        result = IndexResult(source=self.source)
        files = iter_python_files(self.root)
        current = {str(path): _sha256_file(path) for path in files}
        result.files = current
        unchanged = bool(file_hashes) and set(file_hashes) == set(current) and all(
            file_hashes[path] == digest for path, digest in current.items())
        if unchanged:
            # STEP 26/29 fast path: nothing to parse, nothing to apply
            result.metrics.update({"FILES_TOTAL": len(current), "FILES_SCANNED": 0,
                                   "UNCHANGED": True,
                                   "INDEX_DURATION_SECONDS": round(time.monotonic() - started, 3)})
            return result
        if file_hashes and set(file_hashes) != set(current):
            file_hashes = None  # files added/removed -> full reparse (safe slice replace)
        observed = utc_now()
        repo_node = Node(stable_id("repo", self.repo_name), NodeType.REPOSITORY,
                         self.repo_name, self.source, str(self.root),
                         {"remote": "uezeyiraydin-cell/tim-ai-platform"})
        result.nodes.append(repo_node.record(observed))
        known_modules: set[str] = {module_name(self.root, Path(p)) for p in current}

        for path in files:
            relative = path.relative_to(self.root).as_posix()
            digest = current[str(path)]
            if file_hashes and file_hashes.get(str(path)) == digest:
                continue  # unchanged file: skip the parse only
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue  # unparseable files are skipped, not fatal
            result.metrics["FILES_SCANNED"] = result.metrics.get("FILES_SCANNED", 0) + 1
            self._index_file(result, tree, relative, module_name(self.root, path),
                             observed, known_modules)

        result.metrics.update({
            "FILES_TOTAL": len(current),
            "INDEX_DURATION_SECONDS": round(time.monotonic() - started, 3),
            "NODES_ADDED": len(result.nodes),
            "EDGES_ADDED": len(result.edges),
        })
        return result

    def _index_file(self, result: IndexResult, tree: ast.Module, relative: str,
                    module: str, observed: str, known_modules: set[str]) -> None:
        src = self.source
        symbols = self._module_symbols(tree, relative)
        repo_id = stable_id("repo", self.repo_name)
        file_id = stable_id("file", relative)
        result.nodes.append(Node(file_id, NodeType.FILE, relative, src, relative,
                                 {"lines": len(tree.body)}).record(observed))
        result.edges.append(Edge(repo_id, file_id, EdgeType.CONTAINS).record())
        module_id = stable_id("module", module)
        result.nodes.append(Node(module_id, NodeType.MODULE, module, src, relative,
                                 {}).record(observed))
        result.edges.append(Edge(file_id, module_id, EdgeType.DEFINES).record())

        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for target in sorted(imported):
            for candidate in (target, f"src.{target}"):
                if candidate in known_modules and candidate != module:
                    result.edges.append(Edge(
                        module_id, stable_id("module", candidate), EdgeType.IMPORTS,
                        {"resolution_method": "ast_import",
                         "confidence": 1.0}).record())
                    break

        is_test = relative.startswith("tests/")
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                class_id = stable_id("class", relative, node.name)
                result.nodes.append(Node(class_id, NodeType.CLASS, node.name, src,
                                         relative, {"lineno": node.lineno}).record(observed))
                result.edges.append(Edge(module_id, class_id, EdgeType.DEFINES).record())
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_id = stable_id("method", relative,
                                              f"{node.name}.{item.name}")
                        result.nodes.append(Node(method_id, NodeType.METHOD,
                                                 f"{node.name}.{item.name}", src, relative,
                                                 {"lineno": item.lineno}).record(observed))
                        result.edges.append(Edge(class_id, method_id,
                                                 EdgeType.DEFINES).record())
                        self._calls(result, tree, item, method_id, relative,
                                    observed, symbols)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = NodeType.TEST if (is_test and node.name.startswith("test")) else NodeType.FUNCTION
                fn_id = stable_id("test" if kind is NodeType.TEST else "function",
                                  relative, node.name)
                result.nodes.append(Node(fn_id, kind, node.name, src, relative,
                                         {"lineno": node.lineno}).record(observed))
                result.edges.append(Edge(module_id, fn_id, EdgeType.DEFINES).record())
                self._calls(result, tree, node, fn_id, relative, observed, symbols)
                if kind is NodeType.TEST:
                    self._tests_edge(result, relative, module, fn_id, observed)

    def _tests_edge(self, result: IndexResult, relative: str, module: str,
                    test_id: str, observed: str) -> None:
        """tests/test_<x>.py TESTS module <x> — filename convention, labeled
        as such (confidence < 1); explicit imports beat the convention."""
        convention = relative.split("/")[-1]
        convention = convention[len("test_"):] if convention.startswith("test_") else convention
        convention = convention[:-len("_test")] if convention.endswith("_test") else convention
        target = None
        resolution = "filename_convention"
        confidence = 0.7
        for candidate in (f"src.{convention}", convention):
            if self._module_exists(candidate):
                target, resolution = candidate, "filename_convention"
                break
        if target is None:
            for edge in result.edges:
                if edge["from"] == stable_id("module", module) and edge["type"] == "IMPORTS":
                    if edge["to"].startswith("module:src."):
                        target = edge["to"].split(":", 1)[1]
                        resolution, confidence = "test_file_import", 0.9
                        break
        if target:
            result.edges.append(Edge(
                test_id, stable_id("module", target), EdgeType.TESTS,
                {"resolution_method": resolution, "confidence": confidence},
                evidence=[f"tests/{relative.split('/')[-1]}"]).record())

    def _module_exists(self, module: str) -> bool:
        parts = module.split(".")
        path = self.root.joinpath(*parts).with_suffix(".py")
        return path.is_file()

    def _module_symbols(self, tree: ast.Module, relative: str) -> dict[str, tuple[str, str]]:
        """Bare-name -> (prefix, id) table for THIS file only. Methods are
        keyed 'Class.name' plus bare name when unambiguous; a bare name
        colliding between function and method is omitted (never guessed)."""
        table: dict[str, tuple[str, str]] = {}
        conflicts: set[str] = set()
        functions = {n.name for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                table[node.name] = ("class", stable_id("class", relative, node.name))
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        qualified = f"{node.name}.{item.name}"
                        table[qualified] = ("method", stable_id("method", relative, qualified))
                        if item.name in functions or item.name in table:
                            conflicts.add(item.name)
                        else:
                            table[item.name] = ("method", stable_id("method", relative, qualified))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in table or node.name in conflicts:
                    conflicts.add(node.name)
                    table.pop(node.name, None)
                else:
                    table[node.name] = ("function", stable_id("function", relative, node.name))
        for name in conflicts:
            table.pop(name, None)
        return table

    def _calls(self, result: IndexResult, tree: ast.Module, fn: ast.FunctionDef | ast.AsyncFunctionDef,
               fn_id: str, relative: str, observed: str, symbols: dict) -> None:
        """CALLS edges only for calls resolvable to a symbol defined in the
        same file — everything else stays unresolved by design. Method
        targets resolve to method:<file>:Class.name ids (never phantom
        function ids)."""
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            target_name = None
            if isinstance(node.func, ast.Name):
                target_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                target_name = node.func.attr
            if target_name in ("self",):
                continue
            entry = symbols.get(target_name)
            if entry is None:
                continue
            _, target_id = entry
            if target_id != fn_id:
                result.edges.append(Edge(
                    fn_id, target_id, EdgeType.CALLS,
                    {"resolution_method": "same_file_symbol_table",
                     "confidence": 0.6},
                    evidence=[f"{relative}:L{node.lineno}"]).record())


def _sha256_file(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()
