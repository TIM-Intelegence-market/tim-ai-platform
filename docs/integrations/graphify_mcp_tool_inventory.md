# Graphify MCP Tool Inventory

Date: 2026-07-29

Runtime: Graphify 0.9.29 with isolated `mcp 1.29.0`

Transport tested: local loopback HTTP for inventory; preferred future client
transport is stdio.

Graphify exposes no MCP `outputSchema`; every tool returns an MCP text-content
envelope. Consumers must treat output as untrusted text and preserve cited
source fields.

| Tool | Purpose | Required input | Output | Classification | Risk | TIM Manager exposure |
|---|---|---|---|---|---|---|
| `query_graph` | BFS/DFS graph search | `question` | cited node/edge text | Read/query; query logging is opt-in and disabled | Medium: untrusted text, variable result size | Allow only through wrapper with fixed graph, budgets, no `project_path` |
| `get_node` | Node details | `label` | node metadata text | Read | Low | Allow through wrapper |
| `get_neighbors` | Direct relationships | `label` | relationship text | Read | Medium: result expansion | Allow with fixed budget |
| `get_community` | Community members | `community_id` | member/source text | Read | Medium: broad result | Allow with fixed budget |
| `god_nodes` | Most connected nodes | none | ranked text | Read | Low | Allow with bounded `top_n` |
| `graph_stats` | Graph counts/confidence | none | summary text | Read | Low | Allow |
| `shortest_path` | Path between concepts | `source`, `target` | path text | Read | Low | Allow with bounded hops |
| `list_prs` | GitHub PR inventory/impact | none | remote GitHub text | External network read | Medium: expands scope beyond local graph | Deny |
| `get_pr_impact` | PR file/graph impact | `pr_number` | remote GitHub and graph text | External network read | Medium: invokes authenticated `gh` | Deny |
| `triage_prs` | PR review prioritization | none | remote GitHub and graph text | External network read | High: governance-adjacent recommendations | Deny |

## Input-schema concern

Graphify injects optional `project_path` into every tool. This allows a caller
to select another local directory containing `graphify-out/graph.json`. Even
though the operation is a read, that authority is broader than TIM Manager
needs. A strict adapter must remove this field and hard-code:

`/Users/tim/Documents/TIM/tim/graphify-out/graph.json`

## State-change review

The seven core graph tools read the in-memory graph. `query_graph` can write an
optional plaintext query log only when Graphify query logging is explicitly
enabled; the future adapter must set `GRAPHIFY_QUERY_LOG_DISABLE=1`.

CLI queries can create a `graphify-out/cache/last_query_stamp`, but this is not
part of the MCP query handler. The three PR tools execute authenticated,
read-oriented GitHub commands and are excluded to keep the connection local.

No tool should be exposed directly. The required seven-tool allowlist, argument
filter, output bound, fixed graph path, and disabled query log require a
read-only adapter before TIM Manager use.
