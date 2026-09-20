"""Scoped Serena MCP client (stdio, line-delimited JSON-RPC 2.0).

Spawns a dedicated `serena start-mcp-server --project <root>` instance
per project scope, so read navigation runs against the canonical read
source and edits run against the isolated worktree only. Serena's own
IDs never leave this module's boundary as canonical TIM IDs — see
bridge.py for the canonical mapping.

Frame convention matches the repo's existing MCP stack (initialize ->
notifications/initialized -> tools/list -> tools/call)."""
from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
def serena_binary() -> str:
    """Resolve the Serena binary portably: SERENA_BIN wins, then PATH.

    Fails closed with an actionable message instead of guessing a
    machine-specific cache path."""
    explicit = os.environ.get("SERENA_BIN", "")
    if explicit:
        return explicit
    found = shutil.which("serena")
    if found:
        return found
    raise SerenaUnavailable(
        "no serena binary found (set SERENA_BIN or put serena on PATH)")
CONTEXT = "ide-assistant"


class SerenaError(RuntimeError):
    pass


class SerenaUnavailable(SerenaError):
    pass


class SerenaClient:
    """One instance = one spawned server = one project scope."""

    def __init__(self, project_root: str | Path, timeout: float = 180.0) -> None:
        self.project_root = str(Path(project_root).resolve())
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._tools: list[str] = []
        self._initialized = False

    # -- lifecycle ----------------------------------------------------

    def __enter__(self) -> "SerenaClient":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    def start(self) -> None:
        command = [serena_binary(), "start-mcp-server",
                   "--context", CONTEXT, "--project", self.project_root]
        try:
            self._process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
                cwd=self.project_root)
        except OSError as error:
            raise SerenaUnavailable(f"cannot spawn serena: {error}") from error

    def stop(self) -> None:
        if self._process is not None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                self._process.wait(timeout=10)
            except (subprocess.TimeoutExpired, OSError):
                self._process.kill()
                self._process.wait()
            self._process = None

    # -- protocol ------------------------------------------------------

    def _send(self, payload: dict[str, Any], expect_response: bool = True) -> dict | None:
        if self._process is None or not self._process.stdin or not self._process.stdout:
            raise SerenaUnavailable("serena process not running")
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()
        if not expect_response:
            return None
        ready, _, _ = select.select([self._process.stdout], [], [], self.timeout)
        if not ready:
            raise SerenaError("serena response timed out")
        line = self._process.stdout.readline()
        if not line:
            raise SerenaError("serena server closed the stream")
        message = json.loads(line)
        if not isinstance(message, dict):
            raise SerenaError("serena returned a non-object message")
        return message

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._send({"jsonrpc": "2.0", "id": 1, "method": method,
                               "params": params})
        if response is None or "error" in response:
            message = (response or {}).get("error", {}).get("message", "no response")
            raise SerenaError(f"{method} failed: {message}")
        return response.get("result", {})

    def initialize(self) -> dict[str, Any]:
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "tim-agent-infrastructure",
                           "version": "1.0.0"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"},
                   expect_response=False)
        self._initialized = True
        return result

    def tool_names(self) -> list[str]:
        if not self._tools:
            if not self._initialized:
                self.initialize()
            tools = self._request("tools/list", {}).get("tools", [])
            self._tools = [tool.get("name", "") for tool in tools]
        return list(self._tools)

    def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._initialized:
            self.initialize()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            texts = [part.get("text", "") for part in result.get("content", [])]
            raise SerenaError(f"{name}: {' '.join(texts)[:400]}")
        return result.get("content", [])

    # -- semantic surface (exact tool names of serena's ide-assistant) ---

    def find_symbol(self, name_path_pattern: str, relative_path: str = "",
                    substring_matching: bool = False, include_body: bool = False) -> list[dict]:
        """Returns serena symbol dicts: name_path, kind, relative_path,
        body_location{start_line,end_line}."""
        return _json_content(self.call("find_symbol", {
            "name_path_pattern": name_path_pattern,
            "relative_path": relative_path,
            "substring_matching": substring_matching,
            "include_body": include_body,
            "include_kind": True}))

    def find_referencing_symbols(self, name_path: str, relative_path: str) -> dict[str, dict[str, list[dict]]]:
        """Returns {relative_path: {kind: [{name_path, body_location,
        content_around_reference}]}} — flatten with flatten_references()."""
        return _json_content(self.call("find_referencing_symbols", {
            "name_path": name_path, "relative_path": relative_path,
            "include_body": False}))

    def get_symbols_overview(self, relative_path: str) -> dict[str, Any]:
        return _json_content(self.call("get_symbols_overview",
                                       {"relative_path": relative_path}))


def flatten_references(references: dict) -> list[dict[str, Any]]:
    """{file: {kind: [entries]}} -> [{file, kind, name_path, start_line,
    snippet}] (deterministic order)."""
    flat: list[dict[str, Any]] = []
    for file, by_kind in sorted(references.items() if isinstance(references, dict) else []):
        for kind, entries in sorted(by_kind.items()):
            for entry in entries:
                location = entry.get("body_location") or {}
                flat.append({
                    "file": file, "kind": kind,
                    "name_path": entry.get("name_path", ""),
                    "start_line": location.get("start_line"),
                    "snippet": (entry.get("content_around_reference", "") or "")[:160],
                })
    return flat


def _json_content(content: list[dict]) -> Any:
    """Serena returns tool payloads as JSON-in-text content parts."""
    for part in content:
        if part.get("type") == "text":
            try:
                return json.loads(part["text"])
            except (ValueError, TypeError):
                return part.get("text")
    return content
