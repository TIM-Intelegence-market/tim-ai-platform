# TIM Tool Router V1 + Tool Health Registry

`src/agent_infra/router.py` (+ `health.py`). Version TIM_TOOL_ROUTER_V1.

## Canonical routes

| Intent | Primary | Secondary | Fallback |
|---|---|---|---|
| symbol definition / references / tests | Serena | TIMGraphMCP | NativeSearch |
| mission / incident / impact | TIMGraphMCP | Obsidian | — |
| past decision | Obsidian | TIMGraphMCP | — |
| visualization | Graphify | TIMGraphMCP | — |
| implementation | OpenCode | GLM | — |
| review | Qwen | — | — |
| code search | NativeSearch | Serena | — |

Deterministic: same `ContextRequest` + same availability map -> byte-
identical decision hash (test-proven). Primary unavailable -> first
available secondary/fallback with an explicit reason; nothing available
-> honest BLOCKED. **No fallback ever impersonates the primary.**
The router selects CONTEXT TOOLS only — it grants no write authority
(`ROUTER_GRANTS_WRITE_AUTHORITY=NO`); authority lives in agent profiles.

## ToolHealthRegistry

Probes (read-only, evidence + observed_at each): Serena (process),
TIMGraphMCP (store readable + node count), Graphify (binary), Obsidian
(vault), Ollama (port + model list), Qwen (**qwen2.5:7b specifically** —
another model is never silently labeled Qwen), NativeSearch (rg/grep),
pytest (platform venv). Probe failures fail closed to UNKNOWN.
Availability is refreshed at query time — no stale AVAILABLE claims.

## Fallback matrix (verified)

SERENA_UNAVAILABLE -> TIMGraphMCP (or NativeSearch for pure search);
SERENA_PROJECT_MISSING -> explicit degraded/unavailable status;
AMBIGUOUS_SYMBOL -> deterministic first hit + bounded rest;
MISSING_SYMBOL -> explicit no-match blocker; GRAPH_MCP_UNAVAILABLE ->
available secondary or BLOCKED; OBSIDIAN_UNAVAILABLE -> historical
context unavailable; QWEN_UNAVAILABLE -> review omitted honestly;
QWEN_AVAILABLE -> bounded qwen2.5:7b review.
