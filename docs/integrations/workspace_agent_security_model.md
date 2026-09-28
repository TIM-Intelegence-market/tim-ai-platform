# Workspace Agent Gateway Security Model

The local gateway has two authorization layers: its eight-operation allowlist
and the existing TIM Manager Graphify client's seven-tool allowlist. It also
enforces explicit local client IDs, recent timestamps, unique request IDs,
replay protection, rate/concurrency/input/output/runtime limits, excluded
paths, result validation, graph-hash integrity, and secret-safe audit logging.

The client ID is local admission control, not cryptographic remote
authentication. Strong remote authentication and TLS must be supplied by an
OpenAI Secure MCP Tunnel and Workspace Custom MCP App. No token, tunnel,
listener, public endpoint, or external data transfer was created here.

Anonymous/unknown clients, stale timestamps, replay, unknown/write operations,
nested dispatch, excluded paths, oversized data, timeouts, downstream failure,
invalid provenance, graph-hash mismatch, and disabled read-only policy fail
closed.

Until an administrator/user creates and approves the Custom MCP App and Secure
MCP Tunnel, external authentication is **not active** and the real Workspace
Agent is **not connected**.
