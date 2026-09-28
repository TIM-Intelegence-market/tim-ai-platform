# TIM Constitution V1 — adoption record

Status: ADOPTED ON DOCUMENTATION BRANCH

## Problem

TIM had architecture and platform-specific rules but no single, explicit
repository-level precedence document.

## Decision

`TIM_CONSTITUTION.md` is the authoritative engineering constitution. The Master
Prompt index references it before all platform prompts.

## Alternatives

- Keep the Constitution only in an external attachment: rejected because it
  would not be versioned with the repository.
- Duplicate it into every Master Prompt: rejected because copies would drift.

## Risks and controls

- **Interpretation drift:** controlled through one canonical file.
- **Conflict with an existing accepted platform:** this adoption changes no
  platform code or acceptance artifact.
- **Unauthorized release behavior:** no merge, release or tag is performed by
  this adoption record.

## Verification

The change is documentation-only. Acceptance requires Markdown integrity,
link/path verification, a protected-scope diff, Doctor, Validate and the
complete TIM test suite before any merge decision.

Verified on branch `codex/tim-constitution`:

- Constitution and relative Master-Index link: PASS.
- `git diff --check`: PASS.
- Doctor: PASS, exit code 0.
- Validate: PASS, exit code 0.
- Full TIM suite: 271 passed, 0 failed, 0 skipped, 0 XFAIL/XPASS,
  3 known warnings, exit code 0, duration 36.869 seconds.
- Test evidence: `artifacts/test_reports/constitution_full_suite.*`.
- Protected scope: documentation-only; no platform implementation changed.

Final adoption status on this branch: **PASS**.
