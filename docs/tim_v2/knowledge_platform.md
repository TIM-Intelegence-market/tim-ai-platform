# TIM V2 Knowledge Platform

Knowledge is structured and provenance-preserving, not merely retrieval.

| Object | Required fields | Rule |
|---|---|---|
| Source | identity, locator, hash, license, trust | source is immutable by version |
| Evidence | excerpt/observation reference, source, time, hash | evidence can support many claims |
| Claim | proposition, status, confidence, validity, evidence refs | unsupported claims remain visible |
| Fact | validated claim plus validation policy/result | facts remain challengeable |
| Observation | measured value, units, time semantics, dataset ref | never infer a missing value |
| Contradiction | claim/evidence pair, detection method, status | do not erase either side |
| Decision history | decision, alternatives, rationale, approver | explicit, append-only history |

Relationships include `supports`, `refutes`, `qualifies`, `derived_from`,
`supersedes`, `contradicts` and `used_by_research`. Retrieval/RAG indexes are
derived, replaceable views. Model outputs enter as untrusted candidate claims
until validation; they cannot overwrite canonical records.

TIM-IM V1 is consumed as a frozen, read-only knowledge/status source through
documented adapters. It is not a writable store or V2 database.
