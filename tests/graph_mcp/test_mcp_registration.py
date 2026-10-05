"""Project-scoped MCP registration (.mcp.json): the tim-graph entry must stay
portable (no absolute paths, no secrets) and must start the real server
exactly as a client would. The store is redirected to a temp path, so the
repository's own .runtime index is never touched."""
from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
from pathlib import Path

import pytest

from src.graph_mcp import SERVER_NAME
from src.graph_mcp.mcp_server import TOOLS

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / ".mcp.json"
_EXPANSION = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: str, env: dict[str, str]) -> str:
    """Same ${VAR} / ${VAR:-default} expansion Claude Code applies."""
    return _EXPANSION.sub(lambda m: env.get(m.group(1)) or (m.group(2) or ""), value)


def _entry() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))["mcpServers"]["tim-graph"]


def test_registration_is_portable_and_secret_free():
    raw = CONFIG.read_text(encoding="utf-8")
    entry = _entry()
    assert entry["type"] == "stdio"
    assert entry["args"] == ["-m", "src.graph_mcp.mcp_server"]
    assert "/Users/" not in raw and "/home/" not in raw and "/opt/" not in raw
    assert not re.search(r"(?i)(token|secret|password|api_key|ghp_|sk-)", raw)


def test_registered_command_starts_server(tmp_path: Path):
    entry = _entry()
    env = {**os.environ, "TIM_GRAPH_MCP_PY": sys.executable,
           "TIM_GRAPH_MCP_DB": str(tmp_path / "graph.sqlite"),
           "TIM_GRAPH_MCP_KI_TOOLS": str(tmp_path / "no-ki-tools")}
    env.pop("TIM_GRAPH_MCP_ROOT", None)
    command = [_expand(entry["command"], env)] + [_expand(a, env) for a in entry["args"]]
    env.update({k: _expand(v, env) for k, v in entry.get("env", {}).items()})
    proc = subprocess.Popen(command, cwd=ROOT, env=env, text=True, bufsize=1,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)

    def call(payload: dict) -> dict:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 20)
        if not ready:
            pytest.fail(f"no response to {payload['method']}")
        return json.loads(proc.stdout.readline())

    try:
        init = call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init["result"]["serverInfo"]["name"] == SERVER_NAME
        proc.stdin.write(json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/initialized"}) + "\n")
        listed = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert len(listed["result"]["tools"]) == len(TOOLS) == 18
        health = call({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "graph_health", "arguments": {}}})
        payload = json.loads(health["result"]["content"][0]["text"])
        assert payload["read_only_tim"] is True
        assert payload["store"] == str(tmp_path / "graph.sqlite")
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
