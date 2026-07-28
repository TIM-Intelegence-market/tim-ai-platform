# TIM v1 Pre-Unfreeze Backup and Restore Report

## Result

**PASS**

The controlled-unfreeze audit did not enter write mode until the backup and isolated restore checks completed successfully.

## Backup identity

- Backup ID: `tim_v1_pre_unfreeze_20260727T170226Z`
- Created at: 2026-07-27T17:02:26Z
- Source: `/Users/tim/Documents/TIM/tim`
- Backup: `/Users/tim/Documents/TIM/backups/tim_v1_pre_unfreeze_20260727T170226Z`
- Manifest: `/Users/tim/Documents/TIM/backups/tim_v1_pre_unfreeze_20260727T170226Z/backup_manifest.json`
- Backed-up files: 247
- Backup size: 48 MB
- Canonical inventory SHA-256: `9e817d14f23f44aa70a0d355e7d62b391a24d4d7f97318a4da6f985e0d312dad`

The backup contains project source, configuration, schemas, tests, documentation, research artifacts, operational metadata and current data files. No historical TIM artifact was rewritten.

## Exclusions

The following regenerable local files were excluded:

- `.venv/`
- `.venv-research/`
- Python bytecode and `__pycache__`
- `.pytest_cache/`
- editor swap files
- `.DS_Store`

Dependency declarations `requirements.txt` and `requirements-research.txt` are included.

## Git state

`git rev-parse --show-toplevel` resolves to `/Users/tim`, not to the TIM project. TIM is not tracked as a dedicated repository at the audited path. Creating an audit branch in the home-level repository would change unrelated user state and was therefore not performed.

The enclosing repository context recorded at backup time was:

- branch: `main`
- commit: `a418894d33ba2426afe0f31d119332043bddd406`

This commit must not be interpreted as a dedicated TIM source revision. File-level SHA-256 values in the backup manifest are the authoritative baseline.

## Restore test

The backup was restored into:

`/tmp/tim_v1_restore.2Stdd1`

Checks:

| Check | Result |
|---|---|
| Expected files present | PASS — 247/247 |
| Unexpected files | PASS — 0 |
| Per-file SHA-256 | PASS — 247/247 |
| Project structure | PASS |
| `main` import | PASS |
| Dashboard import | PASS |
| Candle aggregator import | PASS |
| Orderflow metrics import | PASS |
| Pytest collection | PASS — 172 tests |

The original audited Python environment was used only to validate imports and collect tests from the isolated restored source. No test wrote into the live project.

## Restore instructions

1. Create an isolated destination.
2. Copy the contents of the backup `project/` directory into it.
3. Verify every file against `files_backed_up` in `backup_manifest.json`.
4. Recreate the main environment from `requirements.txt`.
5. Recreate the research environment from `requirements-research.txt`.
6. Import the central modules.
7. Run `python -m pytest --collect-only`.
8. Run the full test suite before using the restored version.

## Conclusion

The pre-unfreeze baseline is readable, hash-verifiable and restorable. Controlled audit writes may proceed. Scientific behavior changes remain prohibited until separately documented and compared.
