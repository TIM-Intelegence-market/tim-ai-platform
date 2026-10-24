# Manual review workbook completeness

An absent or empty `selected_cases` list cannot pass workbook validation,
even when its `approval` field is true or its summary counters claim completed
reviews. At least one actual complete case decision is required. Counts are
derived from the case rows rather than trusted from summary fields.

This is a completeness check, not authentication of human decisions. Its
`approval` output reports the supplied flag; it does not verify reviewer
identity, independence, signatures, source authenticity or scientific
sufficiency. Those remain separate mandatory review and governance checks.
Even a nonempty workbook with completeness status `PASS` cannot itself
authorize V2 or satisfy B06.

The existing 24-case diagnostic sample and its blank review workbook remain
unchanged. Empty samples must not be replaced automatically, and no reviewer
fields are filled by this check. The prospective qualification and requirement
for independent human scientific review continue unchanged.

## Extension (2026-10-22, T04 of the improvement plan)

`validate_review_packet(workbook, source_sample=None)` reports three findings
that are never merged into one flag:

| Finding | Meaning | Values |
|---|---|---|
| `completeness` | every selected case carries one complete, typed, non-contradictory decision (`ACCEPT`, `REJECT`, `EXCLUDE`; `EXCLUDE` needs `exclusion_reason`; `ACCEPT` needs all four quality flags true, `REJECT` at least one false; booleans must be booleans, confidence a number in [0, 1], timestamps timezone-aware) | `PASS`, `PENDING_OR_FAIL` |
| `approval` | the supplied `approval` flag, reported as given; only the boolean `true` counts | `true`, `false` |
| `authorization` | `reviewer_signature` and `release_authority_signature` exist, name distinct persons, carry their role and a timezone-aware time, and their `bound_content_hash` equals `review_content_hash(workbook)`; the release authority has not reviewed cases | `AUTHORIZED`, `NOT_AUTHORIZED` |
| `source_binding` | with a sample manifest: `source_sample_hash` matches and each row matches the sample by observation id, input hash, validation hash and outcome | `BOUND`, `MISMATCH`, `NOT_CHECKED` |

`review_content_hash` covers the case rows with their decisions and the source
references. It excludes `approval`, the legacy `workbook_hash` and the
signatures, so an attestation given over one set of decisions is invalid for
any edited set, while flipping the approval flag alone cannot re-sign anything.
`verdict` is `REVIEW_AUTHORIZED` only when completeness is `PASS`, approval is
true, authorization is `AUTHORIZED` and source binding is not `MISMATCH`.

A signature is a recorded attestation (who, when, over which content hash). It
is not a cryptographic proof and does not authenticate a person. Rejections are
valid outcomes: an authorized packet may contain `REJECT` decisions; the counts
are reported per decision. The legacy `validate_review_workbook` is unchanged;
`validate_review_packet` is the stricter check for release decisions. The
shipped blank 24-case workbook remains `PENDING_OR_FAIL` and `NOT_AUTHORIZED`.
