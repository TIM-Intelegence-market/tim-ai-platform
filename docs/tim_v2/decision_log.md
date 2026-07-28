# TIM V2 Architecture Decision Log

## D-001 — Standalone TIM repository

Decision: `/Users/tim/Documents/TIM/tim` is the authoritative Git root.
Reason: the parent repository did not track TIM and could not provide TIM
provenance.
Status: accepted.

## D-002 — TIM-IM V1 functional freeze

Decision: tag the accepted behavior as `tim-im-v1.0.0`; V2 work may not
silently extend it.
Reason: preserve the completed acceptance baseline.
Status: accepted.

## D-003 — Runtime data stays outside Git

Decision: raw data, runtime state, local databases, generated scans, outputs
and virtual environments are ignored.
Reason: security, size, mutability and reproducibility boundaries.
Status: accepted.

## D-004 — V2 planning only in this foundation

Decision: create contracts and roadmap but no V2 code.
Reason: implementation requires approved interfaces and Definition of Ready.
Status: accepted.

## D-005 — No remote selected automatically

Decision: retain a local authoritative repository without inventing a remote.
Reason: remote ownership and disclosure require user/organizational authority.
Status: accepted.

## D-006 — Evidence-first promotion

Decision: Research, Strategy, Decision, Simulation, Paper, Shadow and Live are
separate promotion domains.
Reason: scientific and operational evidence differs at every boundary.
Status: proposed V2 baseline.

## D-007 — Explicit claim ingestion

Decision: arbitrary prose and model text do not automatically become canonical
claims.
Reason: prevent hallucinated or injected state.
Status: inherited from TIM-IM V1.
