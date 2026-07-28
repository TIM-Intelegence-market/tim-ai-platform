# TIM-IM Final Verification Probe Results — S11 Remediation

Execution date: 2026-07-28  
Project root: `/Users/tim/Documents/TIM/tim`  
Probe script:
`artifacts/tim_manager/reports/final_verification_probes.py`  
Probe script SHA-256:
`89f87e626d34565066c63f523cadea817ecc8b89c2f6f0cc1d754ceffc0f4815`

This file persists the command outputs captured after the isolated S11
remediation. Volatile protected-file values are time-specific observations.

## Targeted S11 verification

Command:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager/test_mandatory_acceptance.py::test_s11_conflicting_sources_are_visible tests/tim_manager/test_contradictions.py
```

Exit code: `0`

```text
14 passed, 1 warning in 0.09s
```

## Mandatory acceptance

Command:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager/test_mandatory_acceptance.py --junitxml=artifacts/tim_manager/reports/mandatory_acceptance.junit.xml
```

Exit code: `0`

```text
20 passed, 1 warning in 0.84s
JUnit: tests=20 failures=0 errors=0 skipped=0
JUnit SHA-256: 464aca8ed5a9d8be5312ceb52bd61a1ee504f016683f304d48ad66f7ac52b3c5
```

## Full regression

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager
```

Exit code: `0`

```text
58 passed, 1 warning in 20.36s
```

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

Exit code: `0`

```text
237 passed, 145 warnings in 28.95s
```

## Doctor and Validate

Commands:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli doctor
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli validate
```

Exit codes: `0`, `0`

Both returned status `PASS`; config, project root, storage parent, protected
write check, snapshot and MCP were true, and external models were
`optional_disabled`.

## Stabilization and unchanged follow-up scans

Command, executed three times:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli scan
```

```text
90e98a54-b75e-5d6c-9dbc-9eecc7e53692
new=0 changed=0 deleted=0 moved=0 unchanged=234 parser_errors=0
snapshot_id=43312fa2-a863-5f56-9765-0d7a224239be

c681f93f-ff81-5df9-a426-ec785b58f7d0
new=0 changed=0 deleted=0 moved=0 unchanged=234 parser_errors=0
snapshot_id=43312fa2-a863-5f56-9765-0d7a224239be

148146d3-4ed2-5897-b1f7-f5b562adf70e
new=0 changed=0 deleted=0 moved=0 unchanged=234 parser_errors=0
snapshot_id=43312fa2-a863-5f56-9765-0d7a224239be
```

The stabilization scan persisted snapshot schema `1.1` without a source
change. Both immediately following scans were unchanged and retained one
snapshot ID.

## Snapshot schema and byte hashes

Commands:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli export --output artifacts/tim_manager/reports/final_acceptance_snapshot_export.json
shasum -a 256 artifacts/tim_manager/snapshots/current.json artifacts/tim_manager/snapshots/43312fa2-a863-5f56-9765-0d7a224239be.json artifacts/tim_manager/reports/final_acceptance_snapshot_export.json
PYTHONDONTWRITEBYTECODE=1 .venv-research/bin/python artifacts/tim_manager/reports/final_verification_probes.py schema
```

Exit codes: `0`, `0`, `0`

```text
JSONSCHEMA_VERSION	4.26.0
VALIDATED_FILES	3
LEGACY_SCHEMA_1_0_VALID	True
SHA256	73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d,73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d,73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d
IDENTICAL	True
```

The current snapshot, versioned snapshot and export are byte-identical.

## Protected baseline and policy

