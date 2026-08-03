# TIM: GitHub Actions Supply Chain

**Phase 9 — Actions Supply Chain (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Current posture (verified via API, this session)

| Setting | Value |
|---|---|
| Actions enabled | `true` |
| Allowed actions | `selected` (GitHub-owned only) |
| Repository-owner-allowed actions | `false` |
| Verified-publisher actions | `false` (pending) |
| Third-party actions | blocked unless explicitly added |

Only `actions/checkout@v4`, `actions/setup-python@v5`,
`github/codeql-action@v3`, `codecov/codecov-action@v5`, and
`actions/upload-artifact@v4` are used by TIM workflows.

## Third-party action authorizations required

Because `allowed_actions` is `selected`, the following actions must be
explicitly allowed in the repository settings before CI can pass:

1. `codecov/codecov-action@v5`
2. `actions/upload-artifact@v4` (GitHub-owned; already allowed)

`github/codeql-action@v3`, `actions/checkout@v4`, and
`actions/setup-python@v5` are GitHub-owned and already permitted.

## Pinning policy

- All action versions are **major-version pinned** (e.g. `@v4`) in the
  workflow; Dependabot (Phase 6) keeps them current.
- Optional hardening upgrade path: pin full commit SHAs for the three
  third-party/cross-vendor actions and enable verified-publisher mode once
  the plan allows it.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Supply-chain tampering | Major-version pinning + CodeQL scanning + dependabot |
| Unauthorized action execution | `selected` allowlist (enforced at org/repo level) |
| Secret leakage in logs | No secret is echoed; tokens passed via `env` only |
| Action version drift | Dependabot github-actions updates weekly |

Status: **CONFIGURED — SELECTED-ALLOWLIST POSTURE VERIFIED**