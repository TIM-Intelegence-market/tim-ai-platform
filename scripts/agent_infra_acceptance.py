#!/usr/bin/env python3
"""Real Serena acceptance (STEPS 3-6) — spawns one scoped read-only serena
instance against the canonical read source, proves symbol/reference lookup
for CandleAggregator and DurableOutboxWorker, maps results through the
canonical-ID bridge and cross-checks Graph MCP. Exit 0 only on PASS."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agent_infra.bridge import serena_symbol_to_graph_id  # noqa: E402
from src.agent_infra.serena_client import (  # noqa: E402
    SerenaClient, flatten_references)
from src.graph_mcp.mcp_server import build_service  # noqa: E402

READ_ROOT = os.environ.get("TIM_SERENA_READ_ROOT",
                           str(Path.home() / "Documents/TIM/tim"))
VAULT = os.environ.get("TIM_OBSIDIAN_VAULT", "")
VAULT_PATH = Path(VAULT) if VAULT else None
WORKTREE = Path(__file__).resolve().parents[1]
results: dict[str, object] = {}


def check(name: str, condition: bool, detail: str = "") -> None:
    results[name] = "PASS" if condition else "FAIL"
    print(f"{name}={'PASS' if condition else 'FAIL'}" + (f" ({detail})" if detail else ""))


with SerenaClient(READ_ROOT, timeout=120) as serena:
    started = time.monotonic()
    serena.initialize()
    tools = serena.tool_names()
    check("SERENA_TOOLS_INVENTORY", len(tools) >= 20, f"{len(tools)} tools")
    required = {"find_symbol", "find_referencing_symbols", "get_symbols_overview"}
    check("SERENA_REQUIRED_TOOLS", required <= set(tools))

    # --- CandleAggregator ------------------------------------------------
    agg = serena.find_symbol("CandleAggregator", "src/data_ingestion/aggregator.py")
    check("CANDLE_AGGREGATOR_CLASS", len(agg) == 1 and agg[0]["kind"] == "Class")
    methods = []
    for method in ("add_trade", "snapshots", "__init__"):
        found = serena.find_symbol(method, "src/data_ingestion/aggregator.py")
        methods.extend(f for f in found if f["kind"] == "Method"
                       and f["name_path"].startswith("CandleAggregator/"))
    method_names = sorted(m["name_path"].split("/")[-1] for m in methods)
    check("CANDLE_AGGREGATOR_METHODS", {"add_trade", "snapshots"} <= set(method_names),
          ",".join(method_names))
    refs = flatten_references(serena.find_referencing_symbols(
        "CandleAggregator", "src/data_ingestion/aggregator.py"))
    test_refs = [r for r in refs if r["file"].startswith("tests/")]
    check("CANDLE_AGGREGATOR_REFERENCES", len(refs) >= 3, f"{len(refs)} refs")
    check("CANDLE_AGGREGATOR_TESTS", len(test_refs) >= 1,
          ",".join(sorted({r["file"] for r in test_refs})[:3]))

    # --- DurableOutboxWorker --------------------------------------------
    dur = serena.find_symbol("DurableOutboxWorker", "src/data_ingestion/durable.py")
    check("DURABLE_OUTBOX_CLASS", len(dur) == 1 and dur[0]["kind"] == "Class")
    recover = serena.find_symbol("recover_one", "src/data_ingestion/durable.py")
    check("DURABLE_OUTBOX_RECOVER_ONE",
          any(r["kind"] == "Method" and "recover_one" in r["name_path"] for r in recover))
    drefs = flatten_references(serena.find_referencing_symbols(
        "DurableOutboxWorker", "src/data_ingestion/durable.py"))
    dtests = [r for r in drefs if r["file"].startswith("tests/")]
    check("DURABLE_OUTBOX_REFERENCES", len(drefs) >= 1, f"{len(drefs)} refs")
    check("DURABLE_OUTBOX_TESTS", len(dtests) >= 1,
          ",".join(sorted({r["file"] for r in dtests})[:3]))
    results["serena_latency_seconds"] = round(time.monotonic() - started, 2)

    # --- Bridge + Graph MCP (STEPS 5-6) ----------------------------------
    canonical = serena_symbol_to_graph_id(agg[0])
    check("BRIDGE_CANONICAL_ID",
          canonical == "class:src/data_ingestion/aggregator.py:CandleAggregator",
          canonical)
    service = build_service(WORKTREE, WORKTREE / ".runtime/graph/graph.sqlite",
                            vault=VAULT_PATH)
    node = service.get_node(canonical)
    check("GRAPH_GET_NODE", node.get("type") == "Class", canonical)
    neighbors = service.neighbors(canonical, edge_types=["DEFINES"])
    check("GRAPH_NEIGHBORS", len(neighbors["edges"]) >= 3,
          f"{len(neighbors['edges'])} DEFINES")
    dependents = service.dependents(canonical)
    check("GRAPH_DEPENDENTS", len(dependents["edges"]) >= 1,
          f"{len(dependents['edges'])} in-edges (incl. DEFINES)")
    module_dependents = service.dependents(
        "module:src.data_ingestion.aggregator")
    module_tests = [e for e in module_dependents["edges"] if e["type"] == "TESTS"]
    check("GRAPH_MODULE_TEST_COVERAGE", len(module_tests) >= 1,
          f"{len(module_tests)} TESTS edges")
    impact = service.impact(canonical)
    check("GRAPH_IMPACT", impact["analysis"] == "STATIC_GRAPH_IMPACT")
    method_id = serena_symbol_to_graph_id(
        {"relative_path": "src/data_ingestion/aggregator.py",
         "name_path": "CandleAggregator.add_trade", "kind": "Method"})
    check("BRIDGE_METHOD_ID",
          method_id == "method:src/data_ingestion/aggregator.py:CandleAggregator.add_trade")

failed = [k for k, v in results.items() if v == "FAIL"]
print(json.dumps({"CANDLE_AGGREGATOR_SERENA": "PASS" if not any(
    k.startswith("CANDLE") and v == "FAIL" for k, v in results.items()) else "FAIL",
    "DURABLE_OUTBOX_SERENA": "PASS" if not any(
    k.startswith("DURABLE") and v == "FAIL" for k, v in results.items()) else "FAIL",
    "SERENA_GRAPH_BRIDGE": "PASS" if not any(
    k.startswith(("BRIDGE", "GRAPH")) and v == "FAIL" for k, v in results.items()) else "FAIL"}))
sys.exit(1 if failed else 0)
