# TIM Constitution Band 5 — adoption record

Status: ADOPTED ON GOVERNANCE BRANCH

## Problem and goal

Bands 1–4 govern mission, engineering, architecture and canonical data, but do
not define one authoritative role, orchestration, communication, Memory,
routing and safety model for TIM's future multi-agent system.

## Decision

`TIM_AI_AGENT_CONSTITUTION.md` is the canonical Band 5 document. It applies
after Bands 1–4 and before every Master Prompt and implementation.

## Alternatives

- Define agent behavior independently in each prompt: rejected because roles,
  messages and safety boundaries would drift.
- Couple roles to specific model names: rejected because capabilities and
  model availability change independently of responsibility.

## Compatibility debt

Existing agent-oriented documents and tools may not yet implement Canonical
Task, Message, Memory, Event and Replay contracts. These gaps are explicit
migration debt. This adoption does not authorize retroactive agent, tool,
permission or platform changes.

## Acceptance scope

Documentation only. No agent implementation, platform code, schema, tool
permission, global configuration, secret, release tag or runtime state is
changed.

## Verification

Verified on branch `codex/tim-constitution`:

- Band-5 file and relative Master-Index link: PASS.
- `git diff --check`: PASS.
- Doctor: PASS, exit code 0.
- Validate: PASS, exit code 0.
- Full TIM suite: 271 passed, 0 failed, 0 skipped, 0 XFAIL/XPASS,
  3 known warnings, exit code 0, duration 30.581 seconds.
- Evidence: `artifacts/test_reports/ai_band5_full_suite.*`.
- Protected scope: documentation-only.

Final adoption status on this branch: **PASS**.
