# TIM Agent Context Preflight V1 + Context Packs

`src/agent_infra/preflight.py` / `packs.py`.
Version TIM_AGENT_CONTEXT_PREFLIGHT_V1.

## Flow (before substantial coding work)

1. mission -> Graph MCP mission context
2. component -> Serena symbol lookup (scoped read-only instance)
3. references/tests -> Serena
4. cross-system impact -> Graph MCP (STATIC_GRAPH_IMPACT)
5. historical decisions -> Graph MCP Decision nodes (Obsidian-indexed)
6. tool health -> ToolHealthRegistry gates every step
7. bounded AgentContextPack -> worker -> implement -> verify ->
   Graph MCP refresh after approved changes

## AgentContextPack

mission · gates · blockers · symbols (with canonical graph IDs) ·
references · tests · incidents · impact · decisions · docs ·
tool_status · safety_constraints · source_provenance · truncated flags.
No repository dumps, no vault dumps, no secret paths — enforced by
test (`test_pack_excludes_secret_paths`).

## Context budget (TIM_CONTEXT_BUDGET_V1, hard-enforced)

symbols<=10 · references<=20 · tests<=10 · graph_neighbors<=50 ·
graph_depth<=4 · notes<=5 · incidents<=5 · serialized pack<=24000
chars (optional sections drop first; impossible packs raise loudly).
CONTEXT_BUDGET_ENFORCED=YES is the acceptance criterion.

## Measured efficiency sample (2026-09-18, honest)

Representative task "CandleAggregator context": native (full file +
grep) 32 files / 8,332 chars / 0.35 s; routed cold 16 files / 13,652
chars / 3.8 s; routed warm (same Serena instance) 0.41 s.
**No token-savings claim** — routed context is structured and
hard-bounded (independent of repo growth), but did not outperform
native retrieval in raw chars on this sample.

## RepairContextPack (Mission 09.2 foundation)

incident · fingerprint · classification · affected_graph_nodes ·
affected_symbols · tests · prior_repairs (empty list = legitimate) ·
mission_gates · safety_constraints. Data contract only — NO repair
automation here. Future self-healing flow (documented target):
Incident -> Graph MCP -> Serena -> Obsidian -> AgentContextPack ->
Qwen -> OpenCode/GLM -> tests -> gates -> evidence -> Graph MCP refresh.
No unrestricted self-modification.
