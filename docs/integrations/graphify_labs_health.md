# TIM: Integration Health — Graphify Labs

**Phase 2A — Integration Health (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Live health query

- **Attempt**: `POST health_check` to the Graphify gateway.
- **Result**: **NOT PERFORMED (gateway disabled)** — `graphify_gateway.yaml`
  has `enabled: false`; transport requires `secure_mcp_tunnel_required`
  authentication and `allowed_clients: []`.
- **Consequence**: no live Graphify round-trip is possible without first
  enabling the gateway and provisioning an approved MCP tunnel client.
- **Status code classification**: `GATEWAY_DISABLED` (not an error in TIM;
  an expected read-only posture).

## Config snapshot (evidence)

| Key | Value |
|---|---|
| `enabled` | `false` |
| `transport` | `stdio` |
| `authentication_mode` | `secure_mcp_tunnel_required` |
| `allowed_clients` | `[]` (empty) |
| `read_only` | `true` |
| `allowed_operations` | includes `health_check`, `search_repository_graph`, `get_graph_node` |
| `rate_limit_requests` | 20 / 60 s |

## Verification assets

- `scripts/integrations/graphify_semantic_canary.py` exists and is
  deterministic (no-repair evaluator), but requires a live gateway.
- Prior baseline docs under `docs/integrations/graphify_*.md` remain the
  source of truth for design and capability matrix.

## Recommendation

- Do **not** enable the gateway during the toolchain assignment (OBSERVE-only).
- Record Graphify health as **DEFERRED** until the secure MCP tunnel is
  approved and the gateway is enabled by an authorized operator.

Status: **HEALTH DEFERRED — GATEWAY DISABLED BY DESIGN**