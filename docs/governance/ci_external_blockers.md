# TIM: CI External Blockers

**Phase 13/15 — CI External Blockers & Startup Acceptance (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## 1. Branch

`opencode/github-security-quality`

## 2. Fix commit

`f4036f6` — `fix(github): pin codecov-action to verified SHA for selected allowlist`

## 3. GitHub Actions run

`30817807080` (push event, head `f4036f6a57dbdca7006f9b5d74c34e8c501cd05d`)

## 4. CI startup

**PASS**

## 5. Evidence

- Test job was created and started.
- CodeQL job was created and started.
- The earlier error "No jobs were run" is resolved.

## 6. Actions policy (verified via API, unchanged)

- `allowed_actions=selected`
- `github_owned_allowed=true`
- `verified_allowed=false`
- Exactly one third-party action explicitly allowlisted:
  `codecov/codecov-action@0fb7174895f61a3b6b78fc075e0cd60383518dac`
  (pinned to a verified full commit SHA)
- The global actions policy was NOT relaxed.

## 7. CodeQL

- Analysis of **209/209 Python files** completed.
- SARIF upload blocked because Code Scanning is not enabled for the
  repository under the current GitHub plan.
- Classification:
  **LOCAL PASS — EXTERNAL GITHUB PLAN FEATURE REQUIRED**

## 8. Test job

- Collection error in `tests/tim_manager/test_workspace_gateway.py`.
- Cause: `config/tim_manager/graphify_mcp.yaml` contains the local absolute
  path `/Users/tim/Documents/TIM/tim`.
- The GitHub runner uses a different checkout path, so
  `GraphifyMCPConfig.validate()` raises
  `working directory must be the TIM repository`.
- This is a pre-existing V2 configuration defect, not a GitHub-toolchain
  defect.
- No V2 file was modified in this assignment.
- Classification:
  **BLOCKED — V2 PORTABLE PATH REMEDIATION REQUIRED**

## 9. Codecov

- Action is correctly allowlisted and SHA-pinned.
- Upload was not reached because the test job failed before `coverage.xml`
  was produced.
- External Codecov account/token configuration additionally remains pending.
- Classification:
  **BLOCKED — UPSTREAM TEST AND EXTERNAL ACCOUNT REQUIRED**

## 10. Final toolchain verdict

**PASS WITH EXTERNAL AND V2 BLOCKERS**

## 11. Next separate assignment

Replace the hardcoded Graphify working directory with a portable,
repository-relative, or runtime-derived configuration, then re-run the
complete CI.

## Appendix — verified log excerpts

- CodeQL analyze: `CodeQL scanned 209 out of 209 Python files`
- CodeQL upload error: `Code scanning is not enabled for this repository`
- Test collection error:
  `GraphifyConfigurationError: working directory must be the TIM repository`
- Codecov step conclusion: `skipped` (gated on test success)

Status: **DOCUMENTED — PASS WITH EXTERNAL AND V2 BLOCKERS**