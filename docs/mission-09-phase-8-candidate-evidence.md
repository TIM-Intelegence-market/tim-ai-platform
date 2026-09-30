# Mission 09 — Phase 8 Candidate Evidence (P8.1 / P8.2)

Status: **BLOCKED**, because the dependency gate is not met.

Authoritative issue: #19 — `[REPAIR][M09/P8] Proven Self-Healing Recipes`

Parent mission: #9

Evidence cutoff: 2026-09-27, all remote branches of this repository.
Dependency status refreshed: 2026-09-30, against `platform-main` (`8d74be2`).

## Purpose

This document records only the read-only work that #19 allows before its gates
exist:

- **P8.1:** select historical low-risk incident candidates that have repository
  evidence.
- **P8.2:** for each candidate, record what the repository proves about the root
  cause, fingerprint anchor, bounded action, rollback, regression test and
  recurrence protection, and what it does not prove.

It does **not** encode a recipe, apply a repair, or claim that any incident is
`FIXED`. Per #9, a report is never completion.

## Gate check: why no recipe is encoded

#19's Done criterion requires the full lifecycle to run **under the gate engine**
(`DETECT → MATCH → PRECHECK → REPRODUCE → REPAIR → VERIFY → FIXED`). None of the
components that lifecycle runs on exist on any branch:

| Dependency | Issue | State (2026-09-30) | Repository evidence |
|---|---|---|---|
| P0 Baseline | #11 | CLOSED | closed on GitHub |
| P1 Task Engine | #12 | CLOSED | merged via PR #119 into `platform-main`; `src/task_engine/` now exists (see below) |
| P2 Incident Foundation | #13 | OPEN / WAITING | no incident/fingerprint store on `platform-main` |
| P5 Remediation Registry | #16 | OPEN / WAITING | no remediation registry on `platform-main` |
| P6 Reproduction & Sandbox | #17 | OPEN / WAITING | no sandbox engine on `platform-main` (only the P1 disposable workspace, see below) |
| P7 Safety & Verification Gates | #18 | OPEN / WAITING | no central gate engine on `platform-main` |

At the 2026-09-27 cutoff #11 was blocked and #12 was still in its first step.
Both are now closed; the blocker for #19 is #13, #16, #17 and #18.

### What #12 (PR #119) provides for Phase 8

`platform-main` now contains building blocks that a later recipe will run on,
all scoped to Issue #12:

- `src/task_engine/self_heal.py`: the recurrence loop
  (detect → match known case → BUGFIX → reproduce → execute stored approved
  repair → evidence → Fix-First gate). Without a known case or an approved
  recipe the task is `BLOCKED`.
- `src/task_engine/repair_executor.py`: applies one approved, bounded recipe
  to a disposable workspace only; it never deploys and never sets `FIXED`.
- `src/task_engine/fix_first.py`: the Fix-First validator. It rejects
  *operational remediation* until that has its own verifier.

These are not the #18 gate engine. They cover code repairs in a disposable
workspace. C1 below is an operational remediation (restoring a live
connection), so it still needs the #18 gates and an operational verifier
before it can reach `FIXED`.

#18 requires "one authoritative fail-closed gate engine used by all later
repair workflows; no parallel ad-hoc safety decisions." Building a stand-in
registry, sandbox or gate engine inside #19 would violate that rule. P8.3–P8.10
therefore remain `NOT_STARTED`.

## Source lineage note

`main` and the runtime branches (`release/v1.0.0`, `opencode/*`, `feature/*`,
`qwen/*`) share **no merge base**. Several fixes below exist only on the runtime
lineage, so every citation names its branch or commit.

Checked on `platform-main` (2026-09-30): the C1 sources, `ops/launchd/com.tim.awake.plist`
(`7e49df3`), the C2 rate-limited logging and its test, and the C4 fix (`170526b`)
are present. The C3 commits (`fd94912`, `c5eb630`, `efb80c7`) and the C2 bulk
commit (`58bd3de`) are not ancestors of `platform-main`; C3's regression test
and CI workflow are not on it.

## Candidate register

Evidence strength:

- **STRONG:** root cause is documented and reproducible.
- **MEDIUM:** a fix and/or test exists, but the root-cause record is indirect.
- **NONE:** no repository evidence.

### C1 — Binance WebSocket disconnect during macOS host sleep

