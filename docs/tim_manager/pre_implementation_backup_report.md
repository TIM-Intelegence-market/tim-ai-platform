# TIM-IM Pre-Implementation Backup Report

## Authoritative project

- Project root: `/Users/tim/Documents/TIM/tim`
- Runtime evidence: the active process executes `/Users/tim/Documents/TIM/tim/main.py --init-schema`.
- Language: Python.
- Test framework: pytest.
- Package environment: local `.venv`; dependency declarations in `requirements.txt`.
- Scientific runtime: unchanged and running in OBSERVE-only mode.

## Git state

- Git root: `/Users/tim`
- Branch: `main`
- Commit: `a418894d33ba2426afe0f31d119332043bddd406`
- TIM project status: untracked inside the user-wide Git repository.
- TIM-specific work branch: not created.

Creating or switching a branch in this repository would affect the user-wide
working tree rather than an isolated TIM repository. This deviation is retained
as a governance limitation. No unrelated user files were staged or changed.

## Verified backup

- Backup: `/Users/tim/Documents/TIM/backups/tim_pre_intelligence_manager_20260728T072133Z`
- Source snapshot files: 226
- Protected data files inventoried by SHA-256: 48
- Raw market data copied: no
- Secrets copied: no
- Restore test: `VERIFIED`
- Restore hash differences: 0

The backup contains code, configuration, documentation, tests and small project
artifacts. Scientific data and large local environments are represented by
metadata and hashes rather than duplicated.

## Restore verification

The snapshot was copied to
`/Users/tim/Documents/TIM/tmp/tim_manager_restore_20260728T072133Z`. Stable path-ordered SHA-256 lists
for the snapshot and restored copy are byte-identical.

## Protected paths

The enforceable protection contract is stored in
`config/tim_manager/protected_paths.yaml`. TIM-IM writes default to deny and are
only permitted inside the explicitly listed TIM-IM paths.

## Phase-0 decision

Backup and restore verification passed. The authoritative runtime path and
write boundaries are unambiguous. Implementation may continue inside the
TIM-IM allowlist. The missing isolated Git repository remains documented and
must not be hidden by a synthetic branch claim.
