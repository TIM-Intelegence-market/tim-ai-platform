# Graphify Semantic Recovery Baseline

Date: 2026-07-29

## Verdict

**BASELINE MATCHES — CONTINUE**

The verified repository, graph, and MCP state matches the master-prompt
baseline. No material discrepancy was found.

## Repository state

| Check | Expected | Observed | Result |
|---|---|---|---|
| Branch | `codex/github-foundation` | `codex/github-foundation` | PASS |
| HEAD | `39a9d79e8af7ce12b88d6609b16432797f240d71` | same | PASS |
| Remote branch HEAD | same as local HEAD | same | PASS |
| Working tree | clean | clean | PASS |
| Graphify | 0.9.29 | 0.9.29 | PASS |
| Graph nodes | 1,573 | 1,573 | PASS |
| Graph edges | 3,355 | 3,355 | PASS |
| Communities | 84 | 84 | PASS |
| Graph SHA-256 | recorded prior graph | `60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513` | PASS |

The graph's internal `built_at_commit` is
`925ad91e6b920edb5d7fcb372ed1bb39fa43bda4`, the source commit used for
extraction. Commit `39a9d79e8af7ce12b88d6609b16432797f240d71`
adds the graph and integration reports. This expected self-reference boundary
was already documented and is not a baseline discrepancy.

## MCP baseline

The local server was started on loopback for the bounded test, completed MCP
initialization with protocol `2025-03-26`, and was stopped afterward.

Runtime dependency state:

- Graphify package: `graphifyy 0.9.29`
- MCP compatibility pin in isolated Graphify tool: `mcp 1.29.0`
- TIM dependencies: unchanged

Exactly ten tools were exposed:

1. `get_community`
2. `get_neighbors`
3. `get_node`
4. `get_pr_impact`
5. `god_nodes`
6. `graph_stats`
7. `list_prs`
8. `query_graph`
9. `shortest_path`
10. `triage_prs`

The baseline check performed no repository write through MCP and changed no
Git, governance, scientific, research, trading, or acceptance state.
