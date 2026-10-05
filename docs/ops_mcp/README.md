# TIM OPS MCP

Read-only MCP server for TIM's runtime state (#152, package M3). Same
transport and conventions as `docs/graph_mcp/`: stdio, line-delimited
JSON-RPC 2.0, protocol `2025-11-25`, no SDK dependency, inputSchema
enforced server-side, no tracebacks in responses.

Client registration name: `tim-ops` (in `.mcp.json` next to `tim-graph`).

## Tools

| Tool | Source | Notes |
|---|---|---|
| ops_health | server | which sources are configured |
| task_summary | Task Engine | counts by state, `open` = not FIXED/FAILED |
| task_list | Task Engine | filter `state`, `type`; `limit` <= 200, `truncated` flag |
| task_get | Task Engine | task + transitions, evidence, checkpoints |
| tool_health | `src/agent_infra/health.py` | Serena, graph, Obsidian, Ollama, Qwen, ... |
| research_register | `docs/research_lab/REGISTER.jsonl` | hash chain verified, m, statuses, candidates |
| research_reports | `docs/research_lab/reports/` | committed report files |
| research_report | one report | per-variant train/validation trades, expectancy_r, drawdown, p |

## Configuration

```bash
export TIM_OPS_TASK_DB=/path/to/engine.db   # optional; without it task tools answer not_configured
export TIM_OPS_MCP_ROOT=<tim worktree>       # default: current directory
python -m src.ops_mcp.mcp_server
```

## Read-only boundary

- The Task Engine file is opened with a `mode=ro` URI and `PRAGMA query_only`,
  never through `SqliteTaskRepository` (its constructor creates the schema
  and chmods the file). Symlinks, foreign SQLite files and other schema
  versions are refused. A test proves the file's bytes are unchanged after
  every tool and that the connection rejects writes.
- Free-text task fields pass through `src/graph_mcp/redaction.py`.
- Report names are resolved inside `docs/research_lab/reports/`; anything
  else is `not_found`.
- A static test fails if the package gains SQL writes, file writes or Task
  Engine mutators.
- Holdout data is never read; the register is only verified, not appended.

## Not yet covered

Data coverage gaps live in Postgres. They need a technically read-only DB
role whose credentials come from the environment only; that is a separate
step, not part of this server yet.
