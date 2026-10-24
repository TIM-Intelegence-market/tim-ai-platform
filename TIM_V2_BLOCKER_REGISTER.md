# TIM V2 Blocker Register

**Program:** TIM V2 Readiness Remediation  
**Baseline:** `TIM_V2_SCIENTIFIC_READINESS_ASSESSMENT.md`  
**Core:** TIM Core 1.0, FROZEN, OBSERVE-only  
**Register status:** Initial planning baseline

## Status Model

Every blocker has exactly one status:

- `OPEN`
- `IN_PROGRESS`
- `BLOCKED`
- `READY_FOR_VERIFICATION`
- `VERIFIED`
- `CLOSED`

Status changes require an evidence reference, timestamp, accountable role and
approver. No blocker is closed by this document.

## Register

| Blocker ID | Description | Priority | Accountable role | Dependencies | Status |
|---|---|---:|---|---|---|
| V2-B01 | Continuous Coverage below 95% | P0 | Scientific Lead | Stable observation window; V2-B02 | **OPEN** |
| V2-B02 | 63 unresolved new DATA_GAPs | P0 | Integrity Lead | Gap register; operational evidence | **OPEN** |
| V2-B03 | Artifact Audit is FAIL | P0 | Integrity Lead | V2-B05; V2-B07 | **OPEN** |
| V2-B04 | Research Quality is FAIL | P0 | QA Lead | V2-B01; V2-B02; V2-B03; V2-B05 | **OPEN** |
| V2-B05 | Historical Provenance incomplete | P1 | Research Lead | Legacy classification policy | **VERIFIED** (2026-10-24, see section) |
| V2-B06 | Manual Scientific Review absent | P0 | Scientific Lead | V2-B01–B05, B07, B08 | **OPEN** |
| V2-B07 | HC-1.0 governance approval absent | P0 | Governance Lead | Approval workflow; registry/fixture proposals | **OPEN** |
| V2-B08 | Formal V2 responsibility matrix absent | P0 | Governance Lead | Named role assignments | **OPEN** |

## V2-B01 — Continuous Coverage

- **Description:** Continuous one-minute coverage is 60.659%; the gate is at
  least 95%.
- **Cause:** 663 of 1,093 expected one-minute intervals were persisted in the
  assessed continuous window; 430 were absent.
- **Impact:** Scientific continuity and V2 Readiness cannot pass.
- **Evidence:** `data/research/status/tim_v1_readiness.json`;
  `data/research/snapshots/2026-07.in_progress.json`;
  `TIM_V2_SCIENTIFIC_READINESS_ASSESSMENT.md`.
- **Responsible role:** Scientific Lead (accountable), Validator Owner and
  Integrity Lead (responsible for measurement/verification).
- **Dependencies:** V2-B02; immutable cut-off; unchanged Core 1.0 operation.
- **Measures:** Define one prospective qualifying interval; measure expected
  versus observed closed BTCUSDT one-minute intervals; monitor without
  reconstruction; preserve raw counts and gaps.
- **Success criteria:** Coverage ≥95.000% for the complete predefined
  interval; numerator, denominator, boundaries and missing ranges reproducible;
  no estimated or reconstructed interval.
- **Verification:** Integrity Lead independently recomputes the minute grid
  from persisted state at the frozen cut-off; QA compares the result to the
  submitted coverage artifact.
- **Closure evidence:** Content-addressed coverage evidence pack, independent
  verification record and Scientific Lead acceptance.
- **Priority:** P0
- **Status:** **OPEN**

## V2-B02 — DATA_GAPs

- **Description:** 63 new DATA_GAPs remain unresolved at the Readiness cut-off.
- **Cause:** Evidence records source/persistence gaps and public-stream
  disconnections; a complete root cause is not recorded for every gap.
- **Impact:** Coverage claims remain incomplete; observations cannot exist for
  missing intervals.
- **Evidence:** `data/operational/events.jsonl`;
  `data/research/status/tim_v1_readiness.json`;
  `docs/TIM_V1_SCIENTIFIC_VALIDATION_2026-07-23.md`.
- **Responsible role:** Integrity Lead.
- **Dependencies:** Immutable Gap Register; Validator Owner evidence; no
  reconstruction.
- **Measures:** Register every unique gap; deduplicate by persisted gap key;
  classify source, persistence, controlled interruption or unknown; attach
  affected streams, interval, recovery and scientific impact; preserve
  unknown causes explicitly.
- **Success criteria:** Every gap has one register entry, evidence reference,
  reproducible interval, cause status and disposition; final qualifying window
  has zero unresolved new gaps.
