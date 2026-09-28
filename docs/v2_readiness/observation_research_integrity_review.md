# TIM V2 Observation and Research Integrity Review

Status: **PARTIAL — CORE REPLAY EVIDENCE PASSES; END-TO-END INTEGRITY IS NOT PROVEN**

Mode: **OBSERVE**

This is a technical/scientific integrity review, not a human approval. It
separates verified event-time behavior from unresolved persistence,
completeness, auditability, and restart risks.

## 1. Reviewed paths

Two related but distinct paths were inspected:

1. persisted aggregate trades → orderflow metrics → descriptive orderflow
   observation → research case → 5/15/30-minute validation; and
2. persisted candle observation → trigger event → Module A/Module B research
   artifact.

Both paths remain external to Core decision logic and operate in OBSERVE mode.
No inspected research or trigger result creates an order, position, capital
allocation, or trading action.

## 2. Deterministic replay sample

A deterministic 24-case live sample selected one case for each available
combination of eight orderflow observation kinds and three descriptive
outcomes. Selection used lexicographic observation-ID ordering and the first
exact-replay-passing candidate among the first 25 per stratum, rather than
manual choice or hash ordering.

| Replay comparison | Result |
|---|---:|
| Selected kind × outcome strata | 24/24 |
| Observation input-hash equality | 24/24 |
| Validation-hash equality | 24/24 |
| Observation and validation reversed-input equality | 24/24 |
| Source aggregate-trade-ID continuity | 24/24 |
| No completeness at the 29-minute pre-cutoff | 24/24 |
| OBSERVE mode | 24/24 |

This supports exact input/validation hash replay, input-order invariance and the
tested pre-cutoff boundary for the sample. The persisted artifact does not claim
full-row or baseline-numeric equality and does not establish representativeness
of the population, source completeness outside the selected intervals, restart
safety, or human scientific acceptance.

The final targeted science set passed 68/68 with no failures, skips, XFAIL or
XPASS. Two independent fixed-cut replay executions each selected all 24 strata
and produced the identical replay hash
`152e1f61a3c141782b28e22670ba29ea102d37daf98946a1c5970524263f4182`.
The complete project suite passed 362/362 in a disposable PostgreSQL schema;
the pre-remediation active-database setup errors are retained only as baseline
evidence.

## 3. Event-time and lookahead boundary

Verified properties:

- metric windows are half-open at their boundary;
- the baseline trade is at or before the observation time;
- outcome trades are strictly after the observation and at or before the
  requested horizon;
- a target horizon is evaluated only when target time is at or before as_of;
- mixed-symbol validation input is rejected;
- duplicate aggregate-trade identities are rejected; and
- input order is sorted deterministically before validation;
- future input rows are discarded at the validation cut-off; and
- future `complete=true` requires all 5/15/30 horizons and a contiguous
  aggregate-trade-ID sequence.

No sampled pre-horizon trade was allowed to satisfy the 30-minute result. The
tested lookahead boundary therefore passes.

## 4. Trigger lineage

In the later live relationship audit, 8,347 persisted trigger events were
independently recomputed and matched their deterministic artifact identifiers
8,347/8,347. A preceding consistent snapshot contained 8,342 trigger events
against 8,415 eligible observations and exposed 73 eligible observations from
2026-07-20T13:51:00Z through 2026-07-20T15:45:00Z with no trigger event.

The 8,347 result is a later live integrity finding. It is not part of the
frozen 1,339-case cut and must not be used to change that historical count.

All inspected trigger events mapped to a Module A cache record and no
duplicate trigger identity was found in the audited relationship set.
However:

- Module A cache records lacked artifact_hash, schema_version, and
  generator_version;
- trigger state, trigger log, cache write, and case database write are not one
  atomic or hash-chained transaction;
- created_at and triggered_at use wall-clock values, so full serialized
  trigger/report objects are not byte-identical across fresh runs; and
- a second identical trigger is intentionally suppressed by persisted state.

The deterministic scientific payload/identifier is stronger than the
determinism of the full persisted envelope.

## 5. Gap sensitivity and abstention

The **historical evidence fails** gap sensitivity. Before remediation, a record
could be marked complete when a 30-minute result existed even if intermediate
horizons or source continuity were absent. The final prospective validator now
requires all 5/15/30-minute horizons, rejects future rows, and requires a
continuous aggregate-trade-ID sequence before `complete=true`. This code fix
does not retroactively repair or reclassify frozen historical validations.

At the frozen cut:

