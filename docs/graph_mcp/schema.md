# TIM GRAPH MCP — Graph Schema

Schema version 1.0.0 (`SCHEMA_VERSION` in `src/graph_mcp/__init__.py`).

## Stable identities

Deterministic, no random UUIDs. Path-unfriendly characters are
percent-encoded (stable across runs):

```
file:src/data_ingestion/aggregator.py
module:src.data_ingestion.aggregator
class:src/data_ingestion/aggregator.py:CandleAggregator
method:src/data_ingestion/aggregator.py:CandleAggregator.add_trade
function:src/x.py:foo
test:tests/test_x.py:test_behavior
table:tim:candles            column:tim:candles:open_time
service:data_ingestion
mission:TIM/30%20Missions/LONG%20History%20Extension%20Design.md
gate:TIM/50%20Data%20%26%20QA/LONG%20Readiness.md
incident:TIM/20%20Incidents/Observation%20Input%20Hash%20Head%20Blocker%202026-09-17.md
recipe:STALE_CLOSE_REBUILD_V1:1.0.0
agent:qwen                   tool:context-mode
github:issue:12              github:commit:abcdef123456
note:TIM/00%20HOME/TIM%20Home.md
```

## Node types (18)

Repository, Directory, File, Module, Class, Function, Method, Test,
Database, Table, Column, Service, Process, Mission, Gate, Incident,
ErrorFingerprint, RepairRecipe, Agent, Tool, GitHubIssue, GitCommit,
Decision, ObsidianNote.

## Edge types

CONTAINS, IMPORTS, CALLS, DEFINES, TESTS, READS, WRITES, DEPENDS_ON,
IMPLEMENTS, VERIFIES, BLOCKS, UNBLOCKS, REQUIRES, CAUSED_BY,
REPAIRED_BY, REPRODUCED_BY, VALIDATED_BY, ASSIGNED_TO, USES_TOOL,
RELATED_TO, DOCUMENTED_BY, SUPERSEDES, REFERENCES, PARENT_OF, CHILD_OF.

## Canonical records

Node: `{id, type, name, source, path, metadata, content_hash,
observed_at, schema_version}` — `content_hash` covers identity-relevant
content only, so unchanged nodes keep their first `observed_at`
(idempotency).

Edge: `{from, to, type, metadata, evidence[], schema_version}`.
Semantic edge classes (READS, WRITES, CALLS, TESTS, IMPLEMENTS,
VERIFIES, BLOCKS, UNBLOCKS, CAUSED_BY, REPAIRED_BY, REPRODUCED_BY,
VALIDATED_BY, ASSIGNED_TO, SUPERSEDES) **require evidence** — the Edge
constructor refuses to build them without it. Resolution metadata
carries `resolution_method` and `confidence` (CALLS 0.6 same-file,
TESTS 0.7 filename convention / 0.9 explicit import, READS/WRITES 0.9
SQL-string match).

## Determinism material

`node_set_hash` = sha256 over sorted `id|type|content_hash`;
`edge_set_hash` = sha256 over sorted `from|to|type|metadata`
(`graph_stats`, `GraphStore.set_hashes`). Same repo state twice ->
identical hashes (verified on the real repository).
