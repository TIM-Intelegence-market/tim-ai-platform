# TIM GRAPH MCP — Runbook

## Build / refresh

```bash
cd <tim worktree>
.venv/bin/python -m src.graph_mcp.cli --root . \
    --vault "$TIM_OBSIDIAN_VAULT" refresh-all
```

Vault path: `--vault`, else `TIM_OBSIDIAN_VAULT`, else the legacy
`TIM_GRAPH_MCP_VAULT`; without any of them the graph runs vaultless.
Template folders (`99 Vorlagen`, `Templates`) are not indexed.

`refresh-all` = refresh-code (incremental, content-hash skip) +
refresh-docs (Obsidian/recipes/agents) + refresh-runtime-readonly
(services + DB schema). Expected on unchanged tree: `FILES_SCANNED=0`,
all add/update/remove counters 0.

## Inspect

```bash
.venv/bin/python -m src.graph_mcp.cli --root . stats
.venv/bin/python -m src.graph_mcp.cli --root . query search "CandleAggregator"
.venv/bin/python -m src.graph_mcp.cli --root . query impact "class:src/data_ingestion/aggregator.py:CandleAggregator"
```

## Run the MCP server

```bash
TIM_GRAPH_MCP_ROOT=. TIM_OBSIDIAN_VAULT="$TIM_OBSIDIAN_VAULT" \
  .venv/bin/python -m src.graph_mcp.mcp_server
```

Client registration name (distinct from `serena`/`graphify`):
`tim-graph`.

## Acceptance probes

```bash
.venv/bin/python scripts/graph_mcp_protocol_probe.py     # MCP stdio protocol
.unlazy/graph-mcp/gate-check --reverify                  # 14-gate ledger
.unlazy/graph-mcp/gate-check --status
```

## Export / Graphify handoff

```bash
.venv/bin/python -m src.graph_mcp.cli --root . export --out .runtime/graph/exports
graphify explain "CandleAggregator" --graph .runtime/graph/exports/tim-graph.graphify
graphify diagnose multigraph --graph .runtime/graph/exports/tim-graph.graphify
```

The Graphify projection lives only in the export adapter
(`relation`/`confidence`/`source_file`); the canonical schema is
unchanged.

## Known honest gaps

- Bugfixer recipes and `src/bugfixer` are absent at branch base
  `bdad847` (untracked Phase-E1 work in the main checkout) — the recipe
  indexer activates when those files land in this branch.
- 21 Service nodes are legitimately isolated (leaf packages with no
  internal imports); no relationships were invented for them.
