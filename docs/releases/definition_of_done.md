# TIM-IM V1 Release Definition of Done

| Gate | Required evidence | Status |
|---|---|---|
| Authoritative repository | TIM-local `.git`, root and branch verified | PASS |
| Initial baseline | immutable root commit recorded | PASS |
| Release freeze | architecture-freeze document and change gate | PASS |
| Reproducibility | content manifest, snapshot ID/SHA, schema and tag ref | PASS |
| Acceptance | 20/20 mandatory scenarios | PASS |
| Regression | 58 TIM-IM and 237 full TIM tests | PASS |
| Provenance | standalone repository; parent repository not authoritative | PASS |
| Protected boundaries | no TIM-IM protected write observed | PASS |
| Trading/science integrity | no functional or result change in this release task | PASS |
| Architecture baseline | context through recovery diagrams documented | PASS |
| TIM V2 plan | roadmap, milestones, interfaces and risks documented | PASS |
| Repository hygiene | ignore, attributes and line endings documented | PASS |
| Release identity | annotated tag `tim-im-v1.0.0` | PASS after tag creation |
| Remote publication | not required; remote absent is documented | NOT APPLICABLE |

The release is complete only when the annotated tag resolves to the release
documentation commit and the worktree is clean.
