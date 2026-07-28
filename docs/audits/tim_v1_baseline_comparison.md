# TIM v1 Baseline Comparison

Baseline: external backup captured before audit at `2026-07-27T17:02:26Z`.

## Comparison

- Backup inventory: 247 files, canonical inventory SHA-256 `9e817d14f23f44aa70a0d355e7d62b391a24d4d7f97318a4da6f985e0d312dad`.
- Restore: 247/247 hashes matched; imports passed; 172 baseline tests collected.
- Scientific runtime files remained byte-identical during this audit. No database, schema, rule, metric, threshold, manifest, snapshot or persisted record was modified.
- Added files are audit-only documentation, artifacts, one standalone read-only audit runner and its tests.
- Pipeline run: 10/10 canonical outputs identical.

## Compatibility

The sole execution-environment defect is a stale shebang in `.venv/bin/pytest` referencing the former project path. The interpreter and package environment work through `.venv/bin/python -m pytest`; scientific outputs are unaffected.

## Decision

No regression from the captured TIM v1 baseline was detected.
