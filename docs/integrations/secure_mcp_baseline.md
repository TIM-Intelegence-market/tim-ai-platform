# TIM Secure MCP Baseline

Date: 2026-07-31  
Decision: **PASS — secure MCP capability and permission discovery may begin**

```json
{
  "repository_root": "/Users/tim/Documents/TIM/tim",
  "branch_before_target_creation": "codex/workspace-agent-graphify",
  "branch": "codex/workspace-agent-secure-mcp",
  "head": "a6bf59709655094af12a9299c2c936ed106ad641",
  "working_tree_clean_before_baseline_document": true,
  "graphify_version": "0.9.29",
  "codegraph_hash": "60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513",
  "nodes": 1573,
  "relationships": 3355,
  "communities": 84,
  "gateway_enabled": false,
  "gateway_read_only": true,
  "gateway_fail_closed": true,
  "allowed_operations": [
    "search_repository_graph",
    "get_graph_node",
    "get_node_neighbors",
    "get_graph_community",
    "get_graph_statistics",
    "get_shortest_path",
    "get_central_nodes",
    "health_check"
  ],
  "doctor_exit_code": 0,
  "validate_exit_code": 0,
  "test_count": 326
}
```

## Verified environment

| Check | Observed | Result |
|---|---|---|
| Required source branch | `codex/workspace-agent-graphify` | PASS |
| Required source commit | `a6bf59709655094af12a9299c2c936ed106ad641` | PASS |
| Source working tree | clean | PASS |
| Remote | `origin` → private TIM GitHub repository | PASS |
| Python | 3.14.6 | PASS |
| Operating system | macOS 26.5.1, build 25F80 | PASS |
| TIM Manager | 1.0.0 | PASS |
| Graphify CLI | 0.9.29 | PASS |
| `tunnel-client` | not installed / not found on `PATH` | pending |
| Graphify transport | local stdio | PASS |
| Graphify client policy | disabled by default, read-only, fail-closed | PASS |
| Gateway policy | disabled by default, read-only, fail-closed | PASS |
| Gateway operation allowlist | exact eight-operation match | PASS |
| Internal Graphify allowlist | exact seven-tool match | PASS |
| Doctor | PASS, exit 0 | PASS |
| Validate | PASS, exit 0 | PASS |
| Complete test suite | 326 passed, 0 failed, 145 warnings | PASS |

The warnings are the pre-existing Python 3.14 `pytest-asyncio` deprecations.
No tunnel was downloaded or started. No external connection, semantic
indexing, graph write, protected-file write, global Git configuration change,
merge, tag, release, or trading action occurred.

Before implementation, SHA-256 values were captured for all 455 tracked
repository files, the codegraph, and the global Git configuration. Listening
TCP sockets were also recorded locally for the later protected-state
comparison; the raw host snapshot is not committed.
