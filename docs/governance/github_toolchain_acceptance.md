# TIM: GitHub Toolchain Acceptance

**Phase 15 — Acceptance (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`
Branch: `opencode/github-security-quality`

## Acceptance criteria

- [x] Phase 0 baseline revalidated
- [x] Phase 1 working tree forensics complete
- [x] Phase 2 scope isolation + `.gitignore` additive exception
- [x] Phase 2A integration health survey
- [x] Phase 3 coverage baseline attempted, blocker documented
- [x] Phase 4 Codecov config committed
- [x] Phase 5 SonarQube Cloud config committed
- [x] Phase 6 Dependabot config committed
- [x] Phase 7 CodeQL workflow committed
- [x] Phase 8 secret scanning status documented (plan-blocked)
- [x] Phase 9 actions supply chain validated
- [x] Phase 10 CODEOWNERS + PR template
- [x] Phase 11 main ruleset policy documented (plan-blocked)
- [x] Phase 12 negative tests all PASS
- [x] Phase 13 full validation PASS (config) + blocked register
- [x] Phase 14 documentation complete
- [x] Phase 15 commit scope: category A only, no foreign files

## Scope discipline

- Staged files: explicitly selected category A files only.
- No `git add .` / `git add -A`.
- No V2 modified/untracked files included.
- No runtime artifacts, no secrets, no generated files outside toolchain scope.
- No merge, tag, or release; OBSERVE-only preserved.

## Result

**Status: ACCEPTED — toolchain foundation ready; external blockers documented.**

## External blockers (remain after acceptance)

1. Full coverage baseline requires credentialed Postgres (Keychain secret).
2. Rulesets / secret scanning / push protection / CodeQL default setup
   require GitHub Pro plan.
3. Live Codecov and SonarQube badges require external accounts/tokens.
4. `codecov/codecov-action@v5` requires explicit selected-allowlist addition.
