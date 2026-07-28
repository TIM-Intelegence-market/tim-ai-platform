# Dataset Platform - main branch merge evidence

Status: stable V2 component

## Merge

The accepted `codex/dataset-platform` branch was merged into the authoritative
`main` branch by a clean fast-forward:

```text
from: f1a0c4d2c4206c8a6cd8d78316ac2e786b84fe22
to:   f818d6245b46413ba76adaa584ab3d86ac2ca939
mode: --ff-only
```

No merge commit, release tag or unrelated branch was created.

## Post-merge verification

The test command was executed on `main` through the durable test runner:

```text
.venv/bin/python scripts/run_full_test_suite.py --label main_post_merge --timeout-seconds 180
```

Result: exit code 0; `complete: true`; 251 passed; 0 failed; 0 skipped; 0
XFAIL/XPASS; 3 existing warnings; duration 31.893 seconds. Evidence is stored
in `artifacts/test_reports/main_post_merge.junit.xml`,
`main_post_merge.stdout.log`, `main_post_merge.stderr.log` and
`main_post_merge_summary.json`.

The Dataset Platform is now the stable, versioned V2 Dataset Registry contract.
Starting the Knowledge Platform remains a separate, explicitly authorized task.
