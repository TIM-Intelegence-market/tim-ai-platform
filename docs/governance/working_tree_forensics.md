# TIM Working Tree Forensics

**Phase 1 — Working Tree Forensics (v2.0)**

Capture: `2026-08-03T12:55:00Z`

Program: `TIM-GITHUB-SECURITY-QUALITY-TOOLCHAIN-2.0`

## Purpose

Classify every modified and untracked file so that GitHub-toolchain commits
remain strictly isolated from the V2-Finish-First program's in-flight work.
No file is deleted, stashed, reformatted, or reset. No foreign change is
included in toolchain commits.

## Classification categories

- **A. GITHUB_TOOLCHAIN_SCOPE** — belongs to this assignment.
- **B. V2_FINISH_FIRST_SCOPE** — V2 program; must not enter toolchain commits.
- **C. RUNTIME_GENERATED** — runtime logs/reports/temporary artifacts.
- **D. LOCAL_SECRET_OR_HOST_CONFIG** — must never be committed.
- **E. GENERATED_BUT_VERSIONABLE** — auto-generated but versionable per policy.
- **F. UNKNOWN** — unverified origin; do not modify or commit.

## Modified files (15)

| Path | Status | Origin | Workstream | Scope | Treatment |
|---|---|---|---|---|---|
| `TIM_Postgres_Setup.command` | modified | V2 credential handoff | V2-Finish-First | B | leave untouched |
| `TIM_Reset_Postgres_Password.command` | modified | V2 credential rotation | V2-Finish-First | B | leave untouched |
| `config/settings.py` | modified | secret-provider wiring | V2-Finish-First | B | leave untouched |
| `docker-compose.yml` | modified | secret-file DB config | V2-Finish-First | B | leave untouched |
| `docs/governance/github_security_check.md` | modified | V2 audit evidence | V2-Finish-First | B | leave untouched |
| `docs/governance/repository_audit.md` | modified | V2 audit evidence | V2-Finish-First | B | leave untouched |
| `main.py` | modified | durable ingestion app | V2-Finish-First | B | leave untouched |
| `scripts/reset_postgres_password.sh` | modified | V2 rotation | V2-Finish-First | B | leave untouched |
| `scripts/run_full_test_suite.py` | modified | V2 intake test runner | V2-Finish-First | B | leave untouched |
| `scripts/setup_postgres.sh` | modified | V2 credential handoff | V2-Finish-First | B | leave untouched |
| `src/data_ingestion/__init__.py` | modified | export durable store | V2-Finish-First | B | leave untouched |
| `src/data_ingestion/binance_ws.py` | modified | V2 recovery/ingress | V2-Finish-First | B | leave untouched |
| `src/database/schema.sql` | modified | durable tables | V2-Finish-First | B | leave untouched |
| `src/operational/logging.py` | modified | structured logging | V2-Finish-First | B | leave untouched |
| `tests/test_full_suite_runner_isolation.py` | modified | V2 test isolation | V2-Finish-First | B | leave untouched |

## Untracked files (39)

### Toolchain scope (A)

| Path | Status | Treatment |
|---|---|---|
| `docs/governance/github_toolchain_baseline.md` | untracked (prev. session) | commit in toolchain scope |
| `docs/governance/github_toolchain_revalidated_baseline.md` | untracked (this session) | commit in toolchain scope |
| `docs/integrations/chatgpt_codex_connector_status.md` | untracked (prev. session) | commit in toolchain scope |
| `artifacts/github_toolchain/` outputs | untracked (this session) | un-ignore and commit toolchain evidence |

### V2 Finish-First scope (B) — never commit in toolchain scope

| Path |
|---|
| `artifacts/v2_completion/independent_case_audit.json` |
| `artifacts/v2_completion/manual_review_workbook.json` |
| `artifacts/v2_completion/mcp_external_status.json` |
| `artifacts/v2_completion/qualification_daily_manifests/READMETIVE.md` → `README.md` |
| `artifacts/v2_completion/qualification_preregistration.json` |
| `docs/v2_completion/independent_case_methodology.md` |
| `docs/v2_completion/manual_scientific_review_packet.md` |
| `docs/v2_completion/prospective_qualification_preregistration.md` |
| `docs/v2_completion/qualification_campaign_status.md` |
| `docs/v2_completion/secure_mcp_external_status.md` |
| `scripts/admin/` (6 files) |
| `scripts/tim_catchup.py` |
| `scripts/tim_ingestion_control.py` |
| `scripts/tim_log_maintenance.py` |
| `scripts/tim_watchdog.py` |
| `scripts/timctl` |
| `src/data_ingestion/catchup.py` |
| `src/data_ingestion/control.py` |
| `src/data_ingestion/durable.py` |
| `src/data_ingestion/ingress.py` |
| `src/database/migrations/004_durable_ingestion.sql` |
| `src/operational/watchdog.py` |
| `tests/test_binance_recovery_v2.py` |
| `tests/test_durable_ingestion_contract_v2.py` |
| `tests/test_durable_ingestion_database_v2.py` |
| `tests/test_independent_watchdog_v2.py` |
| `tests/test_log_rotation_v2.py` |
| `tests/test_public_catchup_v2.py` |
| `tests/test_runtime_durable_pipeline_v2.py` |
| `tests/test_v2_completion_runtime_control.py` |
| `tests/test_v2_completion_security.py` |

### Secret risk note (D-adjacent)

`config/secrets.py` is an existing **untracked** V2 module that implements a
fail-closed secret resolver. It contains **no committed literal secret value**
(verified: no `password=`, `token=`, or long base64 literal appears in it; it
reads secrets from env/Keychain and only ever `quote()`s them at runtime). It
is V2 scope, not toolchain scope, and is not committed here.

## Commit-relevance summary

- Only category A files are eligible for toolchain commits.
- All category B files are left exactly as found in the working tree.
- No category D or F files exist in the tracked/untracked set.
- Explicit path `git add` is used exclusively; `git add .` and `git add -A`
  are never used.

Status: **FORENSICS COMPLETE**