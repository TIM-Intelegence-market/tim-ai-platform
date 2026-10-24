# Qualification start: verify the evaluated report before consuming it

The qualification start action previously copied the report's `report_sha256`
into gate references without recomputing it. Gate rows were converted directly
to a dictionary: a duplicate name could overwrite an earlier failing row.
The top-level green summary was trusted even when an individual gate failed.

`gates_from_report` now verifies the existing report hash before consuming
start evidence. It requires an explicit boolean `all_start_gates_pass=true`,
an explicit empty blocker list, exactly one row per required gate, and PASS
on every row. Malformed gate collections and missing/malformed freeze evidence
are rejected. Existing freshness, HEAD and frozen-commit checks still apply.

Producer and consumer share `start_gate_report_hash`: SHA-256 over the sorted
JSON report using the existing default JSON separators and `default=str`,
omitting only `report_sha256`. This is the existing producer's format; no
historical reports, algorithms, hash contracts or schema versions are migrated.
A fixed hash captured from the old producer is checked in the regression suite.
The separate raw-file hash recorded by the start script still identifies the
exact report-file bytes; it is not substituted for this report-content hash.

The hash checks content consistency, not a reviewer's identity or a digital
signature. Independently trusted evidence, human start authorization and
scientific/governance approval remain necessary. The correction does not start
or restart a campaign and does not approve V2, count historical data, alter the
34-day duration, or touch runtime/launchd/database state.

Tests cover a changed report with green decisions, absent/incorrect hashes,
a failing gate hidden by a later duplicate, inconsistent individual/summary
statuses, malformed gate collections, actual collector output and unchanged
producer hash bytes. The CLI integration regression confirms rejection occurs
before any campaign output directory or copied report is created. Synthetic
fixtures now carry valid report hashes; the existing wrong-frozen-commit test
re-seals its deliberately changed fixture so that it still reaches that check.
