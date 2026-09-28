# TIM: Negative Tests

**Phase 12 — Negative Tests (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Purpose

Verify that the toolchain did **not** weaken any existing protection, did not
introduce secret material, and did not sweep foreign (V2) work into scope.

## Test results

| # | Negative test | Expected | Result |
|---|---|---|---|
| 1 | No secret literal in toolchain docs/artifacts | no match | PASS |
| 2 | No legacy hardcoded DB credential in tree | no match | PASS |
| 3 | No foreign (V2) file staged | empty stage | PASS |
| 4 | Working tree classification complete | all files classified | PASS |
| 5 | `.gitignore` still blocks `.env`, `data/`, `output/`, cost.json | ignored | PASS |
| 6 | No destructive git command executed (reset/clean/stash) | none run | PASS |
| 7 | No `git add .` / `git add -A` used | explicit paths only | PASS |
| 8 | No secret value printed to stdout/stderr in this session | none observed | PASS |
| 9 | DB test run fails closed (not silently passes) | SecretProviderError | PASS |
| 10 | Coverage baseline not promoted from partial data | blocked, documented | PASS |

## Coverage of the changed `.gitignore`

Only two additive exceptions were made (toolchain evidence dir). Re-checked:
the pre-existing protections for `.env`, `data/`, `output/`, `*.log`,
`graphify-out/cost.json`, and caches remain in force (Test 5).

## Blocker honesty

The DB secret unavailability is surfaced as an explicit error (Test 9) rather
than masked; the coverage baseline is marked blocked rather than fabricated
(Test 10). These are intentional honesty controls.

Status: **ALL NEGATIVE TESTS PASS**