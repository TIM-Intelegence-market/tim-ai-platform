# TIM V2 Governance Approval Workflow

**Scope:** HC-1.0 and V2 Readiness governance  
**Nature:** Planning only  
**Core 1.0:** Frozen and excluded

## Principles

1. No approval is inferred from document existence.
2. Approval references exact immutable document hashes.
3. Specification approval does not authorize implementation.
4. Planning approval does not authorize production use.
5. Rejection and dissent are preserved.
6. Historical artifacts are never rewritten.
7. Every decision has one accountable Release Authority.

## Approval Objects

| Object | Current state | Required decision |
|---|---|---|
| Remediation Program | Proposed | Approve/revise/reject |
| Blocker Register | Initial baseline | Approve baseline |
| RACI Matrix | Roles unassigned | Approve and assign |
| HC-1.0 Specification | Specification ready | Approve/revise/reject |
| Artifact-type registry | Not present | Require and later approve |
| Conformance fixture pack | Not present | Require and later approve |
| V2 cut-over policy | Not present | Define and approve |
| Scientific Review | Not performed | Approve/reject V2 planning |
| V2 implementation authority | Not granted | Separate future decision |

## Workflow

### Gate G0 — Intake and Evidence Freeze

**Responsible:** Governance Lead  
**Accountable:** Release Authority

Required:

- record proposed decision;
- enumerate inputs;
- calculate and record file hashes;
- set review cut-off;
- confirm no Core 1.0 mutation;
- open conflicts-of-interest declarations.

Failure result: `REJECTED_INTAKE`.

### Gate G1 — Completeness Review

**Responsible:** QA Lead  
**Accountable:** Governance Lead

Check:

- required documents present;
- versions and hashes recorded;
- blocker IDs mapped;
- no silent supersession;
- dissent and limitations included;
- RACI assignments complete.

Failure result: `REVISION_REQUIRED`.

### Gate G2 — Scientific Review

**Responsible/Accountable:** Scientific Lead

Check:

- ≥95% qualifying continuous coverage;
- zero unresolved new DATA_GAPs;
- scientific scope and cut-off fixed;
- provenance scope explicit;
- replay stable;
- no reconstructed evidence;
- known limitations retained.

Failure result: `SCIENTIFIC_REVIEW_FAILED`.

### Gate G3 — Integrity and HC-1.0 Review

**Responsible:** Integrity Lead and QA Lead  
**Accountable:** Governance Lead

Check:

- P0 RCA acknowledged;
- hash domains unambiguous;
- legacy Core 1.0 semantics isolated;
- artifact-type registry proposal complete;
- conformance fixtures specified;
- cross-domain comparisons rejected;
- no historical migration/backfill.

Possible result:

- `HC_APPROVED`
- `HC_REVISION_REQUIRED`
- `HC_REJECTED`

This gate does not authorize implementation.

### Gate G4 — Independent Governance Audit

**Responsible:** Governance Auditor  
**Accountable:** Release Authority

Check:

- segregation of duties;
- all blocker transitions evidenced;
- no self-approval;
- revision history complete;
- rejected evidence preserved;
- Core Freeze respected;
- decision scope unambiguous.

Failure result: `GOVERNANCE_AUDIT_FAILED`.

### Gate G5 — Planning Authorization

**Responsible:** Governance Lead  
**Accountable:** Release Authority

Prerequisites:

- G0–G4 PASS;
- all P0 blockers at least `VERIFIED`;
- manual Scientific Review decision present;
- HC-1.0 decision present;
- RACI assigned.

Decision:

- `READY_FOR_V2_PLANNING`
- `NOT_READY`

Planning authorization permits requirements, risk analysis and implementation
planning only.

### Gate G6 — Implementation Authorization

Separate future gate. It is outside this remediation program.

Minimum future prerequisites:

- approved V2 plan;
- approved V2 manifest/version set;
- approved artifact and schema registries;
- conformance fixture pack;
- reproducible-build plan;
- independent test plan;
- explicit Core 1.0 isolation;
- rollback and incident governance.

Decision:

- `AUTHORIZED_FOR_V2_IMPLEMENTATION`
- `NOT_AUTHORIZED`

## HC-1.0 Decision Record

Required fields:

```text
decision_id:
decision_date:
specification_path:
specification_sha256:
contract_version:
decision: APPROVED | REVISION_REQUIRED | REJECTED
scope:
conditions:
excluded_activities:
scientific_lead:
integrity_lead:
qa_lead:
governance_lead:
release_authority:
independent_auditor:
dissent:
signatures_or_evidence_references:
```

## Rejection Rules

HC-1.0 or a related V2 proposal MUST be rejected when it:

- requires Core 1.0 mutation;
- rewrites historical artifacts or hashes;
- permits implicit hash domains;
- lacks contract versioning;
- permits cross-domain digest comparison;
- lacks deterministic serialization;
- lacks an artifact-type registry requirement;
- lacks conformance tests;
- blurs planning and implementation authorization.

Rejection does not delete the proposal. The rejected version and decision
record remain immutable evidence.

## Revision History Rules

Each revision receives:

- unique revision ID;
- parent revision hash;
- creation timestamp;
- author role;
- exact change rationale;
- affected sections;
- new document hash;
- review status;
- decision reference.

Approved text is never edited in place. A revision creates a new candidate
version. Contract semantic changes require a new contract version according to
HC-1.0 governance.

## Exception Handling

No exception may:

- change Core 1.0;
- waive unresolved P0 scientific blockers;
- convert missing evidence into PASS;
- authorize reconstruction;
- bypass Release Authority;
- be applied retroactively.

Every permitted procedural exception requires written rationale, expiry,
scope, risk owner and independent review.

## Current Workflow State

| Gate | Status | Reason |
|---|---|---|
| G0 | OPEN | No approved intake decision |
| G1 | OPEN | RACI roles not assigned |
| G2 | BLOCKED | Coverage and gaps fail |
| G3 | OPEN | HC-1.0 not reviewed/approved |
| G4 | BLOCKED | Earlier gates incomplete |
| G5 | BLOCKED | Binding blockers open |
| G6 | BLOCKED | Outside current authority |

