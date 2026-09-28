# TIM Mission Orchestrator

The orchestrator enforces this order: Mission 01 recovery, Mission 05 catch-up,
idle validation, cursor validation, explicit gap classification, Mission 04
preflight, a bounded observe-only collection, Mission 02 intelligence, and only
then Mission 03 validation/shadow/paper work.

Run the scheduler with `python scripts/tim_orchestrator.py run`, or one
scheduler-owned tick with `python scripts/tim_orchestrator.py tick`.
Inspect the checkpoint with `python scripts/tim_orchestrator.py status`. The
scheduler should use 10-second cadence while catch-up is active, 60 seconds when
idle, and the persisted `next_run_at` value after infrastructure failures. Never
start a second scheduler instance; the process lock rejects it.

Authoritative state is stored in `artifacts/orchestration/state.json`, the
append-only audit stream in `history.jsonl`, job receipts below `job_receipts/`,
and the human-readable phase report in `latest_report.md`.

Safety is fail-closed: exactly one TIM worker, no concurrent recovery/drain/
backfill process, bounded resource usage, finite unknown-error retries, classified
gaps, valid cursor, and Mission 04 preflight PASS. The layer never deletes data,
resets attempts, empties queues, changes gap records, or starts trading. Local
helper agents are disabled by default and, if explicitly enabled, remain
read-only and budgeted. AI output is advisory only and cannot satisfy a gate.

Mission 03 release is deliberately not wired to live execution. Even a valid
release attestation only permits later validation/shadow/paper orchestration;
live trading and trading actions remain disabled in this implementation.
