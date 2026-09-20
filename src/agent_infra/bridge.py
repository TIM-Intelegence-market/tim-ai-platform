"""Serena -> Graph MCP stable-ID bridge (STEPS 5-6).

Graph MCP canonical IDs are the single identity contract:
  file:<rel-path> · class:<rel-path>:<Class> · method:<rel-path>:<Class.method>
  function:<rel-path>:<function> · test:<rel-path>:<test_name>
Serena's internal identifiers never become canonical — only its
(relative_path, name_path, kind) triple maps into the contract."""
from __future__ import annotations

from typing import Any

from src.graph_mcp.schema import stable_id

_KIND_PREFIX = {
    "Class": "class",
    "Function": "function",
    "Method": "method",
    "Test": "test",
}


class BridgeError(ValueError):
    pass


def serena_symbol_to_graph_id(symbol: dict[str, Any]) -> str:
    """Map one serena find_symbol result to the canonical Graph MCP id.
    Serena nests name paths with '/', the canonical contract uses '.'."""
    relative_path = symbol.get("relative_path") or ""
    name_path = (symbol.get("name_path") or "").replace("/", ".")
    kind = symbol.get("kind") or ""
    if not relative_path or not name_path:
        raise BridgeError(f"incomplete serena symbol: {symbol!r}")
    prefix = _KIND_PREFIX.get(kind)
    if prefix is None:
        # Unknown kinds map to file identity only — never a guessed symbol id
        return stable_id("file", relative_path)
    return stable_id(prefix, relative_path, name_path)


def reference_to_file_id(file: str) -> str:
    return stable_id("file", file)
