# TIM V2 finish-first pre-completion baseline

Evidence cut-off: `2026-08-01T21:01:00Z`

Capture: `2026-08-01T21:01:45.552323Z`

Program: `TIM-V2-FINISH-FIRST-20260801`

## Recovery point

The source worktree was independently verified clean on
`codex/v2-final-readiness` at
`d347140620287613e3bac24d0b9412ba38206ca8`, equal to the remote branch.
The completion branch is `codex/v2-finish-first` and started at the same
commit. The recovery capture was then generated while isolated implementation
work was already present on that branch; this explains the intentionally dirty
capture-time worktree recorded in the manifest without changing the clean
source baseline.

The machine-readable recovery set is:

- `artifacts/v2_completion/baseline_manifest.json`;
- `artifacts/v2_completion/implementation_state.json`;
- `artifacts/v2_completion/postgres_listener_before.json`;
- `artifacts/v2_completion/recovery/database_schema_catalog_before.json`;
- `artifacts/v2_completion/recovery/roles_and_rights_before.json`;
- `artifacts/v2_completion/recovery/dashboard_baseline.json`.

The schema catalog contains columns, constraints and indexes. Role evidence
contains role capability flags and database ownership only. No password,
password verifier, environment value, active SQL text or complete connection
string was captured. PostgreSQL configuration and HBA paths are explicitly
recorded as unavailable to the unprivileged `tim` role; the administrator
runbook must discover and back them up from the running server rather than
guess paths.

## Independently reproduced starting facts

| Axis | Verified result |
|---|---|
| Runtime | launchd label `com.tim.runtime`, PID captured from launchd, dashboard HTTP 200 |
| Safety mode | `OBSERVE`; Core frozen; trading actions `0` |
| Dashboard | `127.0.0.1:8765`, loopback only |
| Ollama policy | `DISABLED_BY_POLICY` for TIM |
| PostgreSQL | 18.4, `listen_addresses='*'`, SSL off, SCRAM password encryption |
| PostgreSQL role | `tim` login role, not superuser, no role/database creation privileges |
| Instance classification | `UNKNOWN`; exclusive TIM ownership is not proven |
| Local database probe | `127.0.0.1:5432` reachable |
| LAN database probe | `192.168.10.177:5432` reachable — FAIL |
| Frozen coverage | 663 / 1,093 = 60.659% |
| Extended live coverage | 9,847 / 14,447 = 68.160% |
| Missing coverage | 4,600 minutes in 283 P1 ranges; blocker V2-B02 remains P0 |
| Frozen independent cases | 1,339 → 910 → 378 → 14 |
| Current independent cases | 22,225 complete labels → 19,998 eligible labels → 8,620 source windows → 298 strict units |
| Required independent cases | 1,000 |
| Manual review | pending; no human approval |
| Secure MCP | external OpenAI action remains required; no support case ID |

The prior complete verification remains 362 passed tests, zero failures,
skips, XFAIL or XPASS, 154 warnings, Doctor PASS and Validate PASS. It is a
starting fact only; the completion branch requires a new unfiltered final run.

## Safety disposition

PostgreSQL LAN exposure is real and remains the leading safety failure. The
service is a system-level installation, the application role cannot read the
effective HBA/config paths, and exclusive service ownership is unproven.
Therefore it was not stopped or mutated. The correct disposition is
`BLOCKED — POSTGRES ADMIN ACTION REQUIRED`: complete every non-privileged fix,
produce an idempotent administrator bundle, and require an authorized
PostgreSQL administrator to apply and verify it.

Until that gate passes, no prospective qualification campaign may start and
no backfill candidate may be promoted into readiness coverage.
