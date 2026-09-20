#!/usr/bin/env python3
"""R11 MCP protocol acceptance probe: starts the real server over stdio and
exercises initialize / tools/list / tools/call (valid + invalid). Exits 0 on
PASS, 1 on any FAIL. No TIM production surface is touched.

Portable configuration (no machine-specific defaults):
  TIM_GRAPH_MCP_ROOT   repo root under test (default: this repo, derived
                       from the script location)
  TIM_GRAPH_MCP_PY     python interpreter (default: the running interpreter)
  TIM_GRAPH_MCP_DB     graph store (default: <root>/.runtime/graph/graph.sqlite)
  TIM_GRAPH_MCP_VAULT  vault (optional; omitted when empty)
"""
import json
import os
import select
import subprocess
import sys
from pathlib import Path

ROOT = os.environ.get("TIM_GRAPH_MCP_ROOT",
                      str(Path(__file__).resolve().parents[1]))
PY = os.environ.get("TIM_GRAPH_MCP_PY", sys.executable)
DB = os.environ.get("TIM_GRAPH_MCP_DB",
                    str(Path(ROOT) / ".runtime/graph/graph.sqlite"))
VAULT = os.environ.get("TIM_GRAPH_MCP_VAULT", "")

env = {**os.environ,
       "TIM_GRAPH_MCP_ROOT": ROOT,
       "TIM_GRAPH_MCP_DB": DB}
if VAULT:
    env["TIM_GRAPH_MCP_VAULT"] = VAULT

proc = subprocess.Popen(
    [PY, "-m", "src.graph_mcp.mcp_server"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, bufsize=1, cwd=ROOT, env=env)


def send(payload: dict, expect_response: bool = True, timeout: float = 20.0) -> dict | None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    if not expect_response:
        return None
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        return {"__timeout__": True}
    line = proc.stdout.readline()
    return json.loads(line) if line else {"__closed__": True}


results = {}

init = send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
results["MCP_INITIALIZE"] = (
    init and init.get("result", {}).get("serverInfo", {}).get("name") == "tim-graph-mcp")

send({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_response=False)

tools = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
names = [t["name"] for t in tools.get("result", {}).get("tools", [])]
results["TOOLS_LIST"] = len(names) == 18
results["TOOLS_TOTAL"] = len(names)

health = send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": "graph_health", "arguments": {}}})
results["GRAPH_HEALTH"] = '"status": "ok"' in health["result"]["content"][0]["text"]

search = send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
               "params": {"name": "graph_search",
                          "arguments": {"query": "CandleAggregator"}}})
results["GRAPH_SEARCH"] = "CandleAggregator" in search["result"]["content"][0]["text"]

neighbors = send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                  "params": {"name": "graph_neighbors",
                             "arguments": {"node": "class:src/data_ingestion/aggregator.py:CandleAggregator"}}})
results["GRAPH_NEIGHBORS"] = '"edges"' in neighbors["result"]["content"][0]["text"]

mission = send({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                "params": {"name": "graph_mission_context",
                           "arguments": {"mission": "mission:TIM/30%20Missions/LONG%20History%20Extension%20Design.md"}}})
mission_text = mission["result"]["content"][0]["text"]
results["MISSION_CONTEXT"] = '"LONG History Extension Design"' in mission_text or '"notes"' in mission_text

exported = send({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                 "params": {"name": "graph_export", "arguments": {"format": "mermaid"}}})
results["GRAPH_EXPORT"] = "graph TD" in exported["result"]["content"][0]["text"]

bad = send({"jsonrpc": "2.0", "id": 8, "method": "tools/call",
            "params": {"name": "graph_search", "arguments": {"query": ""}}})
results["INVALID_STRUCTURED_ERROR"] = "error" in bad and "Traceback" not in json.dumps(bad)

proc.stdin.close()
try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait()

ok = all(value for key, value in results.items() if key != "TOOLS_TOTAL")
for key, value in results.items():
    print(f"{key}={'PASS' if value else 'FAIL'}")
print(f"MCP_PROTOCOL={'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
