# Architecture

TIM-IM uses a small ports-and-adapters design:

1. JSON-compatible YAML source and policy registries.
2. Read-only filesystem and Git adapters.
3. An incremental deterministic scanner.
4. Stable UUIDv5 artifact and event identifiers.
5. SHA-256 content fingerprints.
6. Isolated SQLite/FTS5 metadata storage.
7. Append-only JSONL project events.
8. Portable JSON project snapshots.
9. Reports, CLI, deterministic queries and an MCP surface without exposed
   mutation tools; the isolated SQLite index boundary is documented separately.

Generated summaries are not promoted to primary evidence. Runtime timestamps are
excluded from the deterministic snapshot hash.
