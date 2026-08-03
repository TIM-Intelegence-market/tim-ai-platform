# TIM GitHub Toolchain — Revalidated Baseline

**Phase 0 — Baseline Revalidation (v2.0)**

Capture: `2026-08-03T12:53:00Z`

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Repository and Git state

| Axis | Verified result |
|---|---|
| Repository root | `/Users/tim/Documents/TIM/tim` |
| GitHub repository | `uezeyiraydin-cell/tim-ai-platform` (private) |
| Owner context | GitHub **User** account `uezeyiraydin-cell` (no organization) |
| Default branch | `main` |
| Work branch | `opencode/github-security-quality` |
| Base branch | `codex/v2-finish-first` |
| Expected HEAD | `079063f feat(ui): add operations and research control center` |
| Actual HEAD | `079063f` — matches expectation, no reset performed |
| Upstream | none configured for work branch |
| Staged files | none |
| Modified files | 15 |
| Untracked files | 39 |
| GitHub CLI auth | `gh` logged in as `uezeyiraydin-cell`, scopes: `gist`, `read:org`, `repo`, `workflow` |
| Viewer permission | `ADMIN` |
| Merge strategy | merge commit, squash, and rebase all allowed |

## Live security feature inventory

| Feature | Live API result | Classification |
|---|---|---|
| Repository rulesets | `403 Upgrade to GitHub Pro or make this repository public` | BLOCKED — PLAN LIMITATION |
| Classic branch protection | `403 Upgrade to GitHub Pro or make this repository public` | BLOCKED — PLAN LIMITATION |
| Secret scanning (patterns endpoint) | `404` | BLOCKED — NOT AVAILABLE ON PLAN |
| Secret scanning push protection | `404` | BLOCKED — NOT AVAILABLE ON PLAN |
| Code scanning default setup | `404` | BLOCKED — NOT AVAILABLE ON PLAN |
| Dependabot alerts | disabled initially | ENABLED via API (PUT → 204) |
| Automated security fixes | enabled | ENABLED |
| Vulnerability alerts | `204 No Content` (enabled) | ENABLED |
| Actions permissions | `enabled: true` | HARDENED to `allowed_actions: selected` |
| Selected actions | `github_owned_allowed: true`, patterns: none yet | Requires allowlisting for third-party actions |
| Existing webhooks | none | — |
| Installed GitHub Apps (repo scope) | none detected | — |

## CI and coverage state

| Axis | Verified result |
|---|---|
| Test framework | pytest |
| Python | 3.13 (`.venv-research`), 3.14 (`.venv`) present |
| Full suite command | `scripts/run_full_test_suite.py` |
| Prior suite result | 362 passed, 0 failed, 154 warnings |
| Doctor | PASS (prior) |
| Validate | PASS (prior) |
| Coverage tool | none configured; `.coverage`/`htmlcov` ignored |
| Coverage.xml | not present |
| JUnit output | `artifacts/tim_manager/reports/mandatory_acceptance.junit.xml` (prior) |
| Workflows directory | absent (`.github/workflows/` missing) |
| Dependabot config | absent |
| CodeQL config | absent |
| Codecov config | absent |
| Sonar config | absent |
| CODEOWNERS | absent |
| PR template | present at `.github/pull_request_template.md` |

## Existing integration artifacts

- `docs/integrations/chatgpt_codex_connector_status.md` — created previous session (untracked, toolchain scope)
- `docs/governance/github_toolchain_baseline.md` — created previous session (untracked, toolchain scope)
- Graphify integration documents exist under `docs/integrations/graphify_*.md`
- `docs/governance/github_security_check.md` and `docs/governance/repository_audit.md` — **modified** by the V2 program; must not be committed in toolchain scope.

## Working tree status

Modified files (15) and untracked files (39) are classified in
`docs/governance/working_tree_forensics.md` (Phase 1). The files belong to the
V2-Finish-First program and are outside the GitHub-toolchain commit scope.

## Conclusion

The work branch, HEAD, and remote are verified. The repository is a private
repo on the GitHub **Free** user plan. Native security features that require
Pro or Enterprise are blocked. Local preparation for all machine-solvable
toolchain components proceeds; the main ruleset, secret scanning and push
protection are plan-blocked and will be recorded as `BLOCKED — PLAN LIMITATION`
unless a higher plan becomes available.

Status: **REVALIDATED BASELINE COMPLETE**
