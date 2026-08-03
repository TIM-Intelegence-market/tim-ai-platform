# TIM: GitHub Actions Validation

**Phase 13/15 — Actions Supply Chain Validation (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Purpose

Confirm the GitHub Actions posture and validate that the committed workflows
are consistent with TIM's OBSERVE-only, hardened, selected-allowlist posture.

## Verified posture (via API, this session)

| Setting | Value | Validate |
|---|---|---|
| Actions enabled | `true` | PASS |
| Allowed actions | `selected` | PASS |
| GitHub-owned actions allowed | `true` | PASS |
| Repository-owner actions | `false` (owner actions not blanket-enabled) | LOCAL PASS |

## Workflow inventory

| Workflow | File | Jobs | Validation |
|---|---|---|---|
| CI | `.github/workflows/ci.yml` | `test`, `codeql` | PASS |

## Action versions and origins

| Action | Version | Origin | Validation |
|---|---|---|---|
| `actions/checkout` | `@v4` | GitHub-owned | PASS |
| `actions/setup-python` | `@v5` | GitHub-owned | PASS |
| `github/codeql-action` | `@v3` | GitHub-owned | PASS |
| `codecov/codecov-action` | `@v5` | third-party | MUST BE ALLOWED in selected allowlist |
| `actions/upload-artifact` | `@v4` | GitHub-owned | PASS |

## Per-job right needed

- **test job:** `contents: read`, `checks: write`.
- **codeql job:** `contents: read`, `security-events: write`, `actions: read`.
- Workflow-level `permissions` block: `contents: read`,
  `security-events: write`, `checks: write` (minimum necessary).

## Runtime secret handling

- `CODECOV_TOKEN` is not committed; supplied via repository secret at runtime,
  injected with `env` only, never echoed.
- No workflow writes, merges, tags, or releases (OBSERVE-only).

## YAML validity

Validated via `yaml.safe_load`; all four toolchain YAML files parse cleanly.

## Residual external blocker

`codecov/codecov-action@v5` must be explicitly added to the repository's
selected-actions allowlist (UI/config step) before the CI upload step can run.

Status: **WORKFLOWS VALID — SELECTED-ALLOWLIST ENFORCEMENT ENABLED**