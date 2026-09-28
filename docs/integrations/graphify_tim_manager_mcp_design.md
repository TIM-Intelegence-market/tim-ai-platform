# TIM Manager Graphify MCP Integration Design

Date: 2026-07-29

Status: **DESIGN ONLY — IMPLEMENTATION STOPPED**

## Discovery result

TIM Manager has an MCP **server**, not an MCP client.

Documented configuration contains:

- `src/tim_manager/mcp_server.py`: six TIM Manager read-oriented server tools;
- `src.tim_manager.cli serve-mcp`: stdio server startup;
- `docs/tim_manager/mcp_integration.md`: example configuration for external
  Claude/OpenCode clients;
- no MCP client library, client lifecycle, server registry, transport client,
  timeout policy, or remote-tool allowlist.

The existing document explicitly states that no actual external client or
ChatGPT workspace connection is configured. Therefore a Graphify connection
cannot be added by editing an existing client configuration. The master prompt
requires Gate 2 implementation to stop here rather than fabricate a path.

## Required future architecture

A separately approved adapter outside frozen TIM-IM V1 should:

1. launch Graphify over stdio with an explicit executable and graph path;
2. expose server identity `tim-graphify-readonly`;
3. advertise only seven local graph tools;
4. remove `project_path` from every input schema and request;
5. reject the three GitHub PR tools;
6. set `GRAPHIFY_QUERY_LOG_DISABLE=1`;
7. use an explicit working directory;
8. enforce startup, request, and shutdown timeouts;
9. cap result size, traversal depth, token budget, community size, hop count,
   and god-node count;
10. quote outputs as untrusted retrieval with source provenance;
11. never execute retrieved commands;
12. maintain no repository, branch, trading, or governance write capability.

Suggested command after implementation review:

```text
/Users/tim/.local/bin/graphify-mcp
/Users/tim/Documents/TIM/tim/graphify-out/graph.json
```

Suggested environment:

```text
GRAPHIFY_QUERY_LOG_DISABLE=1
```

No shell interpolation is permitted. The executable, graph, and working
directory must be passed as fixed argument-array values.

## Backup and rollback

There is no current TIM Manager client configuration to back up. A future
implementation must create a new, versioned configuration rather than
overwriting the existing TIM Manager MCP server example. Rollback removes the
new adapter/config and leaves TIM-IM V1 unchanged.

## Approval boundary

Implementing this design introduces a new client layer and therefore is feature
development beyond the present protected integration task. It needs explicit
architecture approval and tests before any TIM Manager attachment.
