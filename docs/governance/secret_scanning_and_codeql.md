# TIM: Secret Scanning, Push Protection, and CodeQL

**Phase 8 — Secret Scanning / Push Protection (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Plan limitation (verified via API, this session)

This repository is on the **GitHub Free plan for a private repository**.
GitHub's API returned `403`/`404` ("Upgrade to GitHub Pro or make this
repository public to enable this feature") for:

- `secret_scanning` enablement
- `secret_scanning_push_protection` enablement
- `code_scanning` (CodeQL default setup)

**Classification: `BLOCKED — PLAN LIMITATION`** (not an operator error and
not something the toolchain can change).

## What IS enabled (verified via API, this session)

| Capability | Status |
|---|---|
| Dependabot alerts | ENABLED (204 on enable) |
| Automated security fixes | ENABLED |
| Vulnerability alerts | ENABLED (204 on enable) |
| CodeQL scanning | BLOCKED (plan) |
| Secret scanning | BLOCKED (plan) |
| Push protection | BLOCKED (plan) |

## CodeQL substitute (works today)

Until CodeQL default setup is available, CI runs the CodeQL analysis action
in `ci.yml` (`github/codeql-action@v3`, Python). This requires
`security-events: write` permission and is already declared in the workflow.

## Secret hygiene guarantees (already in place)

- `config/secrets.py` is a fail-closed resolver; no literal secret values.
- Database credential flows through Keychain/pgpass/file providers only.
- Toolchain artifacts contain no secret values (verified by inspection).
- `.gitignore` excludes `.env`, `*.log`, runtime caches, and cost records.
- No token is committed; all API calls use scoped `gh` CLI auth.

## Recommended remediation once plan allows

1. Enable `secret_scanning` (rest API `PUT /repos/{owner}/{repo}/secret-scanning`).
2. Enable `secret_scanning_push_protection`.
3. Enable CodeQL default setup.
4. Commit a `SECURITY.md` reference to the scanning status.

Status: **BLOCKED ON PLAN — GUARDRAILS DOCUMENTED**