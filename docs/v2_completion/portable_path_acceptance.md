# TIM V2: Portable Path Acceptance

**PROGRAM 1 — ACCEPTANCE (v1.1)**

Program: `TIM-V2-COMPLETION-PROGRAM-20260803`

## Result

**PORTABLE PATH REMEDIATION — LOCAL PASS (CI VERIFIED FOR PORTABLE-SCOPE TESTS)**

## What was fixed

1. `config/tim_manager/graphify_mcp.yaml` — replaced all host-bound absolute
   paths with the `@TIM_REPO_ROOT@` placeholder and a bare executable name.
2. Added `src/tim_manager/config_paths.py` — canonical repository-root
   resolver with a secure placeholder substitution.
3. `src/tim_manager/workspace_gateway.py` — added explicit denial of
   parent-directory traversal (`..` path segments) in graph queries. This was
   a real security gap: traversal was previously denied only when the query
   happened to contain an excluded-path marker substring (e.g. macOS tmp_path
   containing `/private/`), so it passed locally but failed on Linux CI.
4. `.github/workflows/ci.yml` — added a `postgres:16` service container and
   wired `TIM_DATABASE_SECRET_PROVIDER=url-env` + `TIM_DATABASE_URL` for the
   test job, making all DB-backed unit tests runnable in CI.

## Resolver behavior (verified)

| Scenario | Result |
|---|---|
| Local original path | PASS |
| Temporary CI checkout (repo root via package location) | PASS |
| Symlink | handled (resolve) |
| Missing config | load errors closed |
| Path traversal (`/../etc/passwd`) | REJECTED |
| Absolute path outside repo (`/Users/tim/.ssh/id_rsa`) | REJECTED |
| Empty spec | REJECTED |
| Denied dirs (`.git`, `data`, `backups`, `secrets`, `output`) | REJECTED |
| Non-relative placeholder | REJECTED |
| `TIM_REPO_ROOT` env override outside repo | REJECTED |
| Read-only Graphify default | preserved |

## Tests

- `tests/tim_manager/test_portable_paths_v2.py` — 11 new tests, all PASS.
- `tests/tim_manager/test_graphify_mcp_client.py` + `test_workspace_gateway.py`
  — 55 tests, all PASS (was the CI failure point).
- Full `tests/tim_manager/` — 124 passed.

## Inventory

Portable-path inventory: 0 MUST-REPLACE in runtime code; 10 HOST-CONFIG-SAFE
HOME-relative credential defaults; 3 TEST-FIXTURE assertions.
See `portable_path_inventory.{md,json}`.

## CI status

### Fixed in CI (verified green)

| Area | Result |
|---|---|
| Test-job collection (graphify config path) | PASS |
| DB-backed unit tests (Postgres service) | PASS |
| `test_workspace_gateway.py` + `test_graphify_mcp_client.py` unit tests | PASS (55) |
| `tests/tim_manager/` full suite | 124 passed locally |
| Full CI test job | **392 passed, 9 failed** |

CI run `30821999602` (commit `f2b3559`).

### Remaining 9 failures — all environment/tool-coupled (NOT path issues)

| Test | Blocker | Class |
|---|---|---|
| 5 × `test_real_*` in `test_graphify_mcp_client.py` | `graphify-mcp` executable not installed on runner (uv tool) | EXTERNAL TOOL |
| `test_module_b_local_report_and_isolated_gpt_researcher` | `.venv-research/bin/python` absent on runner | EXTERNAL VENV |
| `test_live_research_monitor_matrix_is_green` | live research monitor matrix (RED) | EXTERNAL RUNTIME STATE |
| `test_s15_protected_paths_remain_unchanged` | gitignored provenance artifact `artifacts/provenance/TIM-V1-UNFREEZE-*.json` not present in fresh checkout | GITIGNORED ARTIFACT |
| `test_s19_cli_returns_meaningful_exit_codes` | `doctor` requires generated snapshot `artifacts/tim_manager/snapshots/current.json` (created by scan runs, not committed) | GENERATED ARTIFACT |

None of these depend on host paths in committed code — all are external tool,
venv, runtime-state, or generated-artifact requirements outside the portable
path scope. Per V2 rules they are NOT skipped or xfail-marked; they remain
visible failures with honest classification.

## Status

**LOCAL PASS — CI GREEN FOR ALL PORTABLE-SCOPE TESTS (9 env/tool-coupled
failures classified, no masking)**