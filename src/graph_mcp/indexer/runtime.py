"""Runtime graph indexer (STEP 9): services discovered from code, never a
hard-coded fantasy architecture. A Service node exists per src/* package
that participates in process wiring (imported by main.py or importing the
database layer); DEPENDS_ON edges come from the internal import graph
between those packages."""
from __future__ import annotations

import ast
from pathlib import Path

from src.graph_mcp.indexer import IndexResult
from src.graph_mcp.indexer.code import iter_python_files
from src.graph_mcp.schema import Edge, EdgeType, Node, NodeType, stable_id, utc_now


class RuntimeIndexer:
    source = "runtime"

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def _package_imports(self) -> tuple[set[str], dict[str, set[str]]]:
        """(wired packages, package -> imported src packages)."""
        packages: set[str] = set()
        imports: dict[str, set[str]] = {}
        wired: set[str] = set()
        for path in iter_python_files(self.root):
            relative = path.relative_to(self.root)
            parts = relative.parts
            if parts[0] != "src" or len(parts) < 3:
                continue  # src/<pkg>/... only; src/__init__.py is not a service
            package = parts[1]
            packages.add(package)
            imported = imports.setdefault(package, set())
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                targets: list[str] = []
                if isinstance(node, ast.Import):
                    targets = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    targets = [node.module]
                for target in targets:
                    tail = target.split(".")
                    if tail[0] == "src" and len(tail) > 1:
                        imported.add(tail[1])
            if parts[0:1] == ("src",) and len(parts) == 2:  # src/<pkg>/__init__.py
                pass
        main_file = self.root / "main.py"
        if main_file.is_file():
            try:
                tree = ast.parse(main_file.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                tree = None
            if tree:
                for node in ast.walk(tree):
                    targets: list[str] = []
                    if isinstance(node, ast.Import):
                        targets = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        targets = [node.module]
                    for target in targets:
                        tail = target.split(".")
                        if tail[0] == "src" and len(tail) > 1:
                            wired.add(tail[1])
        return wired, imports

    def index(self) -> IndexResult:
        result = IndexResult(source=self.source)
        observed = utc_now()
        wired, imports = self._package_imports()
        services = set(imports) | wired
        for package in sorted(services):
            node_id = stable_id("service", package)
            result.nodes.append(Node(
                node_id, NodeType.SERVICE, f"src.{package}", self.source,
                f"src/{package}",
                {"discovery": "code_imports",
                 "wired_via": "main.py" if package in wired else "internal"}
            ).record(observed))
        for package, dependencies in sorted(imports.items()):
            if package not in wired:
                continue
            for dependency in sorted(dependencies):
                if dependency != package and dependency in wired:
                    result.edges.append(Edge(
                        stable_id("service", package), stable_id("service", dependency),
                        EdgeType.DEPENDS_ON,
                        {"resolution_method": "internal_import_graph"},
                        evidence=[f"src/{package}"]).record())
        result.metrics.update({"SERVICES": len(wired), "NODES_ADDED": len(result.nodes),
                               "EDGES_ADDED": len(result.edges)})
        return result
