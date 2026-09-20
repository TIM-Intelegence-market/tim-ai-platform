from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import select
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .config import PROJECT_ROOT, load_config
from .config_paths import (
    REPO_ROOT_PLACEHOLDER,
    RepositoryPathError,
    repository_path,
)


def _resolve_portable_paths(value: dict[str, Any]) -> dict[str, Any]:
    """Resolve repository-placeholder paths inside a copied config dict.

    Only the documented path-bearing fields are rewritten; everything else is
    left byte-identical. Path resolution never happens inside config files.
    """
    resolved = dict(value)
    for field in ("working_directory", "graph_path"):
        spec = resolved.get(field)
        if isinstance(spec, str):
            resolved[field] = str(repository_path(spec))
    command = resolved.get("command")
    if isinstance(command, str):
        resolved["command"] = _resolve_command(command)
    arguments = resolved.get("arguments")
    if isinstance(arguments, list):
        resolved["arguments"] = [
            str(repository_path(item)) if isinstance(item, str) and REPO_ROOT_PLACEHOLDER in item else item
            for item in arguments
        ]
    return resolved


def _resolve_command(command: str) -> str:
    """Resolve a configured command portably.

    Priority:
      1. explicit environment variable ``TIM_GRAPHIFY_MCP_BIN``,
      2. repository placeholder (absolute, inside the repository),
      3. ``shutil.which`` lookup on PATH for a bare executable name,
      4. verbatim absolute path (security-checked when it uses a placeholder).

    The gateway is disabled by default, so an unavailable executable only
    surfaces as a client-side ``GraphifyClientError`` at connect time; config
    loading never fails merely because a host tool is absent.
    """
    env_value = os.environ.get("TIM_GRAPHIFY_MCP_BIN", "").strip()
    if env_value:
        resolved = Path(env_value).expanduser()
        if not resolved.is_absolute():
            raise GraphifyConfigurationError("TIM_GRAPHIFY_MCP_BIN must be absolute")
        return str(resolved.resolve())
    if REPO_ROOT_PLACEHOLDER in command:
        return str(repository_path(command))
    stripped = command.strip()
    if stripped and not Path(stripped).is_absolute():
        found = shutil.which(stripped)
        if found:
            return found
        return str(Path(PROJECT_ROOT / ".venv" / "bin" / stripped).resolve())
    return command


LOGGER = logging.getLogger("tim_manager.graphify_mcp")
TRUST_CLASS = "untrusted_retrieval"
SERVER_NAME = "tim-graphify-readonly"
GRAPHIFY_LOCAL_TOOLS = frozenset(
    {
        "query_graph",
        "get_node",
        "get_neighbors",
        "get_community",
        "god_nodes",
        "graph_stats",
        "shortest_path",
    }
)
DENIED_GRAPHIFY_TOOLS = frozenset({"list_prs", "get_pr_impact", "triage_prs"})
SOURCE_REF = re.compile(
    r"(?:src|source_file|at)=([A-Za-z0-9_./-]+)(?::L\d+)?"
    r"|\[([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)\]"
)
SECRET_PATTERNS = (
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.S),
)


class GraphifyClientError(RuntimeError):
    """Safe, user-facing client failure."""


class GraphifyConfigurationError(GraphifyClientError):
    pass


class GraphifyPolicyError(GraphifyClientError):
    pass


class GraphifyProtocolError(GraphifyClientError):
    pass


class GraphifyTimeoutError(GraphifyClientError):
    pass


class GraphifyIntegrityError(GraphifyClientError):
    pass


