# TIM V2 Manual Scientific Review Packet

Artifact status: **PENDING HUMAN REVIEW**

Mode: **OBSERVE**

This packet assembles the evidence a named, independent human reviewer needs
to assess TIM V2 scientific readiness. It intentionally exposes failing and
unproven gates. It is not a review decision, signature, approval, or
authorization.

The reviewer should use:

- the blank form at
  docs/v2_readiness/manual_scientific_approval_form.md; and
- the deterministic sample specification at
  artifacts/v2_readiness/manual_review_sample_manifest.json.

## 1. Research objective

Determine whether TIM's descriptive orderflow observations and later
5/15/30-minute outcomes are reproducible, temporally valid, sufficiently
complete, appropriately deduplicated, and scientifically reviewable for a V2
readiness decision.

## 2. Scope

The primary case audit is frozen at 2026-07-23T14:27:42.127641Z and covers
Binance Spot BTCUSDT, 60-second orderflow observations from
2026-07-22T21:29:00Z through 2026-07-23T13:57:00Z. Later operational and replay
evidence is explicitly identified as such and does not alter the frozen case
population.

## 3. Non-goals

This review does not:

- change or approve Core 1.0;
- authorize forecasting, execution, orders, positions, or capital allocation;
- treat descriptive outcomes as trading efficacy;
- merge the frozen July population with later live data;
- infer missing source data; or
- substitute an automated assessment for independent human review.

## 4. Data sources

Primary evidence includes persisted Binance Spot aggregate trades, derived
closed one-minute candles, orderflow observations, orderflow validations,
research cases, trigger events, Module A cache records, frozen research
artifacts, repository code, and targeted tests.

The fixed population was reconstructed using complete validations whose
validated_through timestamp was at or before the fixed case cut-off.

## 5. Periods and evidence cuts

| Evidence | Period/cut |
|---|---|
| Frozen published coverage | 2026-07-22T20:14:00Z inclusive to 2026-07-23T14:27:00Z exclusive |
| Frozen case population | Validated through 2026-07-23T14:27:42.127641Z |
| Frozen case observation span | 2026-07-22T21:29:00Z to 2026-07-23T13:57:00Z |
| Operational baseline | 2026-08-01T15:00:43.767881Z |
| Replay/sample selection cut | 2026-08-01T15:01:00Z; separate current-cut population |

## 6. Coverage definition

The readiness coverage unit is a distinct, valid, closed BTCUSDT one-minute
interval backed by the authoritative source. The fixed window uses a
start-inclusive/end-exclusive UTC interval. Duplicates and synthetic or
forward-filled intervals are excluded. The documented gate is at least 95
percent continuous qualifying coverage, subject to an approved prospective
window.

## 7. Coverage result

The frozen published result is 663/1,093 = 60.659 percent. The separate
same-start extension at the operational baseline is 9,487/14,087 = 67.346
percent, with 4,600 missing minutes. Both are below 95 percent. The extension
does not replace the frozen value, and no prospectively approved qualifying
window is present.

## 8. Gap ledger

The operational extension contains 283 canonical missing ranges; the largest
is 685 minutes. At the frozen case cut, the aggregate-trade sequence audit
found 39 discontinuity events containing 158,066 missing aggregate trade IDs,
with a largest single ID gap of 13,222. A total of 429 fixed-cut labels overlap
a discontinuity in their two-minute input or 30-minute outcome interval.

## 9. Root-cause analysis

The available evidence demonstrates persisted interval and aggregate-ID
discontinuities. All 283 current minute-gap ranges have a technical process-
downtime classification, but only two are confirmed and 281 remain probable
without independent disposition. The reviewer should not promote a probable
classification to scientific acceptance without linked evidence and sign-off.

## 10. Backfill provenance

No data backfill, synthetic interval, forward fill, or reconstruction was
performed as part of this audit. The baseline manifest records zero synthetic
intervals. Any future backfill must be separately versioned, source-authorized,
hash-manifested, and approved before it is eligible for a readiness window.

## 11. Case-count audit

| Stage | Count |
|---|---:|
| Raw complete validation labels | 1,339 |
| Unique source windows/observation times | 554 |
| Strict all-horizon, no-gap labels | 910 |
| Strict unique source windows | 378 |
| Strict non-overlapping 30-minute windows | 14 |
| Required independent quality cases | 1,000 |

The case gate fails. The raw label count is not an independent case count.
Details and distributions are in
docs/v2_readiness/validated_case_quality_report.md.

## 12. Representative sample

The sample manifest contains an executed deterministic 24-stratum automated
selection from the separate current-cut population at 2026-08-01T15:01:00Z:
one replay-passing case for every observation-kind × descriptive outcome
combination. It records exact IDs and hashes, source-window signatures,
sessions, horizons, temporal distance and the captured replay reference. All 24
strata were filled; its sample hash covers selected cases only, not the source
scope, packet metadata or raw trades.

This current-cut selection is only preparation for review. It does not alter or
merge into the frozen 1,339-label gate population. Repeated or overlapping
source windows are disclosed and do not contribute to the independent-case
gate. The referenced replay summary does not embed raw trades, so a human must
obtain and independently bind any raw evidence used for a decision. No human
has accepted or labelled any selected case; the status therefore remains
`PENDING HUMAN REVIEW` and all reviewer/signature fields remain empty.

## 13. Negative cases

There is no preregistered positive/negative hypothesis label in this case
schema. PRICE_INCREASED, PRICE_DECREASED, and PRICE_SIDEWAYS are descriptive
post-observation outcomes, not hypothesis truth values. A negative/control
sampling frame must be defined prospectively.

## 14. Rejected and non-triggered cases

