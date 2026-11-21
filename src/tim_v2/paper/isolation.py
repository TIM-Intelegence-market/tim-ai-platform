"""Static proof that the V2.8 paper package cannot reach a real order endpoint.

Exit criterion of V2.8 (docs/tim_v2/milestones.md): "technical proof that no real order endpoint is reachable".
This module parses every source file of ``src/tim_v2/paper`` and fails if any of them

* imports a network, process or database module, or any TIM module outside this package
  (exchange clients, the Bitunix research client and the live trader all live outside it), or
* contains a string with a URL scheme (http, https, ws or wss followed by a colon and two slashes), or
* calls ``__import__``, ``import_module``, ``eval``, ``exec``, ``compile`` or a process call such as ``os.system``
  (no dynamic way around the import check).

``tests/test_tim_v2_paper.py`` additionally imports and runs the package with sockets disabled.
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PACKAGE = "src.tim_v2.paper"

ALLOWED_STDLIB = frozenset({
    "__future__", "argparse", "ast", "collections", "dataclasses", "datetime", "decimal", "enum", "hashlib",
    "json", "os", "pathlib", "sys", "typing",
})
FORBIDDEN_CALLS = frozenset({"__import__", "eval", "exec", "compile", "import_module", "system", "popen", "fork",
                             "execv", "execve", "execvp", "spawnv", "spawnl", "startfile", "open_connection"})
URL_MARKERS = tuple(scheme + ":" + "/" * 2 for scheme in ("http", "https", "ws", "wss"))  # built, not literal


@dataclass(frozen=True, slots=True)
class IsolationReport:
    ok: bool
    files: tuple[str, ...]
    violations: tuple[str, ...]
    source_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "files": list(self.files), "violations": list(self.violations),
                "source_sha256": self.source_sha256, "allowed_stdlib": sorted(ALLOWED_STDLIB)}


def _module_ok(name: str, level: int) -> bool:
    if level > 0:  # relative import: stays inside this package
        return True
    root = name.split(".")[0]
    if name == PACKAGE or name.startswith(PACKAGE + "."):
        return True
    return root in ALLOWED_STDLIB


def scan(package_dir: Path = PACKAGE_DIR) -> IsolationReport:
    violations: list[str] = []
    files = sorted(p for p in package_dir.rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(package_dir).as_posix()
        source = path.read_bytes()
        digest.update(rel.encode() + b"\0" + source)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not _module_ok(alias.name, 0):
                        violations.append(f"{rel}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if not _module_ok(node.module or "", node.level):
                    violations.append(f"{rel}:{node.lineno} from {node.module} import")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                low = node.value.lower()
                if any(m in low for m in URL_MARKERS):
                    violations.append(f"{rel}:{node.lineno} URL literal")
            elif isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ""
                if name in FORBIDDEN_CALLS:
                    violations.append(f"{rel}:{node.lineno} call {name}")
    return IsolationReport(not violations, tuple(p.relative_to(package_dir).as_posix() for p in files),
                           tuple(violations), digest.hexdigest())
