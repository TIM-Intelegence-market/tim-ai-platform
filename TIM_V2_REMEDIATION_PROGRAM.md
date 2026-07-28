# TIM V2 Readiness Remediation Program

## Program Charter

**Purpose:** Resolve the eight blockers recorded in
`TIM_V2_SCIENTIFIC_READINESS_ASSESSMENT.md`.  
**Current decision:** `NOT READY`  
**Authority:** Planning only  
**Core:** TIM Core 1.0 remains FROZEN and OBSERVE-only  
**Features, architecture and implementation:** Out of scope

## Program Outcomes

The program is complete only when:

1. every blocker has evidence-based disposition;
2. every P0 blocker is independently VERIFIED;
3. the manual Scientific Review is complete;
4. a new independent Readiness Assessment is performed;
5. no existing artifact is rewritten;
6. no status is automatically promoted.

This program itself closes no blocker.

## Baseline

| Measure | Baseline |
|---|---|
| Continuous Coverage | 60.659% |
| Coverage gate | ≥95.000% |
| Expected one-minute intervals | 1,093 |
| Persisted one-minute intervals | 663 |
| Missing one-minute intervals | 430 |
| Unresolved new DATA_GAPs | 63 |
| Validated cases | 1,339 |
| Artifact Audit | FAIL, 13/15 PASS |
| Research Quality | FAIL |
| Historical provenance | Incomplete |
| Manual Scientific Review | WAITING |
| HC-1.0 | Specification only; unapproved |
| Formal V2 RACI | Unassigned |

## Workstream 1 — Continuous Coverage

### Data Sources

Existing evidence only:

- persisted BTCUSDT closed one-minute candles;
- persisted AggTrades for source-boundary evidence;
- structured operational events;
- existing monthly snapshot/readiness artifacts.

No external substitute, synthetic interval, interpolation or reconstruction is
permitted.

### Measurement Method

1. Governance approves a prospective interval before final measurement.
2. Record `start_inclusive` and `end_exclusive` in UTC.
3. Calculate expected one-minute buckets:

   `expected = duration_in_minutes`.

4. Count distinct persisted closed BTCUSDT one-minute candle open times inside
   the interval.
5. Identify duplicates separately.
6. Enumerate every missing expected bucket.
7. Calculate:

   `coverage_percent = observed_distinct / expected * 100`.

8. Preserve expected, observed, missing, duplicate count and interval
   boundaries.

### Monitoring

- Hourly operational view: informational only.
- Daily immutable checkpoint: expected/observed/missing counts.
- Final frozen cut-off: authoritative.
- Monitoring-function health and monitored-data health are reported
  separately.

### Acceptance

- Coverage ≥95.000%.
- Full interval predefined.
- Zero estimated/reconstructed buckets.
- Counts independently reproducible.
- Every missing bucket linked to the Gap Register.

## Workstream 2 — DATA_GAP Resolution

### Register Construction

Use the template in `TIM_V2_BLOCKER_REGISTER.md`.

For each unique gap:

- preserve the original event reference;
- use persisted gap key where present;
- record begin/end/duration;
- record affected streams;
- classify cause as `KNOWN` or `UNKNOWN`;
- record recovery time;
- record observations not created for missing intervals;
- record scientific impact;
- prohibit reconstruction.

### Prioritization

| Priority | Definition |
|---|---|
| P0 | Gap inside the qualifying scientific window; unresolved cause or disposition |
| P1 | Historical gap outside the qualifying window with incomplete documentation |
| P2 | Duplicate notification of an already registered gap; source event preserved |

### Verification

QA reconciles:

- distinct gap keys;
- overlapping intervals;
- candle cadence;
- event counts;
- qualifying-window unresolved count.

Success requires zero unresolved new P0 gaps at the final cut-off.

## Workstream 3 — Audit FAIL

### Missing Evidence

- Legacy Module-A records missing artifact hash, generator version and schema
  version.
- No approved disposition record separating legacy documentation absence from
  present-scope integrity.
- No approved V2 artifact-type registry.
- No HC-1.0 conformance fixture pack.

### Existing Evidence

- Readiness artifact self-hash verified.
- Insights output hash verified in its own domain.
- P0 mismatch reproducibly classified as a cross-domain false positive.
- Historical audit remains unmodified.

### Required Planning Actions

1. Map every audit issue to:
   - genuine integrity failure;
   - legacy documentation limitation;
   - validator semantic false positive;
   - unresolved issue.
2. Reference exact source hashes.
3. Obtain independent Governance Audit.
4. Retain FAIL where the historical validator reports FAIL.
5. Define future V2-only verification expectations under approved HC-1.0.

No audit code or historical artifact is changed by this program.

## Workstream 4 — Quality FAIL

### Quality Metric Catalogue

| Metric | Required evidence | Gate |
|---|---|---|
| Schema validity | Persisted audit/quality evidence | No unresolved P0 schema issue |
| Timestamp integrity | Fixed-cut-off sequence check | PASS |
| Forward-only | Scientific validation/replay | PASS |
| OBSERVE-only | Manifest and event evidence | PASS; zero execution events |
| Coverage | Workstream 1 | ≥95.000% |
| DATA_GAP status | Workstream 2 | Zero unresolved new gaps |
| Provenance | Workstream 5 | 100% prospective scope |
| Replay | Existing/final fixed input | Identical |
| Hash semantics | P0 RCA and HC-1.0 disposition | Unambiguous |
| Documentation | Evidence registry | Complete chain |

Quality cannot become VERIFIED until dependent workstreams are verified.

## Workstream 5 — Historical Provenance

### Provenance Checklist

