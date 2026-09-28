# TIM: Coverage Baseline (Phase 3)

**Phase 3 — CI & Coverage (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Coverage run outcome

**Status: NOT EXECUTABLE — INFRASTRUCTURE BLOCKER (database unavailable)**

A full coverage baseline cannot be produced in this environment because the
TIM database credential is currently unavailable.

## Exact blocker

```
config.secrets.SecretProviderError: macOS Keychain database secret is unavailable
    at config/secrets.py:132 (_keychain)
    reached via scripts/run_full_test_suite.py:88 (resolve_test_database_url
    -> settings.database_url)
```

Environment inventory (read-only checks, no changes made):

| Dependency | State |
|---|---|
| macOS Keychain `com.tim.database` entry | MISSING (`security find-generic-password` fails) |
| `~/.pgpass` | MISSING |
| `~/Library/Application Support/TIM/database-password` file | MISSING |
| Docker Postgres container | NOT RUNNING |
| Loopback listener on TCP 5432 | NONE |
| `TIM_DATABASE_URL` env (restricted to isolated tests) | NOT SET |

The test suite is intentionally fail-closed: without a secret provider it
refuses to run rather than fabricate credentials. This is the correct
behavior and must not be bypassed.

## Tooling installed (approved, isolated to `.venv`)

| Package | Version | Constraint followed |
|---|---|---|
| `coverage` | 7.15.3 | `>=7,<8`, no lock-file change |
| `pytest-cov` | 5.0.0 | `>=5,<6`, no lock-file change |

No productive dependency, lock file, or TIM source logic was modified.
`asyncpg`, `pytest`, `pytest-asyncio` were already present per `requirements.txt`.

## What CAN run without the database (documented, NOT a full baseline)

Non-DB unit tests can be executed independently, but per policy a partial
coverage figure is **not** presented as the baseline. Once a credentialed
Postgres URL is available, the authoritative command is:

```bash
.venv/bin/python scripts/run_full_test_suite.py --isolated-schema tim_baseline_YYYYMMDD \
  --cov --cov-report=xml:coverage.xml --cov-report=term --junitxml=artifacts/github_toolchain/pytest_full.junit.xml
```

## Codecov configuration (DB-independent, completed)

- `codecov.yml` — see `codecov.yml` in repo root (Phase 4).
- `.github/workflows/ci.yml` — see Phase 5/7 workflow (uploads coverage to
  Codecov only when `coverage.xml` exists).
- Coverage gate target and patch target are configured in `codecov.yml`;
  PRs that would lower coverage below the configured floor are flagged.

## Contract

- A coverage baseline is considered **complete only** when produced by the
  full suite against a credentialed, isolated test schema with `coverage.xml`
  plus a JUnit report, and the XML parses and reports a valid line-rate.
- Partial or failing coverage is never promoted to the baseline.

Status: **BLOCKED ON DATABASE CREDENTIAL — CONFIG WORK COMPLETE**