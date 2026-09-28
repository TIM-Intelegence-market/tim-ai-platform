# Graphify MCP Tool Inventory

Date: 2026-07-29

Runtime: Graphify `0.9.29`

Observed protocol: `2025-11-25`

Transport: local stdio

Observed tools: 10

Declared MCP output schemas: none

Every server-side input schema also contains optional `project_path`. TIM
Manager never exposes or forwards this argument; the fixed codegraph is chosen
by the process configuration.

| Tool | Real input schema | Output | Classification | Risk | Client status | Reason |
|---|---|---|---|---|---|---|
| `query_graph` | required `question`; optional `context_filter`, `depth`, `mode`, `token_budget`, server `project_path` | unstructured MCP text | local read/query | medium | **ALLOW** | bounded traversal and tokens; `project_path` removed |
| `get_node` | required `label`; server `project_path` | unstructured MCP text | local read | low | **ALLOW** | fixed graph and validated text result |
| `get_neighbors` | required `label`; optional `relation_filter`, `token_budget`, server `project_path` | unstructured MCP text | local read/query | medium | **ALLOW** | bounded result; source references extracted |
| `get_community` | required `community_id`; optional `token_budget`, server `project_path` | unstructured MCP text | local read/query | medium | **ALLOW** | bounded result; source references extracted |
| `god_nodes` | optional `top_n`, server `project_path` | unstructured MCP text | local read | low | **ALLOW** | `top_n` capped client-side |
| `graph_stats` | server `project_path` only | unstructured MCP text | local read | low | **ALLOW** | health/count query; fixed graph |
| `shortest_path` | required `source`, `target`; optional `max_hops`, server `project_path` | unstructured MCP text | local read/query | low | **ALLOW** | maximum hops capped |
| `list_prs` | optional `base`, `repo`, `project_path` | unstructured MCP text | authenticated network read | medium | **DENY** | invokes GitHub access outside the local graph |
| `get_pr_impact` | required `pr_number`; optional `repo`, `project_path` | unstructured MCP text | authenticated network read | medium | **DENY** | invokes GitHub access and broadens scope |
| `triage_prs` | optional `base`, `repo`, `project_path` | unstructured MCP text | network/governance-adjacent analysis | high | **DENY** | remote access and prioritization are outside retrieval scope |

## Client-side enforcement

The allowlist is exact and unknown tools fail closed. There is no generic CLI
passthrough. Arguments are checked against a per-tool schema before transport,
and the transport independently rejects `project_path`. Query logging is
disabled in the child environment. Denials produce structured security logs.

The server's lack of output schemas is compensated by a validated TIM result
contract, maximum response bytes, text-content checks, error-state checks,
secret redaction, source-reference extraction, and graph-hash provenance.