| Field | Evidence |
|---|---|
| Evidence strength | **STRONG** |
| Sources | `TIM_MISSING_INPUT_FORENSICS_REPORT.md`, `TIM_WEBSOCKET_FAILURE_ANALYSIS.md`, `TIM_TRANSPORT_RELIABILITY_REPORT.md` (all on `main`) |
| Verified root cause | `LOCAL_HOST`: 33/33 gap groups end within 53 s of a logged disconnect, with 99.508 % aggregate overlap with macOS sleep intervals. The analysis hash was reproduced 10/10 times. |
| Fingerprint anchor (draft) | component `src/data_ingestion/binance_ws.py`, message prefix `Binance public stream disconnected`, reason ∈ {`no close frame received or sent`, keepalive `ping timeout`} (28 and 5 historical occurrences) |
| Existing recovery | `BinanceTradeStream.run` reconnects with `min(30, 2**min(attempt,5)) + jitter` backoff (`src/data_ingestion/binance_ws.py:37-59`) |
| Existing prevention | `ops/launchd/com.tim.awake.plist` runs `caffeinate -dimu` (`release/v1.0.0`, commit `7e49df3`) |
| Proposed autonomy | **A1** (operational recovery: bounded reconnect) |
| Bounded action | Reconnect only, with a finite attempt budget. The stream gap is recorded as evidence. |
| Forbidden in recipe | Backfilling or reconstructing missing minutes (#9 forbids silently filling data gaps). Any write to AggTrades or candles. |
| Rollback | None needed: reconnect mutates no stored state. When the budget is exhausted, go to `ESCALATED`. |
| Gaps found | (1) The reconnect loop is **unbounded**: it has no attempt ceiling and never escalates. (2) `tests/test_binance_ws.py` covers only `parse_message`; there is **no regression test for reconnect/backoff**. |
| Verdict | **Preferred first A1 candidate (P8.4)** once #13/#16/#17/#18 exist. |

Honest scope: this recipe can restore **transport continuity** only. The 430
historically missing minutes remain `DOWNLOAD_FAILED` and must not be repaired
by this recipe.

### C2 — Outbox worker log hot-loop

| Field | Evidence |
|---|---|
| Evidence strength | **MEDIUM** |
| Sources | `release/v1.0.0`: `main.py` `_worker_loop` (0.25 s poll), `src/operational/logging.py` `StructuredLog.write(rate_limit_seconds=…)`, `tests/test_log_rotation_v2.py::test_structured_log_rate_limits_and_reports_suppressed_count` |
| Root cause (inferred from code) | An idle or `TERMINAL_BLOCKED` outbox worker cycles every 0.25 s and wrote one `OUTBOX_WORKER_CYCLE` / `OUTBOX_WORKER_UNAVAILABLE` line per cycle. The fix rate-limits by key (60 s idle/terminal, 30 s unavailable) and reports `suppressed_since_last`. |
| Provenance weakness | The fix arrived in the bulk commit `58bd3de` ("feat: sync complete TIM development state", 2026-09-03). No incident record or dedicated root-cause commit exists. The 7 MB `runtime_launchd.err.log` in `docs/tim_manager/final_acceptance_review.md` is stderr, not the queue log, so it is **not** proof of this hot-loop. |
| Fingerprint anchor (draft) | the same `rate_limit_key` repeating above N lines per minute in the queue log |
| Proposed autonomy | **A1** |
| Bounded action | Lossless rotation via `LogRotator.rotate_if_needed(force=True)`: rename plus gzip, with `fsync`. |
| Forbidden in recipe | `LogRotator._prune_expired_locked` deletes backups older than `retention_days`, which deletes evidence, so pruning must be excluded. The recipe must also never touch the blocked outbox item: clearing the queue/outbox and resetting attempts are hard-forbidden. |
| Rollback | Rotated files are retained compressed. Rollback means restoring the prior file from the `.1.gz` backup. |
| Gaps found | No root-cause incident record. The fix is not on `main` (different lineage). |
| Verdict | **Candidate: second A1**, after an operator log excerpt confirms the historical hot-loop (P8.2 completion). |

### C3 — Qwen supervisor launched with resolved framework Python instead of venv Python

| Field | Evidence |
|---|---|
| Evidence strength | **MEDIUM** (fix + regression test + CI wiring; the failure log is not in the repository) |
| Sources | `fd94912` fix (`python.absolute()` instead of `.resolve()`, add `PYTHONPATH`), `c5eb630` regression test `tests/test_local_qwen_launchd_installer.py`, `7be502f` bootstrap, `efb80c7` CI gate `qwen-supervisor.yml` (branches `feature/local-first-qwen-worker`, `qwen/76-server-bootstrap-pr`, …) |
| Root cause | Resolving the venv symlink made launchd start the framework interpreter, which lacks the venv site-packages and the repository import path. |
| Proposed autonomy | A2 at most. However, `f04a7a2` later moved the worker to a **system** LaunchDaemon, so regenerating and reloading it requires root. |
| Recurrence protection | Already present: the regression test runs in CI. |
| Verdict | **Detection-only (A0) + ESCALATE.** It is not eligible for autonomous repair because the action requires root. |

### C4 — LaunchDaemon re-bootstrap before `bootout` completes

| Field | Evidence |
|---|---|
| Evidence strength | **MEDIUM** (fix only) |
| Sources | `170526b` "fix: wait for launchd jobs before rebootstrap": a bounded 15 × 1 s wait on `launchctl print system/<name>` in `scripts/install_tim_24x7.sh` (`release/v1.0.0`, `opencode/rolling-liveness-ops-fix`) |
| Root cause | `bootstrap` raced a service that was still unloading. |
| Gaps found | No regression test. The script requires root (`EUID` check). |
| Verdict | **Not eligible: A0 detection + ESCALATE.** Installing system services is outside the A1/A2 scope. |

### C5 — Dashboard / recovery port conflict

| Field | Evidence |
|---|---|
| Evidence strength | **NONE** |
| Search performed | Commit messages and file contents on all remote branches for `EADDRINUSE`, `address already in use`, `Errno 48`, `Errno 98`, `port conflict`, `port … already in use` |
| Result | No incident, log excerpt, fix, or test found. The dashboard binds `127.0.0.1:8765` (`TIM_DASHBOARD_PORT`). |
| Verdict | **REJECTED: no invented recipe.** This can be reopened only with operator-supplied evidence. |

### Excluded by policy (not low-risk)

| Class | Reason |
|---|---|
| Test/production DB isolation (asyncpg target override, PGPORT) | Test-isolation integrity; owned by #11 |
| Out-of-order trade recovery / terminal head-of-line blockage | Strict-order domain: A4 `SAFE_STOP + ESCALATE` |
| Transient DB-read retry in `scripts/update_rolling_liveness.py` (`c643771`) | Plausible future A1, but the retry itself has no regression test. Kept on a watch list only. |

## Required negative cases for P8.7 (unsafe/unknown must fail closed)

When the gate engine exists, #19 must prove at least:

1. An unmatched fingerprint (e.g. a port-conflict error with no recipe) goes to
   `ESCALATED`, never an improvised action.
2. A `TERMINAL_BLOCKED` outbox head goes to `SAFE_STOP`. The recipe never
   clears, skips or resets it.
3. A C1 recipe that attempts gap backfill is rejected by the forbidden-action
   policy.
4. C3/C4-class incidents that need root go to `ESCALATED` with the exact manual
   action recorded.
5. When the C1 reconnect budget is exhausted, the state is `ESCALATED`, not
   `FIXED`.

## Exact next actions when #13, #16, #17 and #18 pass

1. P8.3: shadow-run C1 in the #17 sandbox against a controlled disconnect
   fixture.
2. P8.4: encode C1 as the first A1 recipe. Add the missing reconnect regression
   test and a finite attempt budget, and verify continuity with no stored-data
   mutation.
3. Obtain operator log evidence for C2 before encoding it.
4. P8.5: no A2 candidate currently qualifies, because C3 and C4 need root.
   Record that fact rather than inventing one.

## Machine-readable summary

```ini
M09_P8_STATUS=BLOCKED
BLOCKER=DEPENDENCIES_NOT_MET:#13,#16,#17,#18(#11,#12_CLOSED)
P8_1_CANDIDATE_SELECTION=DONE_READ_ONLY
P8_2_EVIDENCE_PACK=PARTIAL
P8_3_TO_P8_10=NOT_STARTED
CANDIDATES_STRONG=C1
CANDIDATES_MEDIUM=C2,C3,C4
CANDIDATES_REJECTED_NO_EVIDENCE=C5
FIRST_A1_CANDIDATE=C1_WEBSOCKET_HOST_SLEEP_RECONNECT
A2_CANDIDATES_ELIGIBLE=NONE
RECIPES_ENCODED=0
INCIDENTS_FIXED=0
PRODUCTION_MUTATION=NO
LIVE_TRADING=DISABLED
EXECUTION=DISABLED
NEXT_ACTION=WAIT_FOR_#18_PASS_THEN_P8.3_SHADOW_RUN_C1
```