Present where available:

- provenance/source identifier;
- dataset/input hash;
- artifact/report hash;
- schema version;
- generator version;
- generation timestamp;
- validation status.

Known missing:

- 1,602 current-cut-off legacy Module-A records lack `artifact_hash`,
  `generator_version` and `schema_version`;
- historical Acceptance provenance totals fail;
- historical Research Case provenance totals fail.

Classification:

| Class | Treatment |
|---|---|
| Complete prospective provenance | Eligible for future isolated V2 evidence scope |
| Partial legacy provenance | Retain and document |
| Permanently non-reconstructable | Mark limitation; never infer/backfill |
| Conflicting provenance | Escalate to Integrity Lead; exclude from qualifying scope until disposition |

Success is not retroactive perfection. Success is:

- complete inventory;
- explicit legacy limitations;
- unchanged historical bytes;
- 100% provenance for the prospective V2 evidence scope.

## Workstream 6 — Scientific Review

### Reviewer Roles

- Scientific Lead — accountable chair.
- Integrity Lead — evidence integrity.
- QA Lead — independent verification.
- Research Lead — scientific artifact context.
- Core Owner — freeze boundary.
- Governance Auditor — process independence.
- Release Authority — decision authority.

### Review Scope

- fixed evidence cut-off;
- coverage and gaps;
- provenance;
- deterministic replay;
- P0 disposition;
- audit and quality status;
- version isolation;
- OBSERVE-only;
- known limitations;
- HC-1.0 decision;
- RACI and segregation.

### Review Protocol

1. Freeze evidence pack.
2. Verify hashes.
3. Distribute checklist.
4. Record independent findings.
5. Convene review.
6. Record dissent.
7. Decide only:
   - NOT READY;
   - CONDITIONALLY READY;
   - READY FOR V2 PLANNING.
8. State explicitly that planning does not authorize implementation.

## Workstream 7 — HC-1.0 Governance

Follow `TIM_V2_GOVERNANCE_APPROVAL_WORKFLOW.md`.

Required decisions:

- approve/revise/reject HC-1.0;
- require artifact-type registry;
- require conformance fixtures;
- approve legacy isolation;
- approve V2-only implementation boundary;
- approve future cut-over policy.

No contract implementation occurs in this program.

## Workstream 8 — Responsibility Matrix

Use `TIM_V2_RACI_MATRIX.md`.

Completion requires:

- named holder and alternate for each mandatory role;
- acceptance of responsibility;
- conflict declaration;
- verified segregation;
- Release Authority approval.

## Roadmap

### Phase 1 — Integrity

**Blockers:** V2-B03, V2-B04, V2-B05

Deliverables:

- evidence freeze;
- audit disposition matrix;
- provenance inventory;
- quality metric catalogue;
- documentation supersession map.

Exit criteria:

- evidence scopes explicit;
- P0 hash interpretation reconciled;
- no historical rewrite;
- dependent issues ready for verification.

### Phase 2 — Coverage

**Blockers:** V2-B01, V2-B02

Deliverables:

- approved qualifying interval;
- daily coverage checkpoints;
- complete Gap Register;
- independent final coverage verification.

Exit criteria:

- ≥95.000% coverage;
- zero unresolved new gaps;
- no reconstruction;
- fixed evidence cut-off.

### Phase 3 — Governance

**Blockers:** V2-B07, V2-B08

Deliverables:

- named RACI;
- HC-1.0 approval decision;
- registry/fixture requirements;
- revision history;
- governance audit.

Exit criteria:

- roles assigned;
- segregation verified;
- exact specification hash approved/rejected;
- implementation authority remains separate.

### Phase 4 — Scientific Review

**Blocker:** V2-B06

Deliverables:

- immutable review pack;
- completed Readiness checklist;
- reviewer findings;
- signed Scientific Review decision.

Exit criteria:

- every P0 blocker VERIFIED;
- limitations recorded;
- decision scope explicit.

### Phase 5 — Final Readiness Assessment

Deliverables:

- independent re-assessment;
- final Readiness matrix;
- risk disposition;
- Release Authority decision.

Possible decisions:

- NOT READY;
- CONDITIONALLY READY;
- READY FOR V2 PLANNING.

No decision in this phase automatically authorizes V2 implementation.

## Program Controls

- Weekly blocker review while any P0 is OPEN/IN_PROGRESS.
- Every status transition references immutable evidence.
- No metric may be manually overwritten.
- No blocker closes automatically.
- Core Owner reviews every proposed activity for freeze-boundary impact.
- Any activity requiring Core, Validator, Snapshot, Replay, Manifest or Hash
  Contract changes stops and returns to Governance.

## Deliverable Map

| Deliverable | Purpose |
|---|---|
| `TIM_V2_REMEDIATION_PROGRAM.md` | Program charter and phased plan |
| `TIM_V2_BLOCKER_REGISTER.md` | Authoritative blocker definitions/status |
| `TIM_V2_RACI_MATRIX.md` | Responsibility and segregation model |
| `TIM_V2_GOVERNANCE_APPROVAL_WORKFLOW.md` | Approval/rejection/revision process |
| `TIM_V2_READINESS_CHECKLIST.md` | Manual evidence verification gate |

## Current Program Status

All blockers remain OPEN:

- V2-B01: **OPEN**
- V2-B02: **OPEN**
- V2-B03: **OPEN**
- V2-B04: **OPEN**
- V2-B05: **OPEN**
- V2-B06: **OPEN**
- V2-B07: **OPEN**
- V2-B08: **OPEN**

## STATUS

**V2 REMEDIATION PROGRAM READY**
