# TIM Manager Graphify MCP Client Baseline

Date: 2026-07-29

## Baseline decision

**MATCH — implementation may continue**

| Check | Required | Observed | Result |
|---|---|---|---|
| Repository root | `/Users/tim/Documents/TIM/tim` | same | PASS |
| Branch | `codex/github-foundation` | same | PASS |
| HEAD | `1225fd2b48794d4113aa4cf2f69e642a7097a782` | same | PASS |
| Working tree before this report | clean | clean | PASS |
| Remote | existing GitHub origin | `uezeyiraydin-cell/tim-ai-platform` | PASS |
| Graphify version | installed | `0.9.29` | PASS |
| Codegraph | existing static graph | `graphify-out/graph.json` | PASS |
| Codegraph SHA-256 | verified baseline | `60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513` | PASS |
| Nodes | 1,573 | 1,573 | PASS |
| Relationships | 3,355 | 3,355 | PASS |
| Communities | 84 | 84 | PASS |
| Graphify MCP handshake | local stdio | protocol `2025-11-25` | PASS |
| Graphify MCP tools | ten expected tools | ten exact tools | PASS |

## MCP server inventory

The live stdio inventory returned:

1. `query_graph`
2. `get_node`
3. `get_neighbors`
4. `get_community`
5. `god_nodes`
6. `graph_stats`
7. `shortest_path`
8. `list_prs`
9. `get_pr_impact`
10. `triage_prs`

None declares an MCP output schema. Every input schema includes an optional
caller-controlled `project_path`; the client must remove that authority.

## TIM Manager and dependencies

TIM Manager resides in `src/tim_manager`, with versioned configuration under
`config/tim_manager`, CLI entry through `src.tim_manager.cli`, and its existing
read-oriented MCP server in `src/tim_manager/mcp_server.py`.

The normal TIM virtual environment has no `mcp` package. The isolated research
environment contains `mcp 1.28.1`, which successfully performed the baseline
stdio handshake. The implementation must not add or migrate a project
dependency merely to provide this optional client.

## Protection baseline

No semantic indexing, external provider, global agent configuration, trading
component, Git history, or graph content was changed during baseline
verification. Query logging was disabled for the handshake.
