# TIM: main Branch Ruleset

**Phase 11 — main Ruleset (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Plan limitation (verified via API, this session)

Rulesets require a paid plan. On this private Free-plan repository, creating
a `main` ruleset via API returns `403`/`404`
("Upgrade to GitHub Pro or make this repository public to enable this
feature").

**Classification: `BLOCKED — PLAN LIMITATION`.**

## Intended ruleset design (documented, pending plan upgrade)

- **Target:** `refs/heads/main`
- **Deletion:** block
- **Force push/force push bypasses rules:** block
- **Required status checks (from CI):**
  - `CI / test`
  - `CI / codeql`
- **Required pull request:** true
  - Dismiss stale reviews, optional; require codeowner review (optional on
    User plan single-owner).
- **Non-fast-forward:** block
- **Bypass actor:** repository admin is not to be listed as a general bypass.

## Why CODEOWNERS and CI remain the immediate controls

Until a ruleset can be created, safety is enforced by:

- CODEOWNERS requiring owner review on protected paths (`config/`,
  `scripts/`, `src/database/`, toolchain config) — committed at Phase 10.
- Dependabot + CodeQL + coverage CI (`Phase 5/7`).
- The toolchain's own hygiene discipline (no stray commits, explicit paths).

## Recommended remediation once plan allows

1. `POST` a ruleset for `main` via the Code scanning/rulesets API.
2. Wire it to require the `CI` checks.
3. Re-run Phase 13 validation to confirm.

Status: **BLOCKED ON PLAN — POLICY DOCUMENTED**