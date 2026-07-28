# TIM-IM V1 Release Manifest

## Identity

| Field | Value |
|---|---|
| Release | `tim-im-v1.0.0` |
| Release type | technical baseline and architecture freeze |
| Repository root | `/Users/tim/Documents/TIM/tim` |
| Initial commit | `f1b267e650ace8fb4d50e01496ac50b593887e3f` |
| Branch | `main` |
| Tag | annotated `tim-im-v1.0.0` |
| Remote status | not configured |
| Tag resolution | `git rev-list -n 1 tim-im-v1.0.0` |

## Frozen TIM-IM acceptance identity

| Field | Value |
|---|---|
| Content manifest | `22b258c5fd8eac5e4d3cff0ef648b96c1ce00665c6b11e58a7f5e2b491a10c1b` |
| Snapshot ID | `43312fa2-a863-5f56-9765-0d7a224239be` |
| Snapshot SHA-256 | `73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d` |
| Schema version | `1.1` |
| Acceptance status | `PASS` |
| Mandatory scenarios | `20/20 PASS`, `0 XFAIL` |
| TIM-IM tests | `58 passed` |
| Full TIM tests | `237 passed` |
| Warnings | `145` existing pytest-asyncio deprecations |

## Repository policy

- `.gitignore` excludes runtime data, local databases, generated scans,
  historical artifact stores, outputs, caches and virtual environments.
- `.gitattributes` establishes LF for repository text and CRLF only for
  Windows command files.
- Source, tests, schemas, configuration, documentation and selected final
  acceptance evidence are tracked.
- No Git LFS dependency is required for the tracked baseline.

## Reproduction

```text
git status --short
git rev-parse --show-toplevel
git branch --show-current
git show --no-patch --format=fuller tim-im-v1.0.0
git tag -v tim-im-v1.0.0
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/verify_release_foundation.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli doctor
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli validate
```

`git tag -v` verifies object integrity and annotation display; it does not
claim a cryptographic signature because no signing key was configured.
