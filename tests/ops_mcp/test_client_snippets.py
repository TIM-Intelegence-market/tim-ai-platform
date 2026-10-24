"""Client hookup outside the repo (#152 M2): docs/mcp_clients.md holds the
Codex (TOML) and Claude Desktop (JSON) snippets for tim-graph and tim-ops.
They must match the project registration in .mcp.json, stay secret-free and
start the real server from a foreign working directory once the
`<tim worktree>` placeholder is filled in, which is how both clients run it."""
from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from src.graph_mcp import SERVER_NAME as GRAPH_SERVER_NAME
from src.ops_mcp import SERVER_NAME as OPS_SERVER_NAME

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "mcp_clients.md"
WORKTREE = "<tim worktree>"
SERVERS = {"tim-graph": GRAPH_SERVER_NAME, "tim-ops": OPS_SERVER_NAME}
ROOT_VARS = {"tim-graph": "TIM_GRAPH_MCP_ROOT", "tim-ops": "TIM_OPS_MCP_ROOT"}
# Client-only additions: clients start outside the checkout, the vault is optional.
EXTRA_ENV = {"PYTHONPATH", "TIM_OBSIDIAN_VAULT"}


def _blocks(language: str) -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    return re.findall(rf"```{language}\n(.*?)```", text, flags=re.S)


def _codex() -> dict[str, dict]:
    blocks = _blocks("toml")
    assert len(blocks) == 1, "expected exactly one Codex TOML block"
    return tomllib.loads(blocks[0])["mcp_servers"]


def _desktop() -> dict[str, dict]:
    blocks = _blocks("json")
    assert len(blocks) == 1, "expected exactly one Claude Desktop JSON block"
    return json.loads(blocks[0])["mcpServers"]


def _registered() -> dict[str, dict]:
    return json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]


CLIENTS = {"codex": _codex, "claude_desktop": _desktop}


def test_doc_is_secret_free_and_placeholder_only():
    raw = DOC.read_text(encoding="utf-8")
    assert "/Users/" not in raw and "/home/" not in raw and "C:\\" not in raw
    assert not re.search(r"(?i)(ghp_|\bsk-[a-z0-9]|password\s*=|api_key\s*=|postgres(ql)?://)", raw)


@pytest.mark.parametrize("client", sorted(CLIENTS))
def test_snippet_matches_project_registration(client: str):
    snippet = CLIENTS[client]()
    registered = _registered()
    assert set(snippet) == set(registered) == set(SERVERS)
    for name, entry in snippet.items():
        assert entry["command"] == f"{WORKTREE}/.venv/bin/python"
        assert entry["args"] == registered[name]["args"]
        env = entry["env"]
        assert env[ROOT_VARS[name]] == WORKTREE
        assert env["PYTHONPATH"] == WORKTREE
        assert set(env) <= set(registered[name].get("env", {})) | EXTRA_ENV


def _start(entry: dict, worktree: Path, extra_env: dict[str, str], cwd: Path):
    fill = lambda value: value.replace(WORKTREE, str(worktree))  # noqa: E731
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("TIM_GRAPH_MCP", "TIM_OPS_")) and k != "PYTHONPATH"}
    env.update({k: fill(v) for k, v in entry["env"].items() if v})
    env.update(extra_env)
    # The test venv is not <tim worktree>/.venv; same interpreter, same args.
    command = [sys.executable] + [fill(a) for a in entry["args"]]
    return subprocess.Popen(command, cwd=cwd, env=env, text=True, bufsize=1,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)


@pytest.mark.parametrize("client", sorted(CLIENTS))
@pytest.mark.parametrize("server", sorted(SERVERS))
def test_snippet_starts_server_from_foreign_cwd(client: str, server: str, tmp_path: Path):
    entry = CLIENTS[client]()[server]
    extra = {"TIM_GRAPH_MCP_DB": str(tmp_path / "graph.sqlite"),
             "TIM_GRAPH_MCP_KI_TOOLS": str(tmp_path / "no-ki-tools"),
             "TIM_OBSIDIAN_VAULT": ""}
    proc = _start(entry, ROOT, extra, cwd=tmp_path)

    def call(payload: dict) -> dict:
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 20)
        if not ready:
            pytest.fail(f"no response to {payload['method']}")
        return json.loads(proc.stdout.readline())

    try:
        init = call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert init["result"]["serverInfo"]["name"] == SERVERS[server]
        listed = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert listed["result"]["tools"]
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