Command:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py protected
```

Exit code: `0`

```text
CHANGED	data/operational/runtime_launchd.err.log	94dd9b19c191daf65586a1469400b815f2b5e2bbe6820b6cbb1a360f4f574050	364a938fcc3832e7dc74ef8e10253242866f68eb089548e9f9cd77c7234af8a8	7187798	2026-07-28T09:41:02.822974+00:00
CHANGED	data/research/module_a_cache.jsonl	e3ca84f1b4b414acf222ce70d01ddfc79d953ed3d3a77d707097d96f17783b28	cdec7b8f68fd26b6bb6b18ea212ceffb1b41e8257e80c7aee76571b8c964a7db	4061891	2026-07-28T09:41:02.813359+00:00
CHANGED	data/research/trigger_events.jsonl	1ecfb8e9847d75092d59495fbba6c934835f5ca9c0530060e4b74ea499690031	85809cf63b0abbd1a93dcb6f091f8494c4e6de73ec0e23d0102983e7191bcd4a	1750589	2026-07-28T09:41:02.817146+00:00
CHANGED	data/research/trigger_state.json	fe4e5c8cd21fa69a6af1bf6bb9d7870c76a6bafb2329a31e7eb6564bc4c6020e	ad8ca1aa2ec7ebea6a25b2646631d970891f5aa08b2841f64b27c1063e5ed41d	466132	2026-07-28T09:41:02.816287+00:00
DENIED	data/operational/runtime_launchd.err.log	protected TIM V1 path: data/operational/runtime_launchd.err.log
DENIED	data/research/module_a_cache.jsonl	protected TIM V1 path: data/research/module_a_cache.jsonl
DENIED	data/research/trigger_events.jsonl	protected TIM V1 path: data/research/trigger_events.jsonl
DENIED	data/research/trigger_state.json	protected TIM V1 path: data/research/trigger_state.json
DENIED	artifacts/provenance/TIM-V1-UNFREEZE-20260727T170852Z.json	protected TIM V1 path: artifacts/provenance/TIM-V1-UNFREEZE-20260727T170852Z.json
SUMMARY	same=44	changed=4	missing=0	denied=5	probes=5
```

All 44 baseline-stable protected files remained hash-identical. The same four
previously classified volatile runtime files continued changing while the
pre-existing TIM runtime remained active. No TIM-IM write was observed.

## Local MCP protocol and boundaries

Command:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py mcp
```

Exit code: `0`

```text
SERVER_EXIT	0
RESPONSE_COUNT	11
TOOLS	tim_get_status,tim_get_module_status,tim_get_risks,tim_get_source_health,tim_search,tim_query
WRITE_CAPABILITIES	0
RESOURCE	tim://snapshot/current
WRITE_METHOD_ERROR	-32601
PROTECTED_BEFORE	413fef8c8794c618a805abb44a2d22ffa20834c88b5a983b3f03f54638da0d99
PROTECTED_AFTER	413fef8c8794c618a805abb44a2d22ffa20834c88b5a983b3f03f54638da0d99
PROTECTED_IDENTICAL	True
DATABASE_SHA256_BEFORE	bee655df0f3bb89342c74436a4992653e659e13daeaa45c50bef1de0633392f2
DATABASE_SHA256_AFTER	bee655df0f3bb89342c74436a4992653e659e13daeaa45c50bef1de0633392f2
DATABASE_STAT_IDENTICAL	True
```

## Git, active SQLite provenance and content manifest

Command:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py provenance
```

Exit code: `0`

```json
{
  "authoritative_git_repository": false,
  "content_manifest_hash": "22b258c5fd8eac5e4d3cff0ef648b96c1ce00665c6b11e58a7f5e2b491a10c1b",
  "parent_commit": "a418894d33ba2426afe0f31d119332043bddd406",
  "parent_git_root": "/Users/tim",
  "repository_commit": null,
  "repository_status": "unversioned",
  "reproduced_content_manifest_hash": "22b258c5fd8eac5e4d3cff0ef648b96c1ce00665c6b11e58a7f5e2b491a10c1b",
  "sqlite_artifact_count": 228,
  "sqlite_authoritative_true": 0,
  "sqlite_non_null_repository_commit": 0,
  "sqlite_parent_context": 228,
  "tim_dot_git": false,
  "tracked_tim_files": 0
}
```
