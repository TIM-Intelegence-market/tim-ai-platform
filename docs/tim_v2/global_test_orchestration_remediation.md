# Global test orchestration remediation

Status: PASS

## Root cause

Earlier direct foreground invocations of `.venv/bin/python -m pytest -q` exposed
progress output until roughly 28 seconds and then returned no completion
summary, exit code or retained capture. Process inspection found no remaining
pytest process. This is evidenced as an **environment/output-capture issue**;
there is no evidence for a pytest deadlock, resource leak, async-cleanup issue
or test-order dependency.

The remediation uses a persistent PTY session to wait for the runner. The
runner itself starts pytest once, gives it a private writable temporary
directory and persists all evidence before returning.

## Runner

`scripts/run_full_test_suite.py`:

- derives the repository root from its location;
- creates an isolated temporary directory and sets `TMPDIR`, `TMP` and `TEMP`;
- records Python/pytest version, command, UTC times, duration and exit code;
- writes separate stdout/stderr logs, JUnit XML and JSON summary;
- runs pytest in its own process group and terminates that group on timeout;
- returns pytest's exit code unchanged (or 124 on timeout); and
- has no retries, filters, skip/XFAIL changes or writes to protected paths.

## Staged verification

| Stage | Command | Exit | Passed | Failed | Skipped | XFAIL/XPASS | Warnings | Duration |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Dataset | `python scripts/run_full_test_suite.py --label dataset_stage --timeout-seconds 60 tests/test_tim_v2_dataset_registry.py` | 0 | 14 | 0 | 0 | 0/0 | 1 | 1.472s |
| TIM-IM | `python scripts/run_full_test_suite.py --label tim_manager_stage --timeout-seconds 180 tests/tim_manager` | 0 | 58 | 0 | 0 | 0/0 | 1 | 29.143s |
| Remaining | `python scripts/run_full_test_suite.py --label remaining_stage --timeout-seconds 180 -- tests --ignore=tests/test_tim_v2_dataset_registry.py` | 0 | 237 | 0 | 0 | 0/0 | 3 | 37.728s |
| Full TIM | `python scripts/run_full_test_suite.py --label full_suite --timeout-seconds 180` | 0 | 251 | 0 | 0 | 0/0 | 3 | 34.276s |

All commands used `.venv/bin/python` (Python 3.14.6) and pytest 8.4.2. The
known warnings are existing `pytest-asyncio` deprecations. The full report files
are `artifacts/test_reports/full_suite.junit.xml`,
`artifacts/test_reports/full_suite.stdout.log`,
`artifacts/test_reports/full_suite.stderr.log` and
`artifacts/test_reports/full_suite_summary.json`.

## Regression and protection checks

- Dataset tests: 14 passed.
- Full suite: 251 passed, exit 0, summary `complete: true`.
- Doctor: PASS, exit 0.
- Validate: PASS, exit 0.
- `git diff --name-only main...HEAD` contains Dataset implementation, test,
  schema, runner and Dataset acceptance documentation only.
- The runner never opens source URIs; no Dataset raw-data or network path is
  added.

## Final decision

PASS. No merge or tag was created. The full-suite report is reproducible by
running the recorded command in a persistent terminal session.
