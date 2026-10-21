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