- **Verification:** QA independently reconciles register keys and intervals
  against persisted events and candle cadence.
- **Closure evidence:** Signed Gap Register verification and zero-unresolved
  count for the frozen qualifying window.
- **Priority:** P0
- **Status:** **OPEN**

## V2-B03 — Artifact Audit FAIL

- **Description:** Current artifact audit reports 13/15 PASS and overall FAIL.
- **Cause:** 1,602 legacy Module-A records lack required documentation; the
  known `OUTPUT_HASH_MISMATCH` is a deterministic cross-domain false positive.
- **Impact:** No clean audit gate or unambiguous technical evidence pack.
- **Evidence:** `data/research/audit/latest.json`;
  `TIM_OUTPUT_HASH_ROOT_CAUSE_REPORT.md`.
- **Responsible role:** Integrity Lead.
- **Dependencies:** V2-B05 legacy disposition; V2-B07 prospective hash
  governance; no Core 1.0 rewrite.
- **Measures:** Produce a read-only audit disposition matrix; separate genuine
  integrity failures, legacy documentation limitations and known validator
  false positives; define evidence required for a future V2-only validator.
- **Success criteria:** Every audit issue has a governance-approved
  classification and disposition; no issue is hidden or manually converted to
  PASS; future V2 evidence pack contains no ambiguous hash comparison.
- **Verification:** Independent Governance Auditor checks classifications
  against source artifacts and the P0 RCA.
- **Closure evidence:** Approved audit disposition record and independent
  verification; historical audit remains unchanged.
- **Priority:** P0
- **Status:** **OPEN**

## V2-B04 — Research Quality FAIL

- **Description:** Current Research Quality status is FAIL.
- **Cause:** Quality inherits artifact-audit failures and records open gaps,
  provenance limitations and other evidence deficiencies.
- **Impact:** Scientific Readiness cannot claim complete quality.
- **Evidence:** `data/research/quality/latest.json`;
  `docs/TIM_FINAL_SCIENTIFIC_RECONCILIATION_REPORT.md`.
- **Responsible role:** QA Lead.
- **Dependencies:** V2-B01, V2-B02, V2-B03 and V2-B05.
- **Measures:** Establish a fixed quality metric catalogue; map each current
  issue to evidence and owner; verify schema, timestamp integrity,
  forward-only behavior, OBSERVE-only, coverage, gaps, provenance, replay and
  hash-domain disposition.
- **Success criteria:** All required metrics have reproducible inputs,
  definitions and acceptance criteria; all P0 quality issues are verified or
  formally retained as explicit legacy limitations; no open issue is omitted.
- **Verification:** QA reruns only the approved read-only checks at a frozen
  cut-off; Integrity Lead verifies hashes and issue counts.
- **Closure evidence:** Signed quality verification pack with zero unresolved
  P0 quality issue in the prospective V2 evidence scope.
- **Priority:** P0
- **Status:** **OPEN**

## V2-B05 — Historical Provenance

- **Description:** Historical provenance is incomplete.
- **Cause:** Legacy artifacts and operational records predate final provenance
  metadata requirements.
- **Impact:** Historical claims cannot all be traced to current provenance
  standards; the 72-hour Acceptance provenance criteria remain FAIL.
- **Evidence:** `docs/TIM_72H_ACCEPTANCE_REPORT.md`;
  `data/research/audit/latest.json`;
  `docs/TIM_FINAL_SCIENTIFIC_RECONCILIATION_REPORT.md`.
- **Responsible role:** Research Lead.
- **Dependencies:** Legacy classification policy; V2 scope isolation.
- **Measures:** Inventory present and missing provenance fields; classify
  permanently non-reconstructable records; identify new-scope artifacts with
  complete provenance; prohibit backfill and retroactive assertions.
- **Success criteria:** 100% of records in the prospective V2 evidence scope
  carry required provenance; every historical deficiency is counted and
  classified; no historical record is rewritten.
- **Verification:** Integrity Lead compares inventory to persisted records and
  confirms byte/hash preservation of legacy evidence.
- **Closure evidence:** Approved provenance inventory, legacy limitation
  statement and V2-scope boundary.
