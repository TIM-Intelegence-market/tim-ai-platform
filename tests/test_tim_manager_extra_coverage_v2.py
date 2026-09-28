from __future__ import annotations

import dataclasses
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from src.tim_manager import config_paths
from src.tim_manager.cli import main as cli_main
from src.tim_manager.graphify_mcp import (
    GraphifyMCPConfig,
    GraphifyResult,
    TRUST_CLASS,
    sha256_file,
)

GRAPH_PATH = Path(GraphifyMCPConfig.load().graph_path)
from src.tim_manager.workspace_gateway import (
    SERVER_NAME,
    WorkspaceGateway,
    WorkspaceGatewayConfig,
    WorkspaceGatewayConfigurationError,
    WorkspaceGatewayPolicyError,
    WorkspaceRequest,
    handle,
    serve,
)
from src.tim_manager.workspace_gateway import main as gateway_main


# ---------------------------------------------------------------------------
# config_paths.py
# ---------------------------------------------------------------------------


def test_config_paths_repository_root_env_override() -> None:
    root = config_paths.repository_root()
    assert config_paths.repository_root(env={"TIM_REPO_ROOT": str(root)}) == root
    with pytest.raises(config_paths.RepositoryPathError, match="absolute"):
        config_paths.repository_root(env={"TIM_REPO_ROOT": "relative/dir"})
    with pytest.raises(config_paths.RepositoryPathError, match="outside"):
        config_paths.repository_root(env={"TIM_REPO_ROOT": "/tmp"})


def test_config_paths_relative_spec_is_rejected() -> None:
    with pytest.raises(config_paths.RepositoryPathError, match="absolute or repo-relative"):
        config_paths.repository_path("graphify-out/graph.json")


def test_config_paths_absolute_path_inside_repository_is_allowed() -> None:
    root = config_paths.repository_root()
    target = config_paths.repository_path(str(root / "graphify-out" / "graph.json"))
    assert target == (root / "graphify-out" / "graph.json").resolve()


def test_config_paths_absolute_path_into_denied_directory_is_rejected() -> None:
    root = config_paths.repository_root()
    with pytest.raises(config_paths.RepositoryPathError, match="denied"):
        config_paths.repository_path(str(root / "output" / "payload.json"))


def test_config_paths_load_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_paths, "CONFIG_ROOT", tmp_path)
    (tmp_path / "probe.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert config_paths.load_config("probe.json") == {"a": 1}


def test_config_paths_canonical_json_orders_keys_and_omits_whitespace() -> None:
    assert (
        config_paths.canonical_json({"b": 1, "a": ["x", "y"]})
        == '{"a":["x","y"],"b":1}'
    )
    assert config_paths.canonical_json("café") == '"café"'


# ---------------------------------------------------------------------------
# cli.py helpers
# ---------------------------------------------------------------------------


class _FakeGraphifyConfig:
    enabled = True
    transport = "stdio"
    server_name = "tim-graphify-readonly"
    read_only = True
    trust_class = TRUST_CLASS
    expected_graph_hash = "0" * 64
    allowed_tools = ("query_graph", "get_node")


class _Dummy:
    def __init__(self, value: Any):
        self.value = value

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value}


class _FakeGraphifyClient:
    def __init__(self, config: Any, enabled_override: bool = False):
        self.config = config
        self.enabled_override = enabled_override

    def __enter__(self) -> "_FakeGraphifyClient":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def list_tools(self) -> list[str]:
        return ["query_graph", "get_node"]

    def search_codegraph(self, value: str) -> _Dummy:
        return _Dummy(("search", value))

    def inspect_node(self, value: str) -> _Dummy:
        return _Dummy(("node", value))

    def inspect_relationships(self, value: str) -> _Dummy:
        return _Dummy(("relationships", value))

    def inspect_community(self, community_id: int) -> _Dummy:
        return _Dummy(("community", community_id))

    def get_graph_health(self) -> _Dummy:
        return _Dummy("health")


