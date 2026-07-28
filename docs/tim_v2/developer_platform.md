# TIM V2 Developer Platform

The Developer Platform makes future changes reproducible and reviewable. It is
a set of engineering contracts, not a deployment or CI implementation in V2.0.

| Capability | Contract |
|---|---|
| Repository | authoritative TIM repository, scoped branches and annotated releases |
| Build | declared Python support, pinned dependencies and reproducible environment identity |
| Quality | formatting, typing, unit, contract, integration and regression evidence |
| Schemas | versioned contracts, compatible migrations and rollback rehearsal |
| Documentation | architecture, interfaces, decisions, limitations and evidence updated with changes |
| Review | owner review, security/science review at gated boundaries, no self-approval for critical promotions |
| Release | change manifest, full verification, SBOM/lock target, signed/tagged artifact and recovery evidence |

Developer tooling may not change frozen TIM-IM V1 behavior as a side effect.
Generated data, runtime state, secrets and research outputs remain outside the
versioned code/documentation set unless their approved manifest explicitly says
otherwise.
