# TIM OPS MCP

Read-only MCP server for TIM's runtime state (#152, packages M3 and M3b). Same
transport and conventions as `docs/graph_mcp/`: stdio, line-delimited
JSON-RPC 2.0, protocol `2025-11-25`, no SDK dependency, inputSchema
enforced server-side, no tracebacks in responses.

Client registration name: `tim-ops` (in `.mcp.json` next to `tim-graph`).
Codex and Claude Desktop: `docs/mcp_clients.md`.

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
| data_coverage | Postgres `candles`, `ingestion_gap_incidents` | `symbol` (default BTCUSDT), `timeframe` 1m/5m/15m/1h, `hours` <= 168; expected vs. observed closed candles, ratio vs. 0.95, missing ranges, open gap incidents |

## Configuration

```bash
export TIM_OPS_TASK_DB=/path/to/engine.db   # optional; without it task tools answer not_configured
export TIM_OPS_COVERAGE_DSN=<dsn of tim_ops_ro> # optional; without it data_coverage answers not_configured
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

- `data_coverage` reads only candle open times (no prices, volumes or
  trades) and open gap incidents; their free text is redacted. The window
  is the last `hours` up to now, so it carries no research signal.

## Data coverage: read-only database role

The DSN comes only from the environment (`TIM_OPS_COVERAGE_DSN`). Keep the
password out of the DSN and out of any client config: use `~/.pgpass`
(mode 600) or `PGPASSFILE`. The code adds three layers on top of the role:
`default_transaction_read_only=on` for the session, a `readonly`
repeatable-read transaction per call, and a check that refuses a session
which does not report `default_transaction_read_only = on` before any table
is read. In test context `src/database/safety.py` refuses any target other
than the isolated test database. Errors never contain the DSN.

The code alone is not the boundary. On the server, as an admin, once:

```sql
CREATE ROLE tim_ops_ro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE tim_ops_ro SET default_transaction_read_only = on;
GRANT CONNECT ON DATABASE tim TO tim_ops_ro;
GRANT USAGE ON SCHEMA public TO tim_ops_ro;
GRANT SELECT ON candles, ingestion_gap_incidents TO tim_ops_ro;
```

Acceptance on the server (deferred until it is back, not done yet):

- as `tim_ops_ro`: `DELETE FROM candles WHERE false` fails with
  `permission denied`, `SELECT 1 FROM agg_trades LIMIT 1` fails too;
- `data_coverage` over MCP answers `status: ok` for BTCUSDT 1m 24h.

## Tests

`tests/ops_mcp/test_coverage.py` fakes the connection for the contract and
runs one test against the isolated CI database
(`TIM_DURABLE_TEST_DATABASE_URL`): real coverage numbers and a session that
rejects writes. It does not prove the server role.
