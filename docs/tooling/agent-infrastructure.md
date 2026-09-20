# TIM Agent Infrastructure V1

One coherent layer (branch `glm/agent-infrastructure-v1`, base 7836ce6
= Graph MCP commit dependency), not isolated tools:

```
ChatGPT (coordination/QC)
  └─ TIM_AGENT_CONTEXT_PREFLIGHT_V1
       └─ TIM_TOOL_ROUTER_V1
            ├─ Serena            semantic code intelligence
            ├─ TIM Graph MCP     relationships/missions/incidents/impact
            ├─ Obsidian          verified knowledge (bounded retrieval)
            └─ Graphify          visualization
                 ├─ OpenCode / GLM   implementation (isolated worktrees)
                 └─ Qwen             bounded review (qwen2.5:7b)
                      └─ Bugfixer / Self-Healing (foundation: RepairContextPack)
```

## Components (src/agent_infra/)

serena_client (scoped stdio MCP client), bridge (Serena -> canonical
Graph IDs; '/' nesting -> '.'), router + health (deterministic routing,
evidence-based availability), packs (AgentContextPack,
RepairContextPack, hard budget), preflight (orchestration), profiles
(OpenCode/GLM/Qwen). Graph context via `src.graph_mcp` (unchanged
conventions; only `AgentIndexer` gained evidenced Serena relations +
`dependents()` now includes DEFINES).

## Verified evidence (2026-09-18)

- Serena 2.0.0.dev0 running; TIM registered (control + tim + worktree)
- Real acceptance: CandleAggregator (class/3 methods/44 refs/tests) and
  DurableOutboxWorker (class/recover_one/19 refs/tests) via Serena;
  bridge into Graph MCP (canonical IDs, neighbors, 30 TESTS edges, impact)
- Router deterministic; fallback matrix verified; honest BLOCKED
- LONG context preflight PASS (Graph-MCP-first, pack 2,076 chars,
  routing only — LONG E2 untouched)
- Controlled Serena edit in isolated worktree: test PASS, diff exact
- Qwen review (qwen2.5:7b, six-heading contract) + GLM adjudication:
  4 accepted (already test-covered), 2 deferred, 1 rejected-with-evidence
- 85/85 tests, 18/18 ledger gates, production mutations 0

## Security / write authority

Production read-only/out of scope; writes only inside the isolated
mission worktree; router grants no authority (profiles do, separately);
secret paths (.env, keys, tokens, credential files, serena dashboard
auth_secret) excluded from packs/graph/docs/commits (scan EXPOSED=NO).