- 64 of 1,339 labels lacked at least one of the required 5/15/30 horizons;
- 429 labels overlapped a source discontinuity in their input or outcome
  interval;
- only 910 labels passed the strict all-horizon/no-gap screen;
- those labels represented 378 unique source windows; and
- only 14 strict windows survived a greedy 30-minute non-overlap screen.

These findings prevent a raw complete=true count from serving as scientific
eligibility evidence.

## 6. Mutation and audit-history risk

The statement “no hidden manual changes” is **not proven**:

- validation persistence uses an upsert that can replace horizons, outcome,
  validation hash, and validated-through time;
- the schema has no actor, reason, prior-value, or append-only update history
  for that replacement;
- research cache/log files are plaintext and are not hash-chained; and
- there is no atomic transaction spanning the entire trigger/research
  persistence path.

The current relationships are consistent where tested, but the available
evidence cannot distinguish every legitimate recomputation from an
undocumented historical edit.

## 7. Observation/interpretation separation

Orderflow observation descriptions use descriptive language and do not claim
a forecast or trade setup. Outcome labels summarize later price movement.
Research output remains separate from trading action.

One schema inconsistency remains: the authoritative scientific constitution
requires an observation confidence field, while persisted orderflow
observations do not contain one. Confidence semantics therefore need either an
explicit, reviewed exemption or a versioned schema addition.

## 8. Restart and bounded-load behavior

Restart integrity is **not proven** for realistic history despite bounded
passing evidence:

- an isolated active raw-bucket replay test and one controlled launchd restart
  pass;
- runtime restoration is bounded to 1,000 cases and 500 orderflow
  observations/validations;
- there is no tested restart with a backlog above those limits; and
- there is no crash-consistency test across trigger state, JSONL caches, and
  case persistence.

The V2 research registry currently reports PLANNED_REPLAY_ONLY rather than
performing a full study replay. It is evidence of intent, not execution.

## 9. Test and implementation hazards

- tests/test_research_insights.py contains a reversed-input branch disabled by
  an if False condition; that specific test does not exercise its intended
  reversal.
- ResearchInsightsEngine treats source_window_complete as true when the field
  is omitted.
- Its coverage eligibility check requires a coverage value to be present but
  does not itself enforce the documented 95 percent threshold.
- Dashboard restoration truncation can make an in-memory view look complete
  only because it has reached its load limit.

## 10. Gate assessment

| Integrity question | Assessment | Basis |
|---|---|---|
| Core sampled observation replay | PASS | 24/24 observation input-hash equality |
| Core sampled validation replay | PASS | 24/24 validation-hash equality |
| Input-order invariance | PASS in sample | 24/24 reversed/out-of-order equality |
| Lookahead boundary | PASS in sample | 24/24 pre-30m cut-off enforced |
| Source-gap sensitivity | PASS prospective code / FAIL frozen evidence | final code requires 5/15/30 plus contiguous source IDs; historical rows are unchanged |
| Fixed case quality/independence | FAIL | 910 strict labels, 378 strict windows, 14 non-overlapping windows |
| Trigger identifier lineage | PASS in audited live set | 8,347/8,347 recomputed identifiers |
| Trigger-to-case atomicity | NOT PROVEN | multiple non-atomic stores |
| Immutable edit history | NOT PROVEN | mutable upsert and no actor/history chain |
| Restart above load limits | NOT PROVEN | no representative backlog/crash test |
| Negative/control sampling | ABSENT | fired observations only |
| Human scientific review | PENDING | no completed signed review |
| Trading isolation | PASS | descriptive OBSERVE-only path, no trading action |

## 11. Conclusion

The sampled core calculations show strong deterministic replay and event-time
discipline. The end-to-end scientific evidence remains **PARTIAL** because
historical gap-sensitive eligibility fails, history is mutable without a
complete audit chain, restart behavior is under-tested, and manual review is
absent. The prospective abstention repair does not promote the frozen evidence.

This review provides no human decision and no V2 approval.

## 12. Evidence references

- docs/v2_readiness/validated_case_quality_report.md
- docs/v2_readiness/pre_remediation_baseline.md
- docs/v2_readiness/manual_scientific_review_packet.md
- src/orderflow/metrics.py
- src/orderflow/observations.py
- src/orderflow/validation.py
- src/database/repository.py
- src/research/trigger.py
- src/research/module_a/agent.py
- src/insights/engine.py
- src/dashboard/app.py
- tests/test_research_insights.py
