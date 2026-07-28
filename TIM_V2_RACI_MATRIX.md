# TIM V2 Responsibility Matrix

**Status:** Proposed; organizational assignment required  
**Scope:** Readiness remediation and governance only  
**Core 1.0:** No functional change authorized

## RACI Definitions

- **R — Responsible:** performs the approved activity.
- **A — Accountable:** owns the result and approves completion.
- **C — Consulted:** provides mandatory review input.
- **I — Informed:** receives the evidence and decision.

Each activity has exactly one `A`. A person assigned to independent
verification SHOULD NOT also be the person who produced the evidence.

## Roles

| Role | Mandate |
|---|---|
| Scientific Lead | Scientific criteria, review scope and evidence sufficiency |
| Governance Lead | Process, approvals, policy and audit trail |
| Integrity Lead | Hashes, provenance, gaps and evidence integrity |
| Validator Owner | Read-only validation and monitoring evidence |
| Core Owner | Protect frozen Core 1.0 boundary |
| Research Lead | Research artifacts, provenance inventory and scope |
| QA Lead | Independent test/quality verification |
| Release Authority | Final authorization or rejection |
| Governance Auditor | Independent process and segregation review |

## Matrix

| Activity | Scientific Lead | Governance Lead | Integrity Lead | Validator Owner | Core Owner | Research Lead | QA Lead | Release Authority | Governance Auditor |
|---|---|---|---|---|---|---|---|---|---|
| Approve remediation baseline | C | R | C | I | C | C | C | **A** | C |
| Freeze evidence cut-off | **A** | C | R | R | I | C | C | I | C |
| Measure continuous coverage | **A** | I | R | R | I | C | C | I | C |
| Independently verify coverage | C | I | R | C | I | I | **A** | I | C |
| Build Gap Register | C | I | **A** | R | I | C | C | I | I |
| Verify Gap Register | C | I | C | C | I | I | **A** | I | R |
| Classify audit findings | C | C | **A/R** | C | C | C | C | I | C |
| Verify audit disposition | I | C | C | I | C | I | R | **A** | R |
| Define quality catalogue | C | C | C | C | I | C | **A/R** | I | I |
| Verify quality evidence | C | I | R | C | I | C | **A** | I | C |
| Inventory historical provenance | C | I | R | I | I | **A/R** | C | I | C |
| Approve legacy limitation | C | R | C | I | C | C | C | **A** | C |
| Protect Core 1.0 freeze | I | C | C | I | **A/R** | I | C | C | C |
| Review HC-1.0 | C | **A/R** | R | C | C | C | R | I | C |
| Approve/reject HC-1.0 | C | R | C | I | C | I | C | **A** | C |
| Approve artifact-type registry requirement | C | R | R | C | C | C | C | **A** | C |
| Approve conformance-fixture requirement | I | C | R | R | I | C | **A** | I | C |
| Maintain decision/revision history | I | **A/R** | I | I | I | I | I | C | C |
| Assign named role holders | C | R | I | I | I | I | I | **A** | C |
| Check segregation of duties | I | C | C | I | I | I | C | **A** | R |
| Prepare Scientific Review pack | **A** | C | R | R | C | R | R | I | C |
| Conduct manual Scientific Review | **A** | R | C | C | C | C | C | I | R |
| Record Scientific Review decision | R | C | I | I | I | I | C | **A** | C |
| Run Final Readiness Assessment | C | C | R | C | C | C | R | I | **A** |
| Authorize V2 planning | C | R | I | I | C | I | C | **A** | C |
| Authorize V2 implementation | C | R | C | I | C | I | C | **A** | C |

## Mandatory Segregation Rules

1. Release Authority cannot be the sole producer of the reviewed evidence.
2. QA verification cannot be self-approved by the evidence producer.
3. Governance Auditor cannot approve their own audit conclusion.
4. Core Owner can veto activity that crosses the Core 1.0 freeze boundary.
5. Integrity Lead can block a status transition when evidence hashes or
   provenance are unresolved.
6. Scientific Lead can reject scientific sufficiency but cannot unilaterally
   authorize V2 implementation.
7. HC-1.0 approval and implementation authorization are separate decisions.

## Assignment Record Template

| Role | Named holder | Alternate | Accepted at | Conflict declaration | Signature/reference |
|---|---|---|---|---|---|
| Scientific Lead | UNASSIGNED | UNASSIGNED | — | — | — |
| Governance Lead | UNASSIGNED | UNASSIGNED | — | — | — |
| Integrity Lead | UNASSIGNED | UNASSIGNED | — | — | — |
| Validator Owner | UNASSIGNED | UNASSIGNED | — | — | — |
| Core Owner | UNASSIGNED | UNASSIGNED | — | — | — |
| Research Lead | UNASSIGNED | UNASSIGNED | — | — | — |
| QA Lead | UNASSIGNED | UNASSIGNED | — | — | — |
| Release Authority | UNASSIGNED | UNASSIGNED | — | — | — |
| Governance Auditor | UNASSIGNED | UNASSIGNED | — | — | — |

Until named holders accept these roles, blocker V2-B08 remains **OPEN**.

