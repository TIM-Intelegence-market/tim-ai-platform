# TIM Constitution Band 6 — adoption record

Status: ADOPTED ON GOVERNANCE BRANCH

## Problem and goal

Bands 1–5 define general safety and agent boundaries but do not provide one
complete Zero Trust contract for identity, authentication, authorization,
protected paths, secrets, filesystem, network, supply chain, audit, release,
backup, recovery, incidents and production.

## Decision

`TIM_SECURITY_ZERO_TRUST_CONSTITUTION.md` is the canonical Band 6 document. It
has binding Constitution status; conflict resolution follows the established
numbered precedence after Bands 1–5 and before Master Prompts.

## Alternatives

- Keep security requirements distributed across platform documents: rejected
  because default-deny and audit rules would be inconsistent.
- Implement security controls during adoption: rejected because this branch is
  documentation-only and platform/control changes require separate scoped work.

## Compatibility and security debt

Existing components may not yet implement every Band-6 identity, audit,
filesystem, network, backup and recovery control. These gaps are explicit
security debt. Adoption does not assert that controls are already implemented
and does not authorize silent changes.

## Acceptance scope

Documentation only. No security implementation, permission, agent, platform
code, schema, global configuration, secret, dependency, release tag or runtime
state is changed.

## Verification

| Gate | Result |
|---|---|
| Constitution file and Master Index link | PASS |
| `git diff --check` | PASS |
| Doctor | PASS; exit code 0 |
| Validate | PASS; exit code 0 |
| Full TIM test suite | PASS; 271 passed, 0 failed, 0 skipped, 0 xfailed/xpassed; exit code 0 |
| Protected scope | PASS; documentation-only change |

The full suite completed in 28.53 seconds and emitted 145 known
`pytest-asyncio` deprecation warnings. These warnings remain technical debt and
are not represented as resolved by this adoption.

Reproducible test evidence:

- `artifacts/test_reports/security_band6_full_suite.junit.xml`
- `artifacts/test_reports/security_band6_full_suite.stdout.log`
- `artifacts/test_reports/security_band6_full_suite.stderr.log`

## Final adoption status

PASS
