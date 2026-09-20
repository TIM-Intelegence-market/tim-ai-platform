# TIM GRAPH MCP — Security

## Boundary

`READ_ONLY_TIM=YES` by construction. The only writable surface of this
package is its own SQLite index (`.runtime/graph/graph.sqlite`,
git-ignored) plus its export directory. There is no code path that
writes to any TIM database, the runtime process, queues, the outbox, or
the Obsidian vault (the vault indexer reads frontmatter only).

## Forbidden and enforced

- Production DB mutation / DDL: no connection code exists; the database
  indexer parses `src/database/schema.sql` from the repository file.
- TIM runtime restart, queue/outbox mutation: no such tool is exposed.
- Git mutation: none; refresh tools only touch the graph store.
- Trading/orders: none.

## Secret hygiene

`src/graph_mcp/redaction.py` runs over every node's metadata before it
reaches the store (ghp_/github_pat_/sk-/Bearer tokens, 64-hex key
material, `password|secret|token|api_key[:=]` assignments, secret-named
keys). Verified: the real store contains no secret markers. Obsidian
bodies are never indexed — frontmatter fields only, from an allowlist.

## Query safety

- Search is parameterized SQL (`?` binding); SQL-looking input can only
  ever be search text. Bounded to 200 rows, deterministic order.
- Traversal depth capped at 8 (default 4); neighbor/result limits capped
  at 200 — no runaway traversals.
- MCP inputSchema is enforced server-side; invalid input is a
  structured error. Internal exceptions surface as
  `-32603 internal error: <TypeName>` — no tracebacks, no paths.
