# Workspace Agent Graphify Gateway Architecture

The implementation adds a local, disabled-by-default, line-oriented MCP stdio
adapter. It does not expose a network listener and does not connect the
published Workspace Agent.

```text
future OpenAI Secure MCP Tunnel / Custom MCP App
  -> WorkspaceGateway (stdio, read-only, fail-closed)
  -> GraphifyReadOnlyClient (second allowlist)
  -> local Graphify MCP server
  -> immutable local codegraph
```

The gateway publishes eight named operations. There is no generic dispatch:
search, node, neighbors, community, statistics, shortest path, central nodes,
and health. They map onto the existing seven Graphify read operations.

Controls include exact contracts, explicit client allowlisting, timestamp and
replay checks, per-client rate limit, bounded concurrency/sizes/runtime,
excluded-path rejection, downstream provenance and graph-hash validation, and
stderr-only structured audit events with hashed client references. There are
no filesystem, Git, governance, trading, indexing, or write operations.

The checked-in configuration is disabled and contains no host, port, token,
certificate, or secret. A local ignored configuration is required to enable it.
