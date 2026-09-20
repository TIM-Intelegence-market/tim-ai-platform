# TIM GRAPH MCP — Tools

Server: `python -m src.graph_mcp.mcp_server` (stdio, line-delimited
JSON-RPC 2.0, protocol `2025-11-25`, same convention as the existing
Graphify MCP stack). 18 tools; every argument is validated against the
declared inputSchema server-side — invalid input yields a structured
error, never a traceback.

| Tool | Purpose | Notes |
|---|---|---|
| graph_health | liveness + store summary | `read_only_tim: true` |
| graph_stats | counts by type + set hashes | determinism material |
| graph_get_node | one node record | |
| graph_neighbors | neighbors, direction + edge-type filters | bounded (<=200) |
| graph_search | id/name/path/metadata modes | SQL-side, bounded, `why_matched` per result |
| graph_path | bounded shortest path | depth <= 8 |
| graph_dependencies | DEPENDS_ON/IMPORTS/READS/WRITES/USES_TOOL out-edges | |
| graph_dependents | in-edges incl. TESTS/CALLS | |
| graph_impact | categorized dependents | labeled `STATIC_GRAPH_IMPACT` |
| graph_mission_context | mission bundle: gates/incidents/notes/agents | |
| graph_incident_context | classification, recipes, blocked gates, evidence refs | |
| graph_gate_context | depends_on / blocked_by / missions | |
| graph_agent_context | role, verified tools, limitations | no secrets |
| graph_refresh_code | incremental code re-index (own store only) | hash-skip |
| graph_refresh_docs | Obsidian/recipes/agents re-index | |
| graph_refresh_runtime_readonly | services + DB schema re-index | |
| graph_export | json / mermaid / dot / graphml | graphml + graphify projection |
| graph_index_github_payload | offline provider payload adapter | no credentials |

Examples:

```
graph_search {"query": "CandleAggregator"}
graph_neighbors {"node": "class:src/data_ingestion/aggregator.py:CandleAggregator",
                 "direction": "out", "edge_types": ["DEFINES"]}
graph_impact {"node": "module:src.data_ingestion.aggregator"}
graph_mission_context {"mission": "mission:TIM/30%20Missions/LONG%20History%20Extension%20Design.md"}
graph_export {"format": "mermaid"}
```

CLI equivalents (tests, runbook):

```
.venv/bin/python -m src.graph_mcp.cli --root . --vault "<vault>" refresh-all
.venv/bin/python -m src.graph_mcp.cli --root . query search "LONG Readiness"
.venv/bin/python -m src.graph_mcp.cli --root . export --out .runtime/graph/exports
```
