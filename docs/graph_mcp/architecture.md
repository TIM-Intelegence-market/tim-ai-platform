# TIM GRAPH MCP — Architecture

Status: implemented on branch `glm/tim-graph-mcp` (base `bdad847`).
Schema version 1.0.0. Server name `tim-graph-mcp`.

## What it is — and is not

**TIM GRAPH MCP** is TIM's machine-readable, deterministic relationship
graph and query interface: code, database schema, runtime services,
missions, gates, incidents, repair recipes, agents/tools, GitHub
artifacts, decisions, and Obsidian note metadata.

It is **not** a visualization layer and **not** a semantic code
navigator. Clear separation of roles:

| Layer | Role |
|---|---|
| **TIM GRAPH MCP** | canonical structured graph + bounded query tools (this package) |
| **Graphify** | existing codegraph/visualization/review layer (`src/tim_manager/graphify_mcp.py`, `~/.local/bin/graphify`); consumes graph exports |
| **Obsidian** | canonical human-readable verified knowledge (vault); Graph MCP reads metadata only, never rewrites the vault |
| native grep/AST | repository navigation |

## Components

```
src/graph_mcp/
  schema.py        node/edge types, stable percent-encoded IDs, record
                   contracts, node/edge set hashes, evidence enforcement
  store.py         SQLite (WAL) diff-based apply, retire, SQL-side search
  redaction.py     secret patterns — nothing credential-like is stored
  indexer/
    code.py        AST: File/Module/Class/Method/Function/Test, IMPORTS,
                   TESTS (labeled confidence), CALLS (same-file symbol
                   table, low-confidence label)
    database.py    schema.sql -> Database/Table/Column + REFERENCES;
                   MODULE READS/WRITES TABLE with file:line evidence
    runtime.py     Service nodes from the internal import graph
                   (discovery=code_imports; wired_via=main.py or internal)
    obsidian.py    vault frontmatter -> Mission/Gate/Incident/Decision/
                   ObsidianNote + wikilink REFERENCES + DOCUMENTED_BY;
                   RecipeIndexer for schemas/bugfixer/recipes/*.json
    agents.py      Agent/Tool nodes from the KI TOOLS datapacket +
                   locally verified availability only (port/binary checks)
    github.py      offline provider-payload adapter (no credentials)
  service.py       refresh orchestration (incremental, content-hash),
                   search/neighbors/path/dependencies/impact + context
                   builders; every traversal depth- and size-bounded
  export.py        canonical JSON + Mermaid + DOT + GraphML + Graphify
                   projection (relation/confidence/source_file live ONLY
                   in the Graphify adapter)
  mcp_server.py    line-delimited JSON-RPC 2.0 over stdio, 18 tools,
                   server-side inputSchema enforcement, structured errors
  cli.py           refresh/query/export entry points
```

## Data flow

indexers -> (redaction) -> GraphStore.apply (diff, idempotent)
queries read the store only. The store at `.runtime/graph/graph.sqlite`
is the single writable surface of this package (git-ignored).

## Invariants

- deterministic: same repository state -> identical node/edge set hashes
- idempotent: unchanged second refresh adds/updates/removes nothing
- bounded: search <= 200 rows, traversal depth <= 8 (default 4)
- honest: impact is labeled `STATIC_GRAPH_IMPACT`; unresolved relations
  are skipped, never guessed; every semantic edge carries evidence
