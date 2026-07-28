# TIM V2 Dataset Platform - final acceptance

Status: PASS

## Scope and protection boundary

Reviewed branch: `codex/dataset-platform`.
Implementation baseline: `29ae2edc36ccdae4e665a04c1fcf88eb390a84fe`.
The branch diff is limited to `src/tim_v2/`, its Dataset tests, the V2 dataset
schema and Dataset implementation/acceptance documentation. No TIM-IM V1,
Foundation document, historical/raw data, Trading, Research, Knowledge,
Feature, release tag, secret or global-agent file is in the diff.

## Architecture

The platform is an in-memory metadata registry. It never opens a source URI,
reads raw bytes, copies data or performs network I/O. Dataset versions are
frozen dataclasses. Registration is idempotent for identical canonical manifests
and rejects a changed manifest with the same dataset-version key. Invalid
metadata remains registered as `QUARANTINED` with explicit issue codes.

## Acceptance matrix

| Requirement | Evidence | Result |
|---|---|---|
| Immutability, supersession, lineage, quarantine, quality and time checks | `tests/test_tim_v2_dataset_registry.py` | PASS |
| Deterministic / field-order / whitespace-independent hash | same test file | PASS |
| Semantic change changes hash; unchanged repeat is idempotent | same test file | PASS |
| Invalid JSON and unknown fields rejected | same test file | PASS |
| File/symlink-style URI and traversal rejected without opening it | same test file | PASS |
| Strict schema JSON syntax | `python -m json.tool schemas/tim_v2/dataset_manifest.schema.json` | PASS |
| Doctor | `python -m src.tim_manager.cli doctor` | PASS, exit 0 |
| Validate | `python -m src.tim_manager.cli validate` | PASS, exit 0 |
| Protected-path diff | `git diff --name-only main...HEAD` | PASS; Dataset files only |

## Executed commands and results

- `.venv/bin/python -m pytest -q tests/test_tim_v2_dataset_registry.py`:
  exit 0; 14 passed; 1 `pytest-asyncio` deprecation warning; 0 skips/XFAIL.
- `.venv/bin/python -m json.tool schemas/tim_v2/dataset_manifest.schema.json`:
  exit 0.
- `.venv/bin/python -m src.tim_manager.cli doctor`: exit 0; status PASS.
- `.venv/bin/python -m src.tim_manager.cli validate`: exit 0; status PASS.

## Determinism evidence

Tests perform two identical registrations and obtain the same manifest object
and SHA-256. Canonical JSON hashing gives equal SHA-256 for semantically
identical manifests with different field order and whitespace. A semantic
version change produces a different hash. The registry has no event stream;
the second identical registration does not create a second entry.

## Known warning and remediation

The targeted test run emits one existing `pytest-asyncio` deprecation warning
about `asyncio.get_event_loop_policy` under Python 3.14.6.

The controlled runner `scripts/run_full_test_suite.py` records stdout, stderr,
JUnit XML and JSON summary in `artifacts/test_reports/`. The full suite completed
with exit code 0: 251 passed, 0 failed, 0 skipped, 0 XFAIL/XPASS, 3 warnings and
34.276 seconds. Its JSON summary has `complete: true`.

The earlier incomplete runs were an execution-interface capture limitation for
long foreground commands, not a demonstrated pytest hang. A persistent PTY
session allowed the same runner to finish normally. No functional failure is
attributed to the Dataset Platform.

## Final decision

PASS. The required controlled full-suite evidence, targeted Dataset evidence,
Doctor/Validate checks and protected-scope evidence are complete. No further
platform work is authorized by this report.
