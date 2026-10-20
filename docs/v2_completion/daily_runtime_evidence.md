# Daily qualification manifests: preserve the supplied runtime evidence

`build_daily_manifest` previously wrote a constant `trading_actions: 0`, even
when `metrics.runtime_status.trading_actions` reported a positive count or was
missing. That made the top-level summary disagree with its own input evidence.

New manifests copy a reported nonnegative integer count to `trading_actions`.
Booleans, strings, floats, negative values, absent counts and malformed runtime
status remain unknown (`null`). Absent evidence is never labelled as a reported zero. The raw metrics, including mode and timestamp, remain intact.

`trading_actions_source` names `metrics.runtime_status.trading_actions` for a
valid reported count, otherwise null. `runtime_evidence_scope` is always
`SUPPLIED_SNAPSHOT_NOT_FULL_DAY_PROOF`. The daily collector reads the current
health snapshot even when it catches up on an older day; that snapshot alone
cannot establish that the entire historical day had zero execution events.
Consumers must read the count together with its source and scope: it is a
supplied snapshot value, not a daily execution total or a retroactive attribution
to the manifest date. The manifest adds no new PASS gate and does not authenticate
the supplied count.

The derived count and scope fields are included in `manifest_hash`. Existing
manifests and their hashes are not rewritten. Fresh reports with a genuine
integer zero retain zero; consumers must treat null as unknown rather than
coerce it to zero. New fields change hashes of newly generated reports, not
the pre-existing semantic hash algorithm or governance contract.

This is an artifact-evidence correction under B03. It does not change execution
code, start/stop or abort a campaign, grant human approval, modify source health
files, or claim that all day-wide runtime evidence has been collected.

Offline tests preserve positive/zero counts, reject invalid values without
mutating metrics, retain a mismatching mode and collection timestamp, and bind
the summary to the manifest hash. A daily-CLI integration test writes one past
day from a later synthetic health snapshot with a nonzero count and verifies
that the saved manifest retains it and declares its limited scope. No runtime,
service, database or server access is involved.
