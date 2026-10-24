# Case-audit reporting: count gate and scientific gate

The read-only `scripts/v2_readiness_audit.py` reports two different decisions.
`current_cutoff_audit.gate_status` (also `case_count_gate_status`) checks the
measured strict, non-overlapping, quality-screened 30-minute window count and
whether observation IDs are duplicated. A PASS here does not qualify the data
for V2.

The top-level case `gate_status` remains FAIL because the persisted validation
schema does not supply negative/neutral controls, reviewer identities,
inter-rater evidence or pre-registered regime labels. Manual scientific review
is still pending. `gate_reasons` lists these missing proofs and adds a count
shortfall or duplicate-ID reason only when the corresponding calculation fails.
The frozen and current counts are described independently in `gate_reason`.

For example, a current audit with 1,917 independent windows and no duplicates
has a count PASS and no `current_independent_windows_below_target` reason. Its
scientific gate remains FAIL. This is a reporting example, not a new measurement.

The CLI summary retains `frozen_case_gate` and `current_case_gate` for existing
consumers, and adds `scientific_case_gate`, `scientific_case_gate_reasons`,
`qualification_counted=false` and `v2_approved=false`. Consumers must not treat
`current_case_gate=PASS` as scientific approval. When a caller explicitly limits
the case observation start, `case_window_start_utc` records that boundary; null
means no lower observation-time bound was requested. Daily campaign manifests
remain separate prospective evidence.

This correction applies to future reports. Published historical artifacts and
their hashes remain intact. It changes neither coverage/quality calculations,
case selection, campaign activation nor governance approval. B03 (artifact audit)
and B04 (research quality) still require their remaining scientific evidence.

Offline regression coverage in `tests/test_v2_readiness_case_audit.py` includes
above-target counts, insufficient counts, duplicate IDs despite sufficient
counts, distinct frozen/current cutoffs, empty explicit windows, artifact hashes
and CLI output. These tests use synthetic records and a stub collector; they
connect to no database or server.
