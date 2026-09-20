#!/usr/bin/env python3
"""STEP 15 efficiency measurement + STEP 16 LONG context preflight.

A (native): full-file read of aggregator.py + grep across src/tests.
B (routed): Serena symbols/references + Graph MCP neighbors/impact.
Measured, never invented. The LONG part is CONTEXT ROUTING ONLY — no E2
files, no test DB, no manifests are touched."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent_infra.preflight import ContextPreflight  # noqa: E402
from src.agent_infra.serena_client import SerenaClient, flatten_references  # noqa: E402
from src.graph_mcp.mcp_server import build_service  # noqa: E402

VAULT = os.environ.get("TIM_OBSIDIAN_VAULT", "")
VAULT_PATH = Path(VAULT) if VAULT else None
WORKTREE = Path(__file__).resolve().parents[1]
READ_ROOT = os.environ.get("TIM_SERENA_READ_ROOT",
                           str(Path.home() / "Documents/TIM/tim"))


def measure_native() -> dict:
    started = time.monotonic()
    files_read = 0
    chars = 0
    lines = 0
    aggregator = Path(READ_ROOT) / "src/data_ingestion/aggregator.py"
    text = aggregator.read_text()
    files_read += 1
    chars += len(text)
    lines += text.count("\n")
    grep = subprocess.run(
        ["grep", "-rn", "CandleAggregator", "src", "tests"],
        cwd=READ_ROOT, capture_output=True, text=True)
    grep_lines = [l for l in grep.stdout.splitlines() if l]
    files_read += len({l.split(":")[0] for l in grep_lines})
    chars += len(grep.stdout)
    lines += len(grep_lines)
    return {"files_read": files_read, "lines": lines, "chars": chars,
            "latency_s": round(time.monotonic() - started, 3)}


def measure_routed() -> dict:
    started = time.monotonic()
    files_read = 0
    chars = 0
    with SerenaClient(READ_ROOT, timeout=120) as serena:
        serena.initialize()
        symbols = serena.find_symbol("CandleAggregator",
                                     "src/data_ingestion/aggregator.py")
        refs = flatten_references(serena.find_referencing_symbols(
            "CandleAggregator", "src/data_ingestion/aggregator.py"))
    files_read += len({r["file"] for r in refs})
    payload = json.dumps({"symbols": symbols, "references": refs},
                         default=str)
    chars += len(payload)
    service = build_service(WORKTREE, WORKTREE / ".runtime/graph/graph.sqlite")
    neighbors = service.neighbors(
        "class:src/data_ingestion/aggregator.py:CandleAggregator")
    impact = service.impact("class:src/data_ingestion/aggregator.py:CandleAggregator")
    graph_payload = json.dumps({"neighbors": neighbors, "impact": impact},
                               default=str)
    chars += len(graph_payload)
    return {"files_read": files_read,
            "lines": len(refs) + len(symbols),
            "chars": chars,
            "latency_s": round(time.monotonic() - started, 3)}


def long_context_preflight() -> dict:
    service = build_service(WORKTREE, WORKTREE / ".runtime/graph/graph.sqlite",
                            vault=VAULT_PATH)
    preflight = ContextPreflight(service)
    from src.agent_infra.router import ContextRequest, Intent
    plan = preflight.plan(ContextRequest(intent=Intent.MISSION,
                                         mission="LONG"))
    pack = preflight.build_pack("Continue LONG readiness",
                                mission_query="LONG History Extension")
    return {
        "routing_primary": plan["decision"]["primary_tool"],
        "mission": pack.mission,
        "gates": len(pack.gates), "docs": len(pack.docs),
        "incidents": len(pack.incidents),
        "blockers": pack.blockers,
        "pack_chars": len(pack.serialize()),
        "pass": pack.mission is not None
                and plan["decision"]["primary_tool"] == "TIMGraphMCP",
    }


if __name__ == "__main__":
    native = measure_native()
    routed = measure_routed()
    print("NATIVE_CONTEXT:", json.dumps(native))
    print("ROUTED_CONTEXT:", json.dumps(routed))
    print("CHAR_REDUCTION_FACTOR:", round(native["chars"] / max(1, routed["chars"]), 1))
    long_result = long_context_preflight()
    print("LONG_CONTEXT:", json.dumps(long_result, default=str))
    print(f"LONG_CONTEXT_PREFLIGHT={'PASS' if long_result['pass'] else 'FAIL'}")
    sys.exit(0 if long_result["pass"] else 1)
