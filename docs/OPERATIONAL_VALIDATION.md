# TIM Operational Validation

TIM's validator is a restart-safe, read-only process. It collects process RSS/CPU,
disk use, database and dashboard reachability, required-file health, and the
permanent benchmark result. Every event is written as JSONL with an immediate
flush and `fsync`.

Start the real 72-hour run:

```bash
.venv/bin/python scripts/operational_validation.py --start
.venv/bin/python scripts/operational_validation.py --status
```

The persisted state is `data/operational/state.json`; metrics and structured
events are in the same directory. Restarting the process preserves its original
deadline and counters. A completed 72-hour result is never emitted before that
deadline. Database or dashboard outages are recorded as degraded health rather
than hidden or treated as trading input.

This subsystem is OBSERVE-only. It has no order, credential, private-endpoint, or
execution path.

The acceptance gate is evaluated separately and refuses to create a final report
before the persisted real deadline:

```bash
.venv/bin/python scripts/acceptance_check.py
```

Its database evidence, event classifications, weighted criteria, and Markdown
report are deterministic for an explicit `--as-of` timestamp. A score alone
cannot override a failed required criterion.
