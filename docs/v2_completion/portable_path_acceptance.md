# TIM V2: Portable Path Acceptance

**PROGRAM 1 — ACCEPTANCE (v1.0)**

Program: `TIM-V2-COMPLETION-PROGRAM-20260803`

## Result

**PORTABLE PATH REMEDIATION — PASS (LOCAL)**

## What was fixed

1. `config/tim_manager/graphify_mcp.yaml` — replaced all host-bound absolute
   paths with the `@TIM_REPO_ROOT@` placeholder and a bare executable name.
2. Added `src/tim_manager/config_paths.py` — canonical repository-root
   resolver with a secure placeholder substitution.

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

Run `30817807080` test-job previously failed at collection in
`test_workspace_gateway.py` because the graphify config hardcoded the local
path. With the placeholder, that collection error is removed; CI will be
re-run under Phase 1.6 together with the dashboard work once committed.

## Status

**LOCAL PASS — CI RE-RUN PENDING (committed before full CI exercise)**