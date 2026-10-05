"""#152 M3: tim-ops MCP contract and read-only guarantees. Task stores are
temporary files; the research tests read the committed register/reports."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from src.ops_mcp import SERVER_NAME
from src.ops_mcp.mcp_server import TOOLS, OpsMcpServer
from src.ops_mcp.readers import ResearchReader, SourceError, TaskReader
from src.task_engine.model import Task, TaskState
from src.task_engine.repository import SqliteTaskRepository

ROOT = Path(__file__).resolve().parents[2]
AT = "2026-10-05T10:00:00+00:00"


@pytest.fixture
def task_db(tmp_path: Path) -> Path:
    path = tmp_path / "engine.db"
    with SqliteTaskRepository(path) as repo:
        repo.create(Task(task_id="t-1", source="test", type="repair", title="first",
                         failure_reason="token=supersecretvalue123"))
        repo.create(Task(task_id="t-2", source="test", type="mission", title="second"))
        repo.transition("t-1", TaskState.PLANNED, at=AT, reason="planned")
        repo.attach_evidence("t-1", "log", "logs/run.txt", at=AT)
        repo.checkpoint("t-1", "step-1", at=AT, next_action="verify")
    return path


def server(task_db: Path | None = None, health=lambda: {"Fake": {"state": "AVAILABLE"}}):
    instance = OpsMcpServer(TaskReader(task_db), ResearchReader(ROOT), health=health)
    instance.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    return instance


def call(instance: OpsMcpServer, name: str, arguments: dict | None = None) -> dict:
    response = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": arguments or {}}})
    if "error" in response:
        return response
    return json.loads(response["result"]["content"][0]["text"])


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_handshake_and_tool_list():
    instance = OpsMcpServer(TaskReader(None), ResearchReader(ROOT))
    early = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert early["error"]["code"] == -32000
    init = instance.handle({"jsonrpc": "2.0", "id": 2, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == SERVER_NAME
    listed = instance.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    names = [tool["name"] for tool in listed["result"]["tools"]]
    assert names == [tool["name"] for tool in TOOLS] and len(names) == 8


def test_tasks_not_configured():
    instance = server()
    assert call(instance, "task_summary")["status"] == "not_configured"
    assert call(instance, "ops_health")["task_store"] == "not_configured"


def test_task_summary_list_get(task_db: Path):
    instance = server(task_db)
    summary = call(instance, "task_summary")
    assert summary["total"] == 2 and summary["by_state"]["PLANNED"] == 1
    assert summary["by_state"]["NEW"] == 1 and summary["open"] == 2
    listed = call(instance, "task_list", {"state": "NEW"})
    assert [t["task_id"] for t in listed["tasks"]] == ["t-2"]
    bounded = call(instance, "task_list", {"limit": 1})
    assert bounded["truncated"] is True and len(bounded["tasks"]) == 1
    detail = call(instance, "task_get", {"task_id": "t-1"})
    assert detail["task"]["state"] == "PLANNED"
    assert detail["history"][0]["to"] == "PLANNED"
    assert detail["evidence"][0]["name"] == "log"
    assert detail["checkpoints"][0]["next_action"] == "verify"
    assert call(instance, "task_get", {"task_id": "nope"})["status"] == "not_found"


def test_task_text_is_redacted(task_db: Path):
    detail = call(server(task_db), "task_get", {"task_id": "t-1"})
    assert "supersecretvalue123" not in json.dumps(detail)
    assert "[REDACTED]" in detail["task"]["failure_reason"]


def test_task_store_is_never_modified(task_db: Path):
    before = digest(task_db)
    instance = server(task_db)
    for name, arguments in [("task_summary", {}), ("task_list", {}),
                            ("task_get", {"task_id": "t-1"}), ("ops_health", {})]:
        call(instance, name, arguments)
    assert digest(task_db) == before
    assert not task_db.with_name("engine.db-wal").exists()


def test_reader_connection_refuses_writes(task_db: Path):
    connection = TaskReader(task_db)._connect()
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM tasks")
    finally:
        connection.close()


def test_unsafe_task_stores_are_structured_errors(tmp_path: Path, task_db: Path):
    missing = call(server(tmp_path / "missing.db"), "task_summary")
    assert missing["error"]["code"] == -32001
    foreign = tmp_path / "foreign.db"
    sqlite3.connect(foreign).execute("CREATE TABLE x (y)").connection.commit()
    assert "not a task engine" in call(server(foreign), "task_summary")["error"]["message"]
    link = tmp_path / "link.db"
    link.symlink_to(task_db)
    assert "symlink" in call(server(link), "task_summary")["error"]["message"]
    assert not (tmp_path / "missing.db").exists()


def test_invalid_arguments_are_structured():
    instance = server()
    assert call(instance, "task_list", {"state": "DONE"})["error"]["code"] == -32000
    assert call(instance, "task_list", {"bogus": 1})["error"]["code"] == -32000
    assert call(instance, "task_get", {})["error"]["code"] == -32000
    assert call(instance, "nope")["error"]["code"] == -32000
    assert "Traceback" not in json.dumps(call(instance, "task_list", {"limit": 0}))


def test_tool_health_uses_registry_probes():
    assert call(server(), "tool_health")["tools"] == {"Fake": {"state": "AVAILABLE"}}


def test_research_register_matches_committed_chain():
    register = call(server(), "research_register")
    assert register["chain_valid"] is True and register["m"] == 48
    assert sum(register["by_status"].values()) == 48


def test_research_register_detects_tampering(tmp_path: Path):
    target = tmp_path / "docs/research_lab"
    target.mkdir(parents=True)
    lines = (ROOT / "docs/research_lab/REGISTER.jsonl").read_text().splitlines()
    lines[0] = lines[0].replace('"n": 100', '"n": 101')
    (target / "REGISTER.jsonl").write_text("\n".join(lines) + "\n")
    assert ResearchReader(tmp_path).register()["status"] == "chain_broken"


def test_research_reports_and_traversal():
    instance = server()
    names = call(instance, "research_reports")["reports"]
    assert "r4_2026-09-29T2219Z.json" in names
    report = call(instance, "research_report", {"name": "r4_2026-09-29T2219Z.json", "limit": 3})
    assert report["register_m"] == 48 and len(report["variants"]) == 3
    assert {"trades", "expectancy_r", "p"} <= set(report["variants"][0]["train"])
    for name in ("../REGISTER.jsonl", "../../.mcp.json", "/etc/passwd"):
        assert call(instance, "research_report", {"name": name})["status"] == "not_found"


def test_package_has_no_write_paths():
    forbidden = re.compile(r"(?i)\b(INSERT|UPDATE\s+\w+\s+SET|DELETE\s+FROM|CREATE\s+TABLE|DROP)\b"
                           r"|executescript|write_text|write_bytes|\.transition\(|"
                           r"\.attach_evidence\(|\.checkpoint\(|SqliteTaskRepository\(|"
                           r"open\([^)]*['\"][wax+]")
    for path in (ROOT / "src/ops_mcp").glob("*.py"):
        hits = forbidden.findall(path.read_text())
        assert not hits, f"{path.name}: {hits}"


def test_mcp_json_registers_tim_ops():
    entry = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["tim-ops"]
    assert entry["args"] == ["-m", "src.ops_mcp.mcp_server"]
    assert "TIM_OPS_TASK_DB" in json.dumps(entry)
