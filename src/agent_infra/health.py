"""ToolHealthRegistry (STEP 10, STEP 11).

Read-only probes; every state carries observed_at + evidence. No stale
AVAILABLE claims: a tool is AVAILABLE only when its probe just passed.
Probes are injectable so tests can fake availability deterministically."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.agent_infra.router import AVAILABLE, UNKNOWN, UNAVAILABLE

_VAULT = os.environ.get("TIM_OBSIDIAN_VAULT", "")
VAULT = Path(_VAULT) if _VAULT else Path.home() / "Documents/TIM/TIM OBSIDIAN"
GRAPH_STORE = Path(".runtime/graph/graph.sqlite")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def probe_opencode() -> tuple[str, str]:
    """OpenCode executor presence (desktop-aware, read-only, fail-closed).

    AVAILABLE only when the OpenCode Desktop execution context is
    actually evidenced: ``OPENCODE_CLIENT=desktop`` plus a validated
    project marker (``OPENCODE_PROJECT_ROOT/.agents/skills/``, else
    CWD-relative ``.agents/skills/``).
    No shell ``opencode`` binary is required; none is inspected.
    No private app data is read — only env + project-relative paths.
    This probe reports EXECUTOR presence for routing; it grants no
    write authority (the router never grants any)."""
    client = os.environ.get("OPENCODE_CLIENT", "")
    if client != "desktop":
        if client:
            return UNKNOWN, (f"OPENCODE_CLIENT={client!r} is not the "
                             "known desktop marker — state unknown")
        return UNAVAILABLE, "no OPENCODE_CLIENT evidence in environment"
    project = os.environ.get("OPENCODE_PROJECT_ROOT", "")
    marker = (Path(project) / ".agents/skills" if project
              else Path(".agents/skills"))
    if marker.is_dir():
        skills = sum(1 for _ in marker.iterdir())
        return AVAILABLE, (f"OPENCODE_CLIENT=desktop + project marker "
                           f"{marker}/ ({skills} entries)")
    return UNKNOWN, ("OPENCODE_CLIENT=desktop but no project-local "
                     ".agents/skills/ found "
                     f"({marker} missing) — executor context "
                     "unconfirmed")


def probe_serena() -> tuple[str, str]:
    process = subprocess.run(["pgrep", "-fl", "serena start-mcp-server"],
                             capture_output=True, text=True)
    pids = [line.split()[0] for line in process.stdout.splitlines()
            if "start-mcp-server" in line]
    if pids:
        return AVAILABLE, f"serena MCP server running (pid {','.join(pids[:2])})"
    return UNAVAILABLE, "no serena start-mcp-server process"


def probe_graph_mcp() -> tuple[str, str]:
    import sqlite3

    if not GRAPH_STORE.is_file():
        return UNAVAILABLE, f"no graph store at {GRAPH_STORE}"
    try:
        connection = sqlite3.connect(f"file:{GRAPH_STORE}?mode=ro", uri=True)
        nodes = connection.execute("SELECT count(*) FROM nodes").fetchone()[0]
        connection.close()
    except sqlite3.Error as error:
        return UNAVAILABLE, f"graph store unreadable: {error}"
    return (AVAILABLE if nodes else "DEGRADED"), f"graph store {GRAPH_STORE}: {nodes} nodes"


def probe_graphify() -> tuple[str, str]:
    binary = shutil.which("graphify") or str(Path.home() / ".local/bin/graphify")
    if Path(binary).is_file():
        return AVAILABLE, f"graphify CLI at {binary}"
    return UNAVAILABLE, "graphify CLI not found"


def probe_obsidian() -> tuple[str, str]:
    if (VAULT / "TIM").is_dir():
        notes = sum(1 for _ in (VAULT / "TIM").rglob("*.md"))
        return AVAILABLE, f"vault {VAULT}: {notes} notes"
    return UNAVAILABLE, f"vault missing: {VAULT}"


def probe_ollama() -> tuple[str, str]:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=1.0):
            pass
    except OSError:
        return UNAVAILABLE, "127.0.0.1:11434 not reachable"
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",
                                    timeout=3) as response:
            models = [m.get("name", "") for m in
                      json.loads(response.read()).get("models", [])]
    except (OSError, ValueError) as error:
        return "DEGRADED", f"port open but tags unreadable: {error}"
    return AVAILABLE, f"ollama up; models: {', '.join(models[:5])}"


def probe_qwen() -> tuple[str, str]:
    """Qwen means qwen2.5:7b (the proven review model). Another model is
    NEVER silently substituted and labeled Qwen (STEP 11)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags",
                                    timeout=3) as response:
            models = [m.get("name", "") for m in
                      json.loads(response.read()).get("models", [])]
    except (OSError, ValueError) as error:
        return UNAVAILABLE, f"ollama tags unreadable: {error}"
    if any(model.startswith("qwen2.5:7b") for model in models):
        return AVAILABLE, "qwen2.5:7b installed"
    return UNAVAILABLE, ("qwen2.5:7b NOT installed; present: "
                         + ", ".join(models[:5]))


def probe_native_search() -> tuple[str, str]:
    for tool in ("rg", "grep"):
        if shutil.which(tool):
            return AVAILABLE, f"{tool} on PATH"
    return UNAVAILABLE, "no rg/grep"


def probe_pytest() -> tuple[str, str]:
    _venv = os.environ.get("TIM_PLATFORM_VENV", "")
    venv = (Path(_venv) if _venv
            else Path.home() / "Documents/TIM/tim/.venv/bin/python")
    if venv.exists():
        return AVAILABLE, f"pytest via {venv}"
    return UNAVAILABLE, "platform venv missing"


class ToolHealthRegistry:
    TOOLS: dict[str, Callable[[], tuple[str, str]]] = {
        "Serena": probe_serena,
        "TIMGraphMCP": probe_graph_mcp,
        "Graphify": probe_graphify,
        "Obsidian": probe_obsidian,
        "Qwen": probe_qwen,
        "Ollama": probe_ollama,
        "OpenCode": probe_opencode,
        "NativeSearch": probe_native_search,
        "pytest": probe_pytest,
    }

    def __init__(self, probes: dict[str, Callable] | None = None) -> None:
        self._probes = dict(probes or self.TOOLS)
        self._statuses: dict[str, dict] = {}

    def refresh(self) -> dict[str, dict]:
        self._statuses = {}
        for name, probe in sorted(self._probes.items()):
            try:
                state, evidence = probe()
            except Exception as error:  # probes fail closed
                state, evidence = UNKNOWN, f"probe error: {type(error).__name__}"
            self._statuses[name] = {"state": state, "evidence": evidence,
                                    "observed_at": _now()}
        return dict(self._statuses)

    @property
    def availability(self) -> dict[str, str]:
        return {name: entry["state"] for name, entry in self._statuses.items()}

    def status(self) -> dict[str, dict]:
        return dict(self._statuses)
