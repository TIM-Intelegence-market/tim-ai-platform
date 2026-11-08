"""KI1 package 1: read-only trading tools of tim-ops."""
from __future__ import annotations

import json
import os
from pathlib import Path

from src.ops_mcp.mcp_server import OpsMcpServer
from src.ops_mcp.readers import ResearchReader, TaskReader
from src.ops_mcp.trading import TradingReader

ROOT = Path(__file__).resolve().parents[2]


def server(trading: TradingReader) -> OpsMcpServer:
    instance = OpsMcpServer(TaskReader(None), ResearchReader(ROOT), health=lambda: {}, trading=trading)
    instance.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    return instance


def call(instance, name, arguments=None):
    response = instance.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": arguments or {}}})
    return response if "error" in response else json.loads(response["result"]["content"][0]["text"])


def journal(tmp_path: Path) -> Path:
    entries = [{"id": "a", "status": "CLOSED", "direction": "LONG", "gross_r": 1.1, "net_r": 1.0,
                "plan_text": "token=supersecretvalue123", "internal_note": "nicht zeigen"}]
    path = tmp_path / "tim_plan_journal_short.json"
    path.write_text(json.dumps({"schema": "tim_plan_journal/2", "entries": entries}))
    return path


def test_not_configured_is_reported():
    instance = server(TradingReader(None, None, None))
    for name, args in (("plan_journal", {"journal": "15m"}), ("live_status", {}), ("orderflow_live", {}), ("ki_filter", {}), ("market_snapshot", {})):
        assert call(instance, name, args)["status"] == "not_configured"


def test_plan_journal_whitelists_and_redacts(tmp_path: Path):
    path = journal(tmp_path)
    before = path.read_bytes()
    result = call(server(TradingReader(tmp_path, None, None)), "plan_journal", {"journal": "15m"})
    entry = result["entries"][0]
    assert "internal_note" not in entry and "supersecretvalue123" not in entry["plan_text"]
    assert result["summary"]["sum_net_r"] == 1.0 and path.read_bytes() == before


def test_unknown_journal_and_symlink_refused(tmp_path: Path):
    instance = server(TradingReader(tmp_path, None, None))
    assert "error" in call(instance, "plan_journal", {"journal": "../etc"})
    real = journal(tmp_path)
    os.replace(real, tmp_path / "real.json")
    (tmp_path / "tim_plan_journal_short.json").symlink_to(tmp_path / "real.json")
    assert call(instance, "plan_journal", {"journal": "15m"})["error"]["code"] == -32001


def test_live_status_and_ki_filter(tmp_path: Path):
    status = tmp_path / "live_status.json"
    status.write_text(json.dumps({"stopped": False, "balance": 57.64, "api_secret": "kQ9x/abcdEFGH+ijkl=="}))
    journal(tmp_path)
    instance = server(TradingReader(tmp_path, status, tmp_path / "ki.jsonl"))
    live = call(instance, "live_status")["status"]
    assert live["balance"] == 57.64 and "kQ9x" not in json.dumps(live)
    assert call(instance, "ki_filter")["status"] == "no_decisions_yet"


def test_orderflow_live_reads_state_file(tmp_path: Path):
    path = tmp_path / "orderflow_lage.json"
    path.write_text(json.dumps({"schema": "orderflow-lage/1", "price": 75000.0, "api_key": "sk-supersecretvalue123",
                                "wave": {"direction": "auf"}, "text": "Preis 75000."}))
    instance = server(TradingReader(None, None, None, orderflow_live=path))
    result = call(instance, "orderflow_live")
    assert result["state"]["wave"]["direction"] == "auf" and result["age_seconds"] >= 0
    assert "supersecretvalue123" not in json.dumps(result)
