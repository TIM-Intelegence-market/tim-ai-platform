# Operations

Run `doctor` before a scan. A scan updates only the isolated TIM-IM SQLite
index, append-only event log, snapshots and reports.

The second scan without source changes must emit no new events. Stop and review
if protected-path validation fails, a required source is missing or parser
errors increase unexpectedly.

Restore instructions are stored with the Phase-0 backup.
