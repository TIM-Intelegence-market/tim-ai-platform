# TIM V2 Readiness Checklist

**Use:** Evidence-based manual gate  
**Automatic approval:** Prohibited  
**Current decision:** NOT READY  
**Core 1.0:** Frozen

Marking an item requires an evidence path, file hash, cut-off and reviewer.
Unchecked means not verified; it does not mean assumed failure.

## A. Evidence Freeze

- [ ] Review cut-off recorded.
- [ ] Evidence pack contents enumerated.
- [ ] SHA-256 recorded for every evidence artifact.
- [ ] Core Manifest and Freeze Declaration included.
- [ ] Acceptance and Scientific Validation reports included.
- [ ] Reconciliation and P0 RCA included.
- [ ] HC-1.0 candidate included.
- [ ] No source artifact changed after cut-off.
- [ ] All differing report cut-offs explicitly labelled.

## B. Continuous Coverage — V2-B01

- [ ] Qualifying interval duration approved before measurement.
- [ ] Symbol and timeframe explicitly defined.
- [ ] Start inclusive and end exclusive recorded.
- [ ] Expected intervals reproducibly calculated.
- [ ] Persisted intervals reproducibly counted.
- [ ] Duplicate intervals checked.
- [ ] Missing intervals enumerated.
- [ ] Coverage calculation independently repeated.
- [ ] Coverage is ≥95.000%.
- [ ] No reconstruction, interpolation or estimation used.
- [ ] Coverage evidence hash recorded.
- [ ] V2-B01 status is at least VERIFIED.

## C. DATA_GAPs — V2-B02

- [ ] Gap Register contains every unique gap key.
- [ ] Duplicate gap events reconciled without deleting source events.
- [ ] Begin, end and duration recorded.
- [ ] Affected streams recorded.
- [ ] Cause recorded as known or explicitly unknown.
- [ ] Recovery evidence recorded.
- [ ] Scientific impact recorded.
- [ ] Reproduction method recorded.
- [ ] Owner and disposition recorded.
- [ ] No reconstructed data represented as evidence.
- [ ] Unresolved new gap count at final cut-off is zero.
- [ ] V2-B02 status is at least VERIFIED.

## D. Artifact Audit — V2-B03

- [ ] Every audit issue mapped to one disposition.
- [ ] Legacy documentation absence separated from corruption.
- [ ] P0 hash false positive linked to Root Cause Report.
- [ ] Valid Readiness artifact self-hash acknowledged.
- [ ] Valid Insights output-domain hash acknowledged.
- [ ] No audit FAIL manually overwritten.
- [ ] Future V2 validator requirements mapped to HC-1.0.
- [ ] Independent Integrity review complete.
- [ ] V2-B03 status is at least VERIFIED.

## E. Research Quality — V2-B04

- [ ] Quality metric catalogue approved.
- [ ] Schema integrity checked.
- [ ] Timestamp integrity checked.
- [ ] Forward-only checked.
- [ ] OBSERVE-only checked.
- [ ] Replay checked.
- [ ] Coverage and gap evidence linked.
- [ ] Provenance inventory linked.
- [ ] Hash-domain disposition linked.
- [ ] All P0 quality issues verified or explicitly rejected.
- [ ] V2-B04 status is at least VERIFIED.

## F. Historical Provenance — V2-B05

- [ ] Present provenance fields inventoried.
- [ ] Missing provenance fields inventoried.
- [ ] Affected record counts recorded at fixed cut-off.
- [ ] Permanently non-reconstructable records classified.
- [ ] No retroactive metadata creation performed.
- [ ] No historical hash changed.
- [ ] Prospective V2 evidence boundary approved.
- [ ] New-scope provenance is 100%.
- [ ] Legacy limitation approved and retained.
- [ ] V2-B05 status is at least VERIFIED.

## G. HC-1.0 Governance — V2-B07

- [ ] Exact specification hash recorded.
- [ ] Contract version reviewed.
- [ ] Hash domains reviewed.
- [ ] Canonicalization rules reviewed.
- [ ] Decimal/time/ordering rules reviewed.
- [ ] Legacy boundary reviewed.
- [ ] Artifact-type registry requirement approved.
- [ ] Conformance fixture requirement approved.
- [ ] Cross-domain rejection requirement approved.
- [ ] Rejection/revision history recorded.
- [ ] Release Authority decision signed.
- [ ] Approval explicitly excludes implementation authority.
- [ ] V2-B07 status is at least VERIFIED.

## H. Responsibility and Independence — V2-B08

- [ ] Scientific Lead assigned.
- [ ] Governance Lead assigned.
- [ ] Integrity Lead assigned.
- [ ] Validator Owner assigned.
- [ ] Core Owner assigned.
- [ ] Research Lead assigned.
- [ ] QA Lead assigned.
- [ ] Release Authority assigned.
- [ ] Governance Auditor assigned.
- [ ] Conflicts declared.
- [ ] Segregation rules verified.
- [ ] Named holders accepted responsibilities.
- [ ] V2-B08 status is at least VERIFIED.

## I. Manual Scientific Review — V2-B06

- [ ] Reviewer panel approved.
- [ ] Evidence pack distributed unchanged.
- [ ] All P0 blocker evidence reviewed.
- [ ] Coverage criterion reviewed.
- [ ] DATA_GAP criterion reviewed.
- [ ] Provenance limitation reviewed.
- [ ] Replay evidence reviewed.
- [ ] Integrity/audit disposition reviewed.
- [ ] Known limitations recorded.
- [ ] Dissent recorded.
- [ ] Decision scope states planning versus implementation.
- [ ] Signed decision exists.
- [ ] V2-B06 status is at least VERIFIED.

## J. Final Readiness Assessment

- [ ] All P0 blockers VERIFIED.
- [ ] P1 blockers VERIFIED or formally accepted within an isolated V2 scope.
- [ ] No blocker is silently omitted.
- [ ] No blocker is automatically closed.
- [ ] Machine-readable and human-readable evidence agree at the same cut-off.
- [ ] Final assessment is independently authored.
- [ ] Decision is exactly NOT READY, CONDITIONALLY READY or READY FOR V2 PLANNING.
- [ ] Planning approval does not authorize implementation.
- [ ] Final decision references immutable evidence hashes.
- [ ] Release Authority signs the decision.

## Verification Record

| Section | Reviewer role | Evidence reference | Cut-off | Result | Date |
|---|---|---|---|---|---|
| A | UNASSIGNED | — | — | NOT VERIFIED | — |
| B | UNASSIGNED | — | — | NOT VERIFIED | — |
| C | UNASSIGNED | — | — | NOT VERIFIED | — |
| D | UNASSIGNED | — | — | NOT VERIFIED | — |
| E | UNASSIGNED | — | — | NOT VERIFIED | — |
| F | UNASSIGNED | — | — | NOT VERIFIED | — |
| G | UNASSIGNED | — | — | NOT VERIFIED | — |
| H | UNASSIGNED | — | — | NOT VERIFIED | — |
| I | UNASSIGNED | — | — | NOT VERIFIED | — |
| J | UNASSIGNED | — | — | NOT VERIFIED | — |

