# AUTOMATED PRE-REVIEW — NOT HUMAN APPROVAL

Artifact status: **AUTOMATED ASSESSMENT ONLY**

Mode: **OBSERVE**

Automated recommendation: **MORE EVIDENCE REQUIRED**

This recommendation is not a human decision, signature, scientific approval,
or V2 authorization. It must not populate the manual approval form or change
the checklist/RACI decision state.

## Automated gate summary

| Gate | Automated assessment | Evidence |
|---|---|---|
| Frozen continuous coverage at least 95% | FAIL | 663/1,093 = 60.659% |
| Extended same-start coverage at least 95% | FAIL | 9,487/14,087 = 67.346%; 4,600 missing minutes |
| Gap classification and source continuity | FAIL / INCOMPLETE | 283 extended missing ranges; 39 fixed-cut aggregate-ID discontinuities |
| At least 1,000 raw complete labels | PASS AS A RAW COUNT ONLY | 1,339 |
| At least 1,000 strict quality-screened labels | FAIL | 910 |
| At least 1,000 strict unique source windows | FAIL | 378 |
| At least 1,000 strict non-overlapping 30-minute windows | FAIL | 14 |
| Case/case-link referential integrity | PASS | 1,339 unique IDs/hashes; zero audited relationship mismatches |
| Core sampled replay | PASS IN BOUNDED SAMPLE | 24/24 input-hash, validation-hash, reversed-input, source-continuity and pre-cutoff checks |
| Gap-sensitive abstention | PASS prospective code / FAIL frozen evidence | final validator requires 5/15/30 plus contiguous source IDs; historical rows remain unchanged |
| Trigger identifier lineage | PASS IN LATER LIVE AUDIT | 8,347/8,347 recomputed IDs |
| End-to-end atomic/hash-chained history | NOT PROVEN | mutable upsert and multiple non-atomic stores |
| Restart/crash replay above load limits | NOT PROVEN | representative test absent |
| Negative/rejected/control population | ABSENT | fired observations only |
| Volatility/liquidity regime analysis | ABSENT | no persisted regime labels |
| Named independent reviewers | ABSENT | RACI role holders unassigned |
| Signed manual scientific decision | PENDING | blank form; no decision artifact |
| Research-to-trading isolation | PASS | OBSERVE-only descriptive path |

## Automated reasoning

The fixed-cut population has strong identifier and case-link consistency, and
the bounded replay sample demonstrates deterministic core calculations and a
sound tested lookahead boundary. Those strengths do not overcome the failing
data and case gates.

The published coverage is below threshold. The 1,339 raw labels collapse to
554 underlying market windows before quality screening. Only 910 labels pass
the strict all-horizon/no-gap screen, representing 378 unique strict windows
and 14 greedy non-overlapping 30-minute windows. Negative/control cases,
rejected windows, regime labels, immutable edit history, representative
restart evidence, and independent human review are absent or incomplete.

The later live database count and the 8,347-trigger audit cannot rewrite the
frozen July case claim. Live evidence must be assessed under a prospectively
declared, frozen, hash-manifested scope.

## Evidence required before human reconsideration

1. Prospectively approved fixed qualifying window and analysis plan.
2. At least 95 percent governed continuous coverage with complete gap
   classification.
3. Prospective evidence produced under the repaired gap-sensitive validation,
   which requires all declared horizons and continuous source IDs.
4. At least 1,000 deduplicated, quality-screened independent cases under a
   predeclared rule.
5. Persisted negative/control and rejected/non-triggered sampling frames.
6. Volatility, liquidity, session, and temporal regime analysis.
7. Immutable or append-only mutation history and recoverable atomic
   persistence.
8. Full-population or reviewer-approved replay plus realistic restart/crash
   tests.
9. Executed deterministic manual-review sample with raw evidence.
10. Named independent reviewers, conflicts disclosed, adjudication recorded,
    and a separately signed human decision.

## Automated conclusion

Overall readiness status:

**NOT READY — DATA OR SCIENCE GATE FAILED**

The only automated recommendation is **MORE EVIDENCE REQUIRED**. The permitted
human decisions remain blank in
docs/v2_readiness/manual_scientific_approval_form.md.
