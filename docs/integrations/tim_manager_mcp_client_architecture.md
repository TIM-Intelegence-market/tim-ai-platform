# TIM Manager Graphify MCP Client Architecture

Date: 2026-07-29

## Existing architecture

TIM Manager is an isolated Python package under `src/tim_manager`. It uses
JSON-formatted versioned configuration in `config/tim_manager`, an `argparse`
CLI, filesystem and Git adapters, a deterministic query module, structured
security checks, and a line-oriented local MCP **server**. The normal runtime
has no MCP SDK dependency and there was no MCP client, client transport,
remote-tool policy, or retrieval result model.

## Minimal extension

`src/tim_manager/graphify_mcp.py` adds an optional ports-and-adapters boundary:

```text
TIM Manager CLI (explicit graphify command)
        |
        v
GraphifyReadOnlyClient
        | policy, bounds, provenance, integrity
        v
MCPClientPort
        |
        v
LocalStdioMCPClient
        |
        v
fixed local Graphify MCP process + fixed codegraph
```

The stdlib transport implements only the required MCP JSON-RPC handshake,
tool discovery, tool calls, bounded response reading, timeouts, and safe
shutdown. It does not add a package dependency. The client is disabled by
default and requires an explicit per-invocation CLI enable.

## Dependency direction

The existing scanner, canonical state, reporting, query layer, and MCP server
do not depend on Graphify. Only the new explicit CLI route imports the optional
client. Graphify results never enter TIM-IM snapshots or storage.

## Security boundaries

- fixed absolute executable, repository, and graph paths;
- `shell=False` and no shell interpolation;
- minimal child environment with query logging disabled;
- seven local graph tools allowlisted;
- all PR/network tools and unknown tools denied client-side;
- caller-controlled `project_path` denied;
- input, traversal, result, startup, request, and shutdown bounds;
- graph SHA-256 verified before each tool call;
- output redaction, validation, provenance, and untrusted classification;
- rejected calls produce structured security logs;
- retrieved commands remain text and cannot dispatch tools.

## Non-goals

This client does not provide semantic document indexing, a Workspace Agent
connection, canonical evidence, governance authority, Git authority, external
network retrieval, automatic querying, trading, capital, or execution
capability. It does not change the existing TIM Manager MCP server.
