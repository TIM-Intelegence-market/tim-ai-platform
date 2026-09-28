# TIM: Git Hygiene & Scope Isolation

**Phase 2 — Git Hygiene & Scope Isolation (v2.0)**

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Goal

Keep the GitHub-toolchain program's commits strictly isolated from the
concurrent V2-Finish-First program's working-tree changes. Toolchain work
must never sweep in, reformat, or reveal V2 in-flight code or secrets.

## Non-negotiables

1. **Staged files are explicit and minimal.** Only toolchain-scope files
   (category A) are ever `git add`-ed, by full relative path.
2. **Never use `git add .` or `git add -A`** in the toolchain scope, because
   the working tree contains V2-modified and V2-untracked files.
3. **Never stash** — `git stash` could capture V2 work and its secrets.
   Foreign changes belong to another workstream.
4. **Never `git reset --hard`** or blanket `git clean` in this repo.
5. **Never cherry-pick, merge, rebase, or reset** into or out of the toolchain
   branch unless explicitly requested.
6. **No commits** until every phase's artifacts land in scope; commit only
   when the assignment explicitly calls for it (Phase 15).

## Scope categories (source of truth: `working_tree_classification.json`)

- **A. GITHUB_TOOLCHAIN_SCOPE** — eligible for toolchain commits.
- **B. V2_FINISH_FIRST_SCOPE** — leave untouched, never commit in toolchain.
- **C. RUNTIME_GENERATED** — not committed.
- **D. LOCAL_SECRET_OR_HOST_CONFIG** — never committed.
- **E. GENERATED_BUT_VERSIONABLE** — committed per policy.
- **F. UNKNOWN** — never touched.

## .gitignore governance

- `.env`, `.env.*` (except `.env.example`), `*.log`, runtime artifacts are
  ignored already.
- New exception added so toolchain documentation is versionable:
  ```
  !artifacts/github_toolchain/
  !artifacts/github_toolchain/**
  ```
- The exception is scoped narrowly to the toolchain evidence directory and
  does not weaken any existing `artifacts/*` rule.
- Cache/token files (`.coverage`, `htmlcov/`, `*.log`, caches) remain ignored,
  ensuring code-coverage and other tokens never get staged.
- `config/secrets.py`, `scripts/admin/prepare_tim_credential.py`, and other
  classifier-B files are never touched or staged by the toolchain.

## Commit anatomy (Phase 15)

Each toolchain commit will:
- include **only** category A files whose docs are referenced,
- include `.gitignore` changes that are toolchain-justified,
- exclude every V2 modified/untracked file,
- carry a conventional-commit message scoped to `security-toolchain`.

Status: **SCOPE-ISOLATION RULES READY — pending Phase 15 commit**