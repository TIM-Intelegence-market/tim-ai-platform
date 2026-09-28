# TIM: Codecov Integration

**Phase 4 — Codecov (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Configuration

- **Config file:** `codecov.yml` (repo root).
- **Coverage target:** 60% project, 60% patch, with thresholds (2% / 5%).
- **Flags:** `unittests`.
- **Upload:** `codecov/codecov-action@v5` in `.github/workflows/ci.yml`,
  gated on a successful test run and only when `coverage.xml` exists.
- **Fail on CI error:** `false` (so a missing DB never blocks the PR review
  signal; coverage file must exist to be uploaded).

## Status contract

Codecov statuses are considered **meaningful** only after a complete,
credentialed coverage baseline exists (see `docs/governance/coverage_baseline.md`
— currently `BLOCKED ON DATABASE CREDENTIAL`).

Until then, `require_ci_to_pass` and status gates are configured but the
coverage upload is intentionally non-failing to avoid masking CI results.

## Codecov token

- Not committed. Supplied as a repository secret `CODECOV_TOKEN` at runtime.
- Enable once the repository owner provisions a Codecov account bound to the
  repo (requires UI/account authorization, out of scope for OBSERVE-only).

## Verification checklist

- [x] `codecov.yml` present
- [x] Coverage upload step in CI (post-test)
- [x] Target/threshold gates configured
- [x] Coverage baseline doc references it
- [ ] Live Codecov status badge (pending Codecov account)

Status: **CONFIGURED — EXTERNAL ACCOUNT PENDING**