Rejected and non-triggered market windows are not persisted as a reviewable
population. Because only detector-fired observations are retained, the total
eligible opportunity set and detector false-positive/false-negative rates
cannot be calculated.

## 15. Bias risks

- detector-fired-only selection;
- repeated labels on the same underlying market minute;
- heavy concentration in LARGE_INDIVIDUAL_TRADE_ACTIVITY;
- one market, symbol, and timeframe;
- only 16 hours 28 minutes of case observations;
- imbalanced UTC session and outcome counts;
- absent volatility/liquidity regime labels;
- absent negative/control windows;
- mutable validation rows without actor/update history; and
- post hoc descriptive outcomes without a preregistered hypothesis.

## 16. Lookahead review

The sampled validator replay enforced:

- baseline trade at or before observation time;
- outcome trades strictly after observation time;
- target horizon at or before as_of; and
- no use of pre-30-minute state to satisfy the 30-minute horizon.

All 24 sampled cases passed this boundary. Human review should independently
inspect the selected raw trade intervals and reproduce the boundary.

## 17. Leakage review

Observation generation uses adjacent prior/current metric windows and
descriptive fixed conditions. Validation uses later trades. No trading action
consumes the research result. Remaining leakage risks are governance-level:
post hoc case selection, absent rejected-window population, potential reuse of
overlapping windows across labels, and mutable persisted validation state.

## 18. Replay evidence

A deterministic current-cut 24-case sample passed all 24 strata for observation
input-hash equality, validation-hash equality, reversed-input invariance, source
ID continuity, the 29-minute pre-cutoff check and OBSERVE mode. The replay
artifact does not persist a full-row or baseline-numeric equality assertion.
Later live trigger lineage recomputed 8,347/8,347 artifact identifiers. A
preceding relationship snapshot identified 73 early eligible observations
without trigger events.

These are bounded replay results, not a complete study replay.

## 19. Determinism boundaries

Scientific payloads and identifiers are deterministic in the tested scope.
Full envelopes are not byte-deterministic because created_at and triggered_at
use wall clock time and persisted trigger state suppresses repeats. Module A
cache records lack artifact hash/schema/generator metadata, and the trigger,
cache, and case writes are not one atomic hash-chained transaction.

## 20. Limitations

- Fixed case population was reconstructed rather than supplied as an original
  immutable per-case manifest.
- Coverage is below the documented threshold.
- Gap causes are technically classified but not independently approved.
- Gap-sensitive abstention is implemented prospectively for aggregate-trade ID
  discontinuities; historical validations remain unchanged and fail audit.
- Strict case count is below 1,000 before independence is considered.
- Regime labels and negative/control sampling are absent.
- No complete edit history or inter-rater evidence exists.
- One bounded restore and controlled launchd restart pass; exhaustive crash
  boundaries and source catch-up remain untested.
- V2 registry replay is PLANNED_REPLAY_ONLY.
- The pre-remediation active-database run had two setup errors; the final
  disposable-schema suite passed 362/362 without touching production data.

## 21. Scientific debt

Before an affirmative readiness decision, the review team should require:

1. a preregistered objective, hypothesis, outcomes, exclusions, and analysis;
2. a prospectively approved, frozen, hash-manifested qualifying window;
3. continuous source coverage at or above the governed threshold;
4. validator quarantine/abstention on source gaps and incomplete horizons;
5. at least 1,000 quality-screened independent cases under a predeclared
   independence rule;
6. persisted rejected/non-triggered and negative/control windows;
7. volatility, liquidity, date, and session regime analysis;
8. append-only actor/reason/update history and atomic or recoverable
   persistence;
9. representative restart/crash and full-study replay tests; and
10. independent named reviewers with conflict disclosures and adjudication.

## 22. Questions for human reviewers

1. Is the research objective sufficiently precise and prospectively testable?
2. Is the fixed-cut reconstruction acceptable without an original per-case
   immutable manifest?
3. Are the coverage and aggregate-ID gaps fatal for this evidence window?
4. Is observed_at an adequate source-window deduplication key for this
   one-market, one-timeframe design?
5. Is a 30-minute separation sufficient, or should independence use a longer
   embargo/block rule?
6. Does the proposed stratified sample expose enough positive, negative,
   sideways, session, and observation-kind variation?
7. Are the 24-case replay and trigger lineage checks sufficient, or is full
   population replay required?
8. How must rejected/non-triggered controls and market regimes be added?
9. Is the absence of orderflow confidence fields acceptable under the
   scientific constitution?
10. What exact remediation and re-review evidence is required?

## 23. Human decision options

The human review form permits exactly one of:

- APPROVED
- APPROVED WITH CONDITIONS
- REJECTED
- MORE EVIDENCE REQUIRED

No option is selected in this packet or the blank form. All reviewer identity,
conflict, rationale, condition, dissent, date, and signature fields must be
completed by authorized humans.

## Evidence index

- docs/v2_readiness/pre_remediation_baseline.md
- artifacts/v2_readiness/baseline_manifest.json
- docs/v2_readiness/validated_case_quality_report.md
- docs/v2_readiness/observation_research_integrity_review.md
- artifacts/v2_readiness/manual_review_sample_manifest.json
- docs/v2_readiness/manual_scientific_approval_form.md
- docs/v2_readiness/automated_scientific_pre_review.md
- TIM_V2_READINESS_CHECKLIST.md
- TIM_V2_RACI_MATRIX.md

Governance state at packet creation: checklist sections NOT VERIFIED, named
role holders UNASSIGNED, G0/G1/G3 OPEN, G2/G4/G5 BLOCKED, and
data/research/status/manual_scientific_review.json absent.