class MCPClientPort(Protocol):
    def connect(self) -> None: ...
    def initialize(self) -> dict[str, Any]: ...
    def list_tools(self) -> list[dict[str, Any]]: ...
    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...
    def close(self) -> None: ...
    def health_check(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GraphifyMCPConfig:
    enabled: bool
    transport: str
    server_name: str
    command: str
    arguments: tuple[str, ...]
    working_directory: str
    graph_path: str
    expected_graph_hash: str
    read_only: bool
    allowed_tools: tuple[str, ...]
    startup_timeout_seconds: float
    request_timeout_seconds: float
    shutdown_timeout_seconds: float
    max_result_bytes: int
    max_results: int
    trust_class: str
    require_provenance: bool
    allow_shell_interpolation: bool
    allow_unknown_tools: bool
    allow_writes: bool

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GraphifyMCPConfig":
        if not isinstance(value, dict):
            raise GraphifyConfigurationError("configuration must be an object")
        required = {
            "enabled",
            "transport",
            "server_name",
            "command",
            "arguments",
            "working_directory",
            "graph_path",
            "expected_graph_hash",
            "read_only",
            "allowed_tools",
            "startup_timeout_seconds",
            "request_timeout_seconds",
            "shutdown_timeout_seconds",
            "max_result_bytes",
            "max_results",
            "trust_class",
            "require_provenance",
            "allow_shell_interpolation",
            "allow_unknown_tools",
            "allow_writes",
        }
        unknown = set(value) - required - {"schema_version"}
        missing = required - set(value)
        if missing or unknown:
            raise GraphifyConfigurationError(
                f"invalid configuration keys: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        if not isinstance(value["arguments"], list) or not all(
            isinstance(item, str) for item in value["arguments"]
        ):
            raise GraphifyConfigurationError("arguments must be a string array")
        if not isinstance(value["allowed_tools"], list) or not all(
            isinstance(item, str) for item in value["allowed_tools"]
        ):
            raise GraphifyConfigurationError("allowed_tools must be a string array")
        numeric_fields = (
            "startup_timeout_seconds",
            "request_timeout_seconds",
            "shutdown_timeout_seconds",
            "max_result_bytes",
            "max_results",
        )
        if any(
            isinstance(value[name], bool) or not isinstance(value[name], (int, float))
            for name in numeric_fields
        ):
            raise GraphifyConfigurationError("timeouts and bounds must be numeric")
        value = _resolve_portable_paths(value)
        config = cls(
            enabled=value["enabled"],
            transport=value["transport"],
            server_name=value["server_name"],
            command=value["command"],
            arguments=tuple(value["arguments"]),
            working_directory=value["working_directory"],
            graph_path=value["graph_path"],
            expected_graph_hash=value["expected_graph_hash"],
            read_only=value["read_only"],
            allowed_tools=tuple(value["allowed_tools"]),
            startup_timeout_seconds=float(value["startup_timeout_seconds"]),
            request_timeout_seconds=float(value["request_timeout_seconds"]),
            shutdown_timeout_seconds=float(value["shutdown_timeout_seconds"]),
            max_result_bytes=value["max_result_bytes"],
            max_results=value["max_results"],
            trust_class=value["trust_class"],
            require_provenance=value["require_provenance"],
            allow_shell_interpolation=value["allow_shell_interpolation"],
            allow_unknown_tools=value["allow_unknown_tools"],
            allow_writes=value["allow_writes"],
        )
        config.validate()
        return config

    @classmethod
    def load(cls, name: str = "graphify_mcp.yaml") -> "GraphifyMCPConfig":
        return cls.from_dict(load_config(name))

    def validate(self) -> None:
        boolean_fields = (
            self.enabled,
            self.read_only,
            self.require_provenance,
            self.allow_shell_interpolation,
            self.allow_unknown_tools,
            self.allow_writes,
        )
        if any(type(item) is not bool for item in boolean_fields):
            raise GraphifyConfigurationError("security switches must be booleans")
        if self.transport != "stdio":
            raise GraphifyConfigurationError("only local stdio transport is allowed")
        if self.server_name != SERVER_NAME or self.trust_class != TRUST_CLASS:
            raise GraphifyConfigurationError("server identity or trust class mismatch")
        if not Path(self.command).is_absolute() or not Path(self.working_directory).is_absolute():
            raise GraphifyConfigurationError("command and working directory must be absolute")
        graph = Path(self.graph_path)
        if not graph.is_absolute() or graph.name != "graph.json":
            raise GraphifyConfigurationError("graph_path must be an absolute graph.json path")
        if Path(self.working_directory).resolve() != PROJECT_ROOT.resolve():
            raise GraphifyConfigurationError("working directory must be the TIM repository")
        if graph.resolve() != (PROJECT_ROOT / "graphify-out" / "graph.json").resolve():
            raise GraphifyConfigurationError("only the authoritative TIM codegraph is allowed")
        if not re.fullmatch(r"[0-9a-f]{64}", self.expected_graph_hash):
            raise GraphifyConfigurationError("expected_graph_hash must be SHA-256")
        if not self.read_only or self.allow_writes or self.allow_unknown_tools:
            raise GraphifyConfigurationError("read-only fail-closed switches are required")
        if self.allow_shell_interpolation:
            raise GraphifyConfigurationError("shell interpolation is forbidden")
        if set(self.allowed_tools) - GRAPHIFY_LOCAL_TOOLS:
            raise GraphifyConfigurationError("allowlist contains a non-local or unknown tool")
        if set(self.allowed_tools) & DENIED_GRAPHIFY_TOOLS:
            raise GraphifyConfigurationError("network PR tools are forbidden")
        if len(set(self.allowed_tools)) != len(self.allowed_tools):
            raise GraphifyConfigurationError("allowed_tools contains duplicates")
        if any(type(item) is not str for item in self.arguments):
            raise GraphifyConfigurationError("arguments must be strings")
        if any(value <= 0 for value in (
            self.startup_timeout_seconds,
            self.request_timeout_seconds,
            self.shutdown_timeout_seconds,
            self.max_result_bytes,
            self.max_results,
        )):
            raise GraphifyConfigurationError("timeouts and result bounds must be positive")


@dataclass(frozen=True)
class GraphifyResult:
    query_id: str
    server_name: str
    tool_name: str
    graph_hash: str
    generated_at_utc: str
    trust_class: str
    results: tuple[dict[str, Any], ...]
    source_refs: tuple[str, ...]
    warnings: tuple[str, ...]
    truncated: bool
    raw_response_hash: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["results"] = list(self.results)
        value["source_refs"] = list(self.source_refs)
        value["warnings"] = list(self.warnings)
        return value

    @classmethod
    def validate(cls, value: dict[str, Any]) -> "GraphifyResult":
        required = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != required:
            raise GraphifyProtocolError("result provenance contract is incomplete")
        if value["server_name"] != SERVER_NAME or value["trust_class"] != TRUST_CLASS:
            raise GraphifyProtocolError("result trust identity mismatch")
        if not re.fullmatch(r"[0-9a-f]{64}", value["graph_hash"]):
            raise GraphifyProtocolError("result graph hash is invalid")
        if not value["query_id"] or not value["tool_name"] or not value["generated_at_utc"]:
            raise GraphifyProtocolError("result provenance fields are empty")
        if not re.fullmatch(r"[0-9a-f]{64}", value["raw_response_hash"]):
            raise GraphifyProtocolError("raw response hash is invalid")
        if (
            not isinstance(value["results"], list)
            or not all(isinstance(item, dict) for item in value["results"])
            or not isinstance(value["source_refs"], list)
            or not all(isinstance(item, str) for item in value["source_refs"])
            or not isinstance(value["warnings"], list)
            or not all(isinstance(item, str) for item in value["warnings"])
            or type(value["truncated"]) is not bool
        ):
            raise GraphifyProtocolError("result collections or truncation state are invalid")
        return cls(
            query_id=value["query_id"],
            server_name=value["server_name"],
            tool_name=value["tool_name"],
            graph_hash=value["graph_hash"],
            generated_at_utc=value["generated_at_utc"],
            trust_class=value["trust_class"],
            results=tuple(value["results"]),
            source_refs=tuple(value["source_refs"]),
            warnings=tuple(value["warnings"]),
            truncated=value["truncated"],
            raw_response_hash=value["raw_response_hash"],
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def extract_source_refs(text: str) -> list[str]:
    references: set[str] = set()
    for first, second in SOURCE_REF.findall(text):
        reference = first or second
        if reference:
            references.add(reference)
    return sorted(references)


def normalize_graphify_text(text: str) -> str:
    """Normalize order-only server variance without changing retrieved lines."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    if len(lines) <= 1:
        return "\n".join(lines)
    heading, body = lines[0], [line for line in lines[1:] if line]
    return "\n".join([heading, *sorted(body)])


def _security_event(reason: str, tool_name: str) -> None:
    LOGGER.warning(
        json.dumps(
            {
                "event": "graphify_mcp_request_denied",
                "reason": reason,
                "tool_name": redact_secrets(tool_name),
                "trust_class": TRUST_CLASS,
            },
            sort_keys=True,
        )
    )


class LocalStdioMCPClient:
    """Minimal JSON-RPC MCP stdio client with no project dependency."""

    def __init__(self, config: GraphifyMCPConfig):
        self.config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._request_id = 0
        self._buffer = b""
        self._initialized: dict[str, Any] | None = None

    def connect(self) -> None:
        if self._process and self._process.poll() is None:
            return
        if not Path(self.config.command).is_file():
            raise GraphifyClientError("Graphify MCP executable is unavailable")
        if not Path(self.config.graph_path).is_file():
            raise GraphifyClientError("Graphify codegraph is unavailable")
        environment = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "GRAPHIFY_QUERY_LOG_DISABLE": "1",
        }
        try:
            self._process = subprocess.Popen(
                [self.config.command, *self.config.arguments],
                cwd=self.config.working_directory,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                start_new_session=True,
            )
        except OSError as exc:
            raise GraphifyClientError(f"Graphify MCP server start failed: {exc}") from exc
        self._buffer = b""

    def _write(self, message: dict[str, Any]) -> None:
        if not self._process or self._process.poll() is not None or not self._process.stdin:
            raise GraphifyProtocolError("Graphify MCP server is not running")
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            self._process.stdin.write(payload)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise GraphifyProtocolError("Graphify MCP server terminated") from exc

    def _read_message(self, timeout: float) -> dict[str, Any]:
        if not self._process or not self._process.stdout:
            raise GraphifyProtocolError("Graphify MCP server is not connected")
        deadline = time.monotonic() + timeout
        descriptor = self._process.stdout.fileno()
        while b"\n" not in self._buffer:
            if self._process.poll() is not None:
                raise GraphifyProtocolError("Graphify MCP server terminated")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GraphifyTimeoutError("Graphify MCP response timed out")
            readable, _, _ = select.select([descriptor], [], [], remaining)
            if not readable:
                raise GraphifyTimeoutError("Graphify MCP response timed out")
            chunk = os.read(descriptor, min(65536, self.config.max_result_bytes + 1))
            if not chunk:
                raise GraphifyProtocolError("Graphify MCP server returned an incomplete response")
            self._buffer += chunk
            if len(self._buffer) > self.config.max_result_bytes:
                raise GraphifyProtocolError("Graphify MCP response exceeds max_result_bytes")
        line, self._buffer = self._buffer.split(b"\n", 1)
        try:
            message = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GraphifyProtocolError("Graphify MCP response is malformed JSON") from exc
        if not isinstance(message, dict):
            raise GraphifyProtocolError("Graphify MCP response must be an object")
        return message

    def _request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        self._write(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GraphifyTimeoutError("Graphify MCP response timed out")
            response = self._read_message(remaining)
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response["error"]
                raise GraphifyProtocolError(
                    redact_secrets(f"Graphify MCP error {error.get('code')}: {error.get('message')}")
                )
            result = response.get("result")
            if not isinstance(result, dict):
                raise GraphifyProtocolError("Graphify MCP result is invalid")
            return result

    def initialize(self) -> dict[str, Any]:
        self.connect()
        result = self._request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "tim-manager", "version": "1.0.0"},
            },
            self.config.startup_timeout_seconds,
        )
        if not result.get("protocolVersion") or not result.get("serverInfo"):
            raise GraphifyProtocolError("Graphify MCP initialization is incomplete")
        self._write({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = result
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        if not self._initialized:
            self.initialize()
        result = self._request("tools/list", {}, self.config.request_timeout_seconds)
        tools = result.get("tools")
        if not isinstance(tools, list) or any(not isinstance(item, dict) for item in tools):
            raise GraphifyProtocolError("Graphify MCP tool inventory is invalid")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self.config.allowed_tools:
            _security_event("tool_not_allowlisted", name)
            raise GraphifyPolicyError(f"Graphify tool is not allowed: {redact_secrets(name)}")
        if "project_path" in arguments:
            _security_event("caller_controlled_graph_path", name)
            raise GraphifyPolicyError("caller-controlled project_path is forbidden")
        if not self._initialized:
            self.initialize()
        return self._request(
            "tools/call",
            {"name": name, "arguments": arguments},
            self.config.request_timeout_seconds,
        )

    def health_check(self) -> dict[str, Any]:
        initialized = self.initialize()
        tools = self.list_tools()
        return {
            "status": "reachable",
            "protocol_version": initialized["protocolVersion"],
            "server": initialized["serverInfo"],
            "tool_count": len(tools),
        }

    def close(self) -> None:
        process, self._process = self._process, None
        self._initialized = None
        self._buffer = b""
        if not process:
            return
        if process.stdin:
            process.stdin.close()
        try:
            process.wait(timeout=self.config.shutdown_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=self.config.shutdown_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=self.config.shutdown_timeout_seconds)

    def __enter__(self) -> "LocalStdioMCPClient":
        self.connect()
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()


class GraphifyReadOnlyClient:
    _ARGUMENTS = {
        "query_graph": {"question", "mode", "depth", "token_budget", "context_filter"},
        "get_node": {"label"},
        "get_neighbors": {"label", "relation_filter", "token_budget"},
        "get_community": {"community_id", "token_budget"},
        "god_nodes": {"top_n"},
        "graph_stats": set(),
        "shortest_path": {"source", "target", "max_hops"},
    }

    def __init__(
        self,
        config: GraphifyMCPConfig | None = None,
        transport: MCPClientPort | None = None,
        *,
        enabled_override: bool = False,
    ):
        self.config = config or GraphifyMCPConfig.load()
        if not self.config.enabled and not enabled_override:
            raise GraphifyConfigurationError(
                "Graphify MCP client is disabled; use an explicit per-invocation enable"
            )
        self.transport = transport or LocalStdioMCPClient(self.config)

    def _current_graph_hash(self) -> str:
        observed = sha256_file(Path(self.config.graph_path))
        if observed != self.config.expected_graph_hash:
            raise GraphifyIntegrityError("Graphify codegraph hash differs from configured baseline")
        return observed

    def _validate_arguments(self, tool_name: str, arguments: dict[str, Any]) -> None:
        allowed = self._ARGUMENTS[tool_name]
        unknown = set(arguments) - allowed
        if unknown:
            _security_event("unknown_or_forbidden_argument", tool_name)
            raise GraphifyPolicyError(f"forbidden tool arguments: {sorted(unknown)}")
        for key, value in arguments.items():
            if isinstance(value, str) and (len(value) > 4096 or "\x00" in value):
                raise GraphifyPolicyError(f"invalid string argument: {key}")
        if "token_budget" in arguments and not 1 <= arguments["token_budget"] <= 4000:
            raise GraphifyPolicyError("token_budget outside client limit")
        if "depth" in arguments and not 1 <= arguments["depth"] <= 4:
            raise GraphifyPolicyError("depth outside client limit")
        if "max_hops" in arguments and not 1 <= arguments["max_hops"] <= 8:
            raise GraphifyPolicyError("max_hops outside client limit")
        if "top_n" in arguments and not 1 <= arguments["top_n"] <= self.config.max_results:
            raise GraphifyPolicyError("top_n outside client limit")

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> GraphifyResult:
        if tool_name not in self.config.allowed_tools:
            _security_event("tool_not_allowlisted", tool_name)
            raise GraphifyPolicyError(f"Graphify tool is not allowed: {tool_name}")
        self._validate_arguments(tool_name, arguments)
        graph_hash = self._current_graph_hash()
        raw_result = self.transport.call_tool(tool_name, arguments)
        if raw_result.get("isError") is True:
            raise GraphifyProtocolError("Graphify tool reported an error")
        content = raw_result.get("content")
        if not isinstance(content, list):
            raise GraphifyProtocolError("Graphify tool result has no content list")
        texts: list[str] = []
        for item in content[: self.config.max_results]:
            if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
                raise GraphifyProtocolError("Graphify tool returned unsupported content")
            texts.append(normalize_graphify_text(redact_secrets(item["text"])))
        if not texts or not any(text.strip() for text in texts):
            raise GraphifyProtocolError("Graphify tool returned an empty result")
        raw = json.dumps(raw_result, ensure_ascii=False, sort_keys=True)
        if len(raw.encode("utf-8")) > self.config.max_result_bytes:
            raise GraphifyProtocolError("Graphify tool result exceeds max_result_bytes")
        source_refs = sorted(
            {reference for text in texts for reference in extract_source_refs(text)}
        )
        warnings: list[str] = []
        if not source_refs:
            warnings.append("no_repository_source_refs")
        result = GraphifyResult(
            query_id=str(uuid.uuid4()),
            server_name=SERVER_NAME,
            tool_name=tool_name,
            graph_hash=graph_hash,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            trust_class=TRUST_CLASS,
            results=tuple({"text": text} for text in texts),
            source_refs=tuple(source_refs),
            warnings=tuple(warnings),
            truncated=any("TRUNCATED" in text for text in texts),
            raw_response_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        )
        return GraphifyResult.validate(result.to_dict())

    def connect(self) -> dict[str, Any]:
        initialized = self.transport.initialize()
        self.list_tools()
        return initialized

    def list_tools(self) -> list[dict[str, Any]]:
        discovered = self.transport.list_tools()
        names = {item.get("name") for item in discovered}
        missing = set(self.config.allowed_tools) - names
        if missing:
            raise GraphifyIntegrityError(f"configured Graphify tools are missing: {sorted(missing)}")
        return [
            item
            for item in discovered
            if item.get("name") in self.config.allowed_tools
        ]

    def search_codegraph(self, query: str) -> GraphifyResult:
        return self._call(
            "query_graph",
            {"question": query, "mode": "bfs", "depth": 2, "token_budget": 2000},
        )

    def inspect_node(self, node_id: str) -> GraphifyResult:
        return self._call("get_node", {"label": node_id})

    def inspect_relationships(self, node_id: str) -> GraphifyResult:
        return self._call(
            "get_neighbors", {"label": node_id, "token_budget": 2000}
        )

    def inspect_community(self, community_id: int) -> GraphifyResult:
        return self._call(
            "get_community", {"community_id": community_id, "token_budget": 2000}
        )

    def query_repository_context(self, query: str) -> GraphifyResult:
        return self.search_codegraph(query)

    def get_graph_health(self) -> GraphifyResult:
        return self._call("graph_stats", {})

    def get_shortest_path(self, source: str, target: str) -> GraphifyResult:
        return self._call(
            "shortest_path", {"source": source, "target": target, "max_hops": 8}
        )

    def get_central_nodes(self, top_n: int) -> GraphifyResult:
        return self._call("god_nodes", {"top_n": top_n})

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> "GraphifyReadOnlyClient":
        self.connect()
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        self.close()