- **Priority:** P1
- **Status:** **VERIFIED**
- **Status change (2026-10-24T01:04:15Z, OPEN → VERIFIED):**
  - Evidence: `docs/v2_readiness/historical_provenance_inventory.md`; writer fix
    and read-only inventory in PR #379 (merge 59388dd), live on the Mac since
    2026-10-24T00:51Z; inventory file on the Mac
    `~/Library/Application Support/TIM/provenance/inventory-2026-10-24.json`.
  - Inventory at cut-off 2026-10-24T00:51:30Z: 3,302 cache records,
    3,301 PARTIAL_LEGACY, 1 COMPLETE_PROSPECTIVE, 0 NON_RECONSTRUCTABLE,
    0 CONFLICTING, prospective scope 100 % complete, `bytes_unchanged: true`.
  - V2-scope boundary: 2026-10-24T00:51:14.905971Z (first record with all
    V2 fields). The earlier 2026-09-01 boundary is withdrawn because it was
    never enforced.
  - Legacy limitation: the 3,301 earlier records stay unchanged, are not
    backfilled and remain documented as a limitation.
  - Approver: project owner (Uzi), decision in the project thread,
    2026-10-24T01:04:15Z.
  - Limitation of the verification: the byte/hash preservation check is the
    inventory's own before/after hashing. A separate check by the Integrity
    Lead has not been done yet and can still be added.

## V2-B06 — Manual Scientific Review

- **Description:** The binding manual Scientific Review is `WAITING`.
- **Cause:** Prerequisite evidence gates remain incomplete and no review panel
  decision exists.
- **Impact:** No authorized transition to V2 planning or development.
- **Evidence:** `data/research/status/tim_v1_readiness.json`;
  `docs/TIM_CORE_1_0_FREEZE.md`.
- **Responsible role:** Scientific Lead.
- **Dependencies:** Verified disposition of V2-B01–B05, V2-B07 and V2-B08.
- **Measures:** Convene independent review panel; distribute immutable
  evidence pack; complete checklist; record dissent, limitations and decision.
- **Success criteria:** Every mandatory criterion is evaluated; all P0
  blockers are VERIFIED; decision is signed and explicitly limited to planning
  or development authority.
- **Verification:** Release Authority validates panel composition, evidence
  hashes and checklist completeness.
- **Closure evidence:** Signed Scientific Review protocol and decision.
- **Priority:** P0
- **Status:** **OPEN**

## V2-B07 — HC-1.0 Governance

- **Description:** HC-1.0 exists as a specification but is not approved.
- **Cause:** Required governance decisions, registry and conformance fixtures
  are absent.
- **Impact:** V2 hash semantics cannot be implemented under an authorized,
  testable contract.
- **Evidence:** `TIM_HASH_CONTRACT_SPECIFICATION_V2.md`, section 17.
- **Responsible role:** Governance Lead.
- **Dependencies:** V2-B08; independent Integrity and QA review.
- **Measures:** Execute the approval workflow; review scope, domain rules,
  canonicalization, registry requirements, legacy boundary and rejection
  paths; record approval, rejection or revision request.
- **Success criteria:** Contract decision signed; approved version immutable;
  registry and conformance-fixture requirements accepted; Core 1.0 exclusion
  explicit.
- **Verification:** Governance Auditor checks signatures, revision history,
  evidence hashes and separation from Core 1.0.
- **Closure evidence:** Governance decision record referencing the exact
  HC-1.0 document hash.
- **Priority:** P0
- **Status:** **OPEN**

## V2-B08 — Responsibility Matrix

- **Description:** No formal V2 RACI and named sign-off authority are evidenced.
- **Cause:** Roles exist conceptually but accountability and segregation of
  duties have not been assigned.
- **Impact:** Decisions, exceptions and approvals are not fully auditable.
- **Evidence:** `TIM_V2_SCIENTIFIC_READINESS_ASSESSMENT.md`.
- **Responsible role:** Governance Lead.
- **Dependencies:** Organizational assignment of named persons outside this
  planning document.
- **Measures:** Approve RACI; assign one accountable owner per activity;
  enforce independent verification and Release Authority separation.
- **Success criteria:** All activities have exactly one Accountable role, at
  least one Responsible role where execution is required, and documented
  Consulted/Informed parties; named assignments are accepted.
- **Verification:** Governance Auditor checks completeness and conflicts of
  interest.
- **Closure evidence:** Signed RACI assignment record.
- **Priority:** P0
- **Status:** **OPEN**

## Gap Register Template

| Gap ID | Gap key | Begin | End | Duration | Stream | Cause status | Cause | Recovery | Scientific impact | Evidence | Owner | Status |
|---|---|---|---|---:|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | KNOWN / UNKNOWN | — | — | — | — | Integrity Lead | OPEN |

Permitted gap statuses are the program status model. Unknown cause MUST remain
explicit. No row may represent reconstructed or estimated market data.

## Change Log

| Date | Change | Role | Evidence |
|---|---|---|---|
| 2026-07-23 | Initial blocker baseline; all blockers OPEN | Governance Lead | V2 Readiness Assessment |