def _patch_graphify(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.tim_manager.graphify_mcp as graphify_mcp

    monkeypatch.setattr(
        graphify_mcp,
        "GraphifyMCPConfig",
        type(
            "GraphifyMCPConfig",
            (),
            {"load": staticmethod(lambda: _FakeGraphifyConfig())},
        ),
    )
    monkeypatch.setattr(graphify_mcp, "GraphifyReadOnlyClient", _FakeGraphifyClient)


# ---------------------------------------------------------------------------
# cli.py subcommand coverage
# ---------------------------------------------------------------------------


def test_cli_init_prints_ready(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main(["init"]) == 0
    assert "READY" in capsys.readouterr().out


def test_cli_scan_runs_full_pipeline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    monkeypatch.setattr(cli, "scan_project", lambda: {"scan_id": "S1", "stats": {"files": 3}})
    monkeypatch.setattr(cli, "build_snapshot", lambda scan: {"snapshot_id": "SNAP1"})
    monkeypatch.setattr(cli, "persist_scan", lambda scan, snapshot: {"out": "ok"})
    assert cli_main(["scan"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scan_id"] == "S1"
    assert payload["snapshot_id"] == "SNAP1"
    assert payload["outputs"] == {"out": "ok"}


def test_cli_sources_prints_health(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    monkeypatch.setattr(cli, "load_snapshot", lambda: {"source_health": {"binance": "ok"}})
    assert cli_main(["sources"]) == 0
    assert json.loads(capsys.readouterr().out) == {"binance": "ok"}


def test_cli_status_prints_snapshot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    monkeypatch.setattr(cli, "load_snapshot", lambda: {"status": "ok"})
    assert cli_main(["status"]) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "ok"}


def test_cli_brief_reads_executive_brief(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "executive_brief.md").write_text("# Brief\n", encoding="utf-8")
    monkeypatch.setattr(cli, "ARTIFACT_ROOT", tmp_path)
    assert cli_main(["brief"]) == 0
    assert capsys.readouterr().out == "# Brief\n\n"


def test_cli_timeline_and_derived_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    snapshot = {
        "recent_changes": [{"sha": "abc"}],
        "risks": ["r"],
        "decisions": ["d"],
        "experiments": ["e"],
        "evals": ["v"],
    }
    monkeypatch.setattr(cli, "load_snapshot", lambda: snapshot)
    for command, expected in (
        ("timeline", snapshot["recent_changes"]),
        ("risks", snapshot["risks"]),
        ("decisions", snapshot["decisions"]),
        ("experiments", snapshot["experiments"]),
        ("evals", snapshot["evals"]),
    ):
        assert cli_main([command]) == 0
        assert json.loads(capsys.readouterr().out) == expected


def test_cli_search_calls_search(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    monkeypatch.setattr(cli, "search", lambda query: [{"query": query}])
    assert cli_main(["search", "trading"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"query": "trading"}]


def test_cli_query_calls_answer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    monkeypatch.setattr(cli, "answer", lambda question: {"answer": question})
    assert cli_main(["query", "why"]) == 0
    assert json.loads(capsys.readouterr().out) == {"answer": "why"}


def test_cli_diff_compares_two_snapshots(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    monkeypatch.setattr(cli, "load_snapshot", lambda path=None: {"path": str(path)})
    monkeypatch.setattr(cli, "diff_snapshots", lambda old, new: {"old": old, "new": new})
    assert cli_main(["diff", "old.json", "new.json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["old"]["path"] == "old.json"
    assert payload["new"]["path"] == "new.json"


def test_cli_export_writes_snapshot_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    output = tmp_path / "export.json"
    monkeypatch.setattr(cli, "safe_output_path", lambda relative: output)
    monkeypatch.setattr(cli, "load_snapshot", lambda: {"k": "v"})
    assert cli_main(["export", "--output", "artifacts/tim_manager/export.json"]) == 0
    assert json.loads(output.read_text(encoding="utf-8")) == {"k": "v"}
    assert "export.json" in capsys.readouterr().out


def test_cli_serve_mcp_invokes_server(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli
    import src.tim_manager.mcp_server as mcp_server

    called: list[bool] = []
    monkeypatch.setattr(mcp_server, "serve", lambda: called.append(True))
    assert cli_main(["serve-mcp"]) == 0
    assert called == [True]


def test_cli_validate_doctor_pass_and_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    monkeypatch.setattr(
        cli,
        "doctor",
        lambda: {"status": "PASS", "checks": {"config": True}},
    )
    assert cli_main(["doctor"]) == 0
    monkeypatch.setattr(
        cli,
        "doctor",
        lambda: {"status": "FAIL", "checks": {"config": False}},
    )
    assert cli_main(["validate"]) == 2
    capsys.readouterr()


def test_cli_graphify_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_graphify(monkeypatch)
    assert cli_main(["graphify", "status"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["enabled_by_default"] is True
    assert payload["transport"] == "stdio"


def test_cli_graphify_read_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_graphify(monkeypatch)
    assert cli_main(["graphify", "tools"]) == 0
    assert json.loads(capsys.readouterr().out)["tools"] == ["query_graph", "get_node"]

    assert cli_main(["graphify", "search", "TIM"]) == 0
    assert json.loads(capsys.readouterr().out) == {"value": ["search", "TIM"]}

    assert cli_main(["graphify", "node", "x"]) == 0
    assert json.loads(capsys.readouterr().out) == {"value": ["node", "x"]}

    assert cli_main(["graphify", "relationships", "x"]) == 0
    assert json.loads(capsys.readouterr().out) == {"value": ["relationships", "x"]}

    assert cli_main(["graphify", "community", "7"]) == 0
    assert json.loads(capsys.readouterr().out) == {"value": ["community", 7]}

    assert cli_main(["graphify", "health"]) == 0
    assert json.loads(capsys.readouterr().out) == {"value": "health"}


def test_cli_command_error_returns_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import src.tim_manager.cli as cli

    def failing_search(query: str) -> list[dict[str, Any]]:
        raise ValueError("boom")

    monkeypatch.setattr(cli, "search", failing_search)
    assert cli_main(["search", "x"]) == 2
    assert "boom" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# workspace_gateway.py config validation
# ---------------------------------------------------------------------------


def _gateway_config(**updates: Any) -> WorkspaceGatewayConfig:
    base: dict[str, Any] = {
        "enabled": True,
        "allowed_clients": ("canary-client",),
    }
    base.update(updates)
    return dataclasses.replace(WorkspaceGatewayConfig.load(), **base)


def _service(**updates: Any) -> WorkspaceGateway:
    client = _FakeDownstreamClient()
    return WorkspaceGateway(
        _gateway_config(**updates), client_factory=lambda: client  # type: ignore[arg-type]
    )


def _request(request_id: str, **updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "request_id": request_id,
        "query": "TIM Manager",
        "parameters": {},
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_id": "canary-client",
        "max_results": 5,
    }
    value.update(updates)
    return value


def _config_dict() -> dict[str, Any]:
    config = WorkspaceGatewayConfig.load()
    return {
        "enabled": config.enabled,
        "transport": config.transport,
        "server_name": config.server_name,
        "authentication_mode": config.authentication_mode,
        "allowed_clients": list(config.allowed_clients),
        "allowed_operations": list(config.allowed_operations),
        "read_only": config.read_only,
        "max_request_bytes": config.max_request_bytes,
        "max_query_length": config.max_query_length,
        "max_results": config.max_results,
        "max_response_bytes": config.max_response_bytes,
        "request_timeout_seconds": config.request_timeout_seconds,
        "max_parallel_requests": config.max_parallel_requests,
        "rate_limit_requests": config.rate_limit_requests,
        "rate_limit_window_seconds": config.rate_limit_window_seconds,
        "max_clock_skew_seconds": config.max_clock_skew_seconds,
        "replay_window_seconds": config.replay_window_seconds,
        "audit_to_stderr": config.audit_to_stderr,
        "allow_anonymous": config.allow_anonymous,
        "allow_unknown_operations": config.allow_unknown_operations,
        "allow_writes": config.allow_writes,
    }


def test_gateway_config_from_dict_roundtrips() -> None:
    assert WorkspaceGatewayConfig.from_dict(_config_dict()) == WorkspaceGatewayConfig.load()


def test_gateway_config_from_dict_rejects_non_object() -> None:
    with pytest.raises(WorkspaceGatewayConfigurationError, match="must be an object"):
        WorkspaceGatewayConfig.from_dict("not-a-dict")


def test_gateway_config_from_dict_rejects_missing_and_unknown_keys() -> None:
    missing = _config_dict()
    missing.pop("enabled")
    with pytest.raises(WorkspaceGatewayConfigurationError, match="missing"):
        WorkspaceGatewayConfig.from_dict(missing)
    unknown = _config_dict()
    unknown["surprise"] = True
    with pytest.raises(WorkspaceGatewayConfigurationError, match="unknown"):
        WorkspaceGatewayConfig.from_dict(unknown)


def test_gateway_config_from_dict_rejects_bad_string_arrays() -> None:
    bad_type = _config_dict()
    bad_type["allowed_clients"] = "canary-client"
    with pytest.raises(WorkspaceGatewayConfigurationError, match="string array"):
        WorkspaceGatewayConfig.from_dict(bad_type)
    bad_item = _config_dict()
    bad_item["allowed_operations"] = ["search_repository_graph", 42]
    with pytest.raises(WorkspaceGatewayConfigurationError, match="string array"):
        WorkspaceGatewayConfig.from_dict(bad_item)


def test_gateway_config_from_dict_rejects_non_numeric_bounds() -> None:
    value = _config_dict()
    value["max_results"] = True
    with pytest.raises(WorkspaceGatewayConfigurationError, match="numeric"):
        WorkspaceGatewayConfig.from_dict(value)


def test_gateway_config_load_missing_or_malformed(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceGatewayConfigurationError, match="missing or malformed"):
        WorkspaceGatewayConfig.load(tmp_path / "missing.yaml")
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("{not json", encoding="utf-8")
    with pytest.raises(WorkspaceGatewayConfigurationError, match="missing or malformed"):
        WorkspaceGatewayConfig.load(malformed)


def test_gateway_config_validate_rejects_non_boolean_switches() -> None:
    with pytest.raises(WorkspaceGatewayConfigurationError, match="switches must be booleans"):
        dataclasses.replace(WorkspaceGatewayConfig.load(), enabled=1).validate()


def test_gateway_config_validate_rejects_identity_or_transport_mismatch() -> None:
    for candidate in (
        dataclasses.replace(WorkspaceGatewayConfig.load(), transport="http"),
        dataclasses.replace(WorkspaceGatewayConfig.load(), server_name="other"),
        dataclasses.replace(WorkspaceGatewayConfig.load(), authentication_mode="open"),
    ):
        with pytest.raises(WorkspaceGatewayConfigurationError, match="identity or transport"):
            candidate.validate()


def test_gateway_config_validate_rejects_operation_allowlist_mismatch() -> None:
    candidate = dataclasses.replace(
        WorkspaceGatewayConfig.load(), allowed_operations=("search_repository_graph",)
    )
    with pytest.raises(WorkspaceGatewayConfigurationError, match="allowlist mismatch"):
        candidate.validate()


def test_gateway_config_validate_rejects_duplicate_and_invalid_clients() -> None:
    with pytest.raises(WorkspaceGatewayConfigurationError, match="duplicates"):
        dataclasses.replace(WorkspaceGatewayConfig.load(), allowed_clients=("a", "a")).validate()
    with pytest.raises(WorkspaceGatewayConfigurationError, match="invalid allowed client"):
        dataclasses.replace(WorkspaceGatewayConfig.load(), allowed_clients=("",)).validate()


def test_gateway_config_validate_rejects_non_positive_bounds() -> None:
    with pytest.raises(WorkspaceGatewayConfigurationError, match="positive"):
        dataclasses.replace(WorkspaceGatewayConfig.load(), max_request_bytes=0).validate()


def test_gateway_config_validate_rejects_overbroad_bounds() -> None:
    with pytest.raises(WorkspaceGatewayConfigurationError, match="bounds too broad"):
        dataclasses.replace(WorkspaceGatewayConfig.load(), max_results=21).validate()
    with pytest.raises(WorkspaceGatewayConfigurationError, match="bounds too broad"):
        dataclasses.replace(WorkspaceGatewayConfig.load(), max_parallel_requests=5).validate()


# ---------------------------------------------------------------------------
# workspace_gateway.py request parsing / authorization
# ---------------------------------------------------------------------------


def test_gateway_requires_authorized_client() -> None:
    with pytest.raises(WorkspaceGatewayConfigurationError, match="no authorized"):
        WorkspaceGateway(_gateway_config(allowed_clients=()))


def test_gateway_default_client_factory_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.tim_manager.workspace_gateway as wg

    enabled_flags: list[bool] = []
    fake = _FakeDownstreamClient()

    class Factory:
        def __new__(cls, config: Any, enabled_override: bool = False) -> Any:
            enabled_flags.append(enabled_override)
            return fake

    monkeypatch.setattr(wg, "GraphifyReadOnlyClient", Factory)
    service = WorkspaceGateway(_gateway_config())
    response = service.process("health_check", _request("default-factory", query=""))
    assert response["status"] == "success"
    assert enabled_flags == [True]


class _FakeDownstreamClient:
    def __init__(self, response: Any = None):
        self.response = response if response is not None else _result()
        self.calls: list[tuple[str, Any]] = []

    def _call(self, name: str, value: Any = None) -> Any:
        self.calls.append((name, value))
        return self.response

    def search_codegraph(self, value: str) -> Any:
        return self._call("search_codegraph", value)

    def inspect_node(self, value: str) -> Any:
        return self._call("inspect_node", value)

    def inspect_relationships(self, value: str) -> Any:
        return self._call("inspect_relationships", value)

    def inspect_community(self, value: int) -> Any:
        return self._call("inspect_community", value)

    def get_graph_health(self) -> Any:
        return self._call("get_graph_health")

    def get_shortest_path(self, source: str, target: str) -> Any:
        return self._call("get_shortest_path", (source, target))

    def get_central_nodes(self, top_n: int) -> Any:
        return self._call("get_central_nodes", top_n)

    def close(self) -> None:
        pass


def _result(text: str = "NODE") -> GraphifyResult:
    return GraphifyResult(
        query_id="fake-query",
        server_name="tim-graphify-readonly",
        tool_name="query_graph",
        graph_hash=sha256_file(GRAPH_PATH),
        generated_at_utc=datetime.now(timezone.utc).isoformat(),
        trust_class=TRUST_CLASS,
        results=({"type": "text", "text": text},),
        source_refs=("src/tim.py",),
        warnings=(),
        truncated=False,
        raw_response_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def test_gateway_request_parse_rejects_schema_mismatch() -> None:
    payload = _request("schema")
    payload["extra_key"] = True
    with pytest.raises(WorkspaceGatewayPolicyError, match="schema mismatch"):
        WorkspaceRequest.parse(payload, "search_repository_graph", _gateway_config())


def test_gateway_request_parse_rejects_invalid_field_types() -> None:
    config = _gateway_config()
    bad_request_id = _request("t1")
    bad_request_id["request_id"] = 123
    with pytest.raises(WorkspaceGatewayPolicyError, match="string field"):
        WorkspaceRequest.parse(
            bad_request_id, "search_repository_graph", config
        )
    with pytest.raises(WorkspaceGatewayPolicyError, match="parameters must be an object"):
        WorkspaceRequest.parse(
            _request("t2", parameters=[1, 2]), "search_repository_graph", config
        )
    with pytest.raises(WorkspaceGatewayPolicyError, match="max_results must be an integer"):
        WorkspaceRequest.parse(
            _request("t3", max_results=2.5), "search_repository_graph", config
        )


def test_gateway_request_validate_rejects_invalid_request_id() -> None:
    config = _gateway_config()
    with pytest.raises(WorkspaceGatewayPolicyError, match="request_id"):
        WorkspaceRequest.parse(_request("bad id!"), "search_repository_graph", config)
    with pytest.raises(WorkspaceGatewayPolicyError, match="request_id"):
        WorkspaceRequest.parse(_request(""), "search_repository_graph", config)


def test_gateway_request_validate_rejects_oversized_and_nul_queries() -> None:
    with pytest.raises(WorkspaceGatewayPolicyError, match="query exceeds policy"):
        WorkspaceRequest.parse(
            _request("q1", query="x" * 5000),
            "search_repository_graph",
            _gateway_config(max_query_length=100),
        )
    with pytest.raises(WorkspaceGatewayPolicyError, match="query exceeds policy"):
        WorkspaceRequest.parse(
            _request("q2", query="a\x00b"),
            "search_repository_graph",
            _gateway_config(),
        )


def test_gateway_request_validate_rejects_invalid_timestamp() -> None:
    with pytest.raises(WorkspaceGatewayPolicyError, match="requested_at_utc"):
        WorkspaceRequest.parse(
            _request("ts", requested_at_utc="not-a-date"),
            "search_repository_graph",
            _gateway_config(),
        )


def test_gateway_request_validate_requires_query_for_search_operations() -> None:
    with pytest.raises(WorkspaceGatewayPolicyError, match="requires a query"):
        WorkspaceRequest.parse(
            _request("rq", query=""), "get_graph_node", _gateway_config()
        )


def test_gateway_request_validate_rejects_invalid_operation_parameters() -> None:
    config = _gateway_config()
    with pytest.raises(WorkspaceGatewayPolicyError, match="community_id"):
        WorkspaceRequest.parse(
            _request("p1", query="", parameters={"community_id": "x"}),
            "get_graph_community",
            config,
        )
    with pytest.raises(WorkspaceGatewayPolicyError, match="community_id"):
        WorkspaceRequest.parse(
            _request("p2", query="", parameters={"community_id": True}),
            "get_graph_community",
            config,
        )
    with pytest.raises(WorkspaceGatewayPolicyError, match="shortest path"):
        WorkspaceRequest.parse(
            _request("p3", query="", parameters={"source": "", "target": "B"}),
            "get_shortest_path",
            config,
        )
    with pytest.raises(WorkspaceGatewayPolicyError, match="top_n"):
        WorkspaceRequest.parse(
            _request("p4", query="", parameters={"top_n": 0}),
            "get_central_nodes",
            config,
        )


def test_gateway_authorize_prunes_expired_replay_entries() -> None:
    service = _service(replay_window_seconds=1)
    service._seen_requests[("canary-client", "expired")] = 0.0
    response = service.process("search_repository_graph", _request("expired"))
    assert response["status"] == "success"


def test_gateway_authorize_enforces_rate_limit() -> None:
    service = _service(rate_limit_requests=1)
    assert service.process("search_repository_graph", _request("rl-1"))["status"] == "success"
    assert service.process("search_repository_graph", _request("rl-2"))["status"] == "denied"


def test_gateway_concurrency_limit_is_denied() -> None:
    service = _service()
    assert service._semaphore.acquire(blocking=False) is True
    try:
        response = service.process("search_repository_graph", _request("conc"))
        assert response["status"] == "denied"
        assert "concurrency" in response["warnings"][0]
    finally:
        service._semaphore.release()


def test_gateway_invalid_downstream_result_type_is_error() -> None:
    class NotAResult:
        pass

    client = _FakeDownstreamClient(response=NotAResult())
    service = WorkspaceGateway(
        _gateway_config(), client_factory=lambda: client  # type: ignore[arg-type]
    )
    response = service.process("health_check", _request("nres", query=""))
    assert response["status"] == "error"


def test_gateway_downstream_generic_provenance_failure_is_error() -> None:
    import src.tim_manager.workspace_gateway as wg

    class BadProvenanceResult(GraphifyResult):
        def to_dict(self) -> Any:
            raise ValueError("provenance explode")

    bad = BadProvenanceResult(**dataclasses.asdict(_result()))
    client = _FakeDownstreamClient(response=bad)
    service = WorkspaceGateway(
        _gateway_config(), client_factory=lambda: client  # type: ignore[arg-type]
    )
    response = service.process("search_repository_graph", _request("bad-prov"))
    assert response["status"] == "error"


def test_gateway_denies_parent_directory_traversal_query() -> None:
    client = _FakeDownstreamClient()
    service = WorkspaceGateway(
        _gateway_config(), client_factory=lambda: client  # type: ignore[arg-type]
    )
    response = service.process(
        "search_repository_graph", _request("traversal", query="../../../etc/passwd")
    )
    assert response["status"] == "denied"
    assert client.calls == []


def test_gateway_authorize_prunes_expired_rate_window_entries() -> None:
    from collections import deque

    service = _service(rate_limit_requests=10)
    service._rate_windows["canary-client"] = deque([0.0])
    response = service.process("search_repository_graph", _request("window-prune"))
    assert response["status"] == "success"


# ---------------------------------------------------------------------------
# workspace_gateway.py serve / main
# ---------------------------------------------------------------------------


def test_gateway_serve_handles_protocol_lines_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import logging

    import src.tim_manager.workspace_gateway as wg

    wg.LOGGER.handlers.clear()
    wg.LOGGER.setLevel(logging.NOTSET)
    config = _gateway_config(max_request_bytes=200)
    monkeypatch.setattr(wg.WorkspaceGatewayConfig, "load", lambda *args, **kwargs: config)

    lines = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "bogus"}),
            "{not-json",
            "x" * 300,
        ]
    ) + "\n"
    stdin = io.StringIO(lines)
    stdout = io.StringIO()
    monkeypatch.setattr(wg.sys, "stdin", stdin)
    monkeypatch.setattr(wg.sys, "stdout", stdout)

    try:
        serve(tmp_path / "unused.yaml")
        output = stdout.getvalue()
        assert SERVER_NAME in output
        assert '"code":-32601' in output
        assert '"code":-32603' in output
        assert output.count("\n") == 5
    finally:
        wg.LOGGER.handlers.clear()
        wg.LOGGER.propagate = True
        wg.LOGGER.setLevel(logging.NOTSET)


def test_gateway_main_returns_error_for_missing_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gateway_main(["--config", "/nonexistent/config/gateway.yaml"]) == 2
    assert "ERROR" in capsys.readouterr().err


def test_gateway_main_success_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.tim_manager.workspace_gateway as wg

    monkeypatch.setattr(wg, "serve", lambda path: None)
    assert gateway_main(["--config", "/tmp/config.yaml"]) == 0


def test_gateway_handle_tools_call_is_error_when_denied() -> None:
    service = WorkspaceGateway(
        _gateway_config(), client_factory=lambda: _FakeDownstreamClient()  # type: ignore[arg-type]
    )
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "commit", "arguments": _request("denied-call")},
        },
        service,
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["status"] == "denied"
