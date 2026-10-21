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

## D-008 — Contracts before runtime

Decision: V2.0 defines domain, dataset, knowledge, feature, evaluation,
simulation and agent contracts before their runtime implementations.
Reason: stable ownership, schema and failure behavior are prerequisites for
reproducible implementation and review.
Status: accepted.

## D-009 — Immutable versions, append-only history

Decision: datasets, research results and material knowledge records are
versioned rather than edited in place; corrections supersede prior records.
Reason: scientific traceability requires preserving the original assertion and
the reason it changed.
Status: accepted.

## D-010 — Time is a first-class contract

Decision: event, observation, publication and processing time are distinct
fields whenever applicable.
Reason: collapsing them makes lookahead leakage and historical reconstruction
unreviewable.
Status: accepted.

## D-011 — Derived retrieval is non-canonical

Decision: RAG/search indexes are disposable projections of structured,
provenance-bearing records.
Reason: index drift or model retrieval must not alter scientific truth.
Status: accepted.

## D-012 — Privilege is separated from intelligence

Decision: agents, dashboards and MCP may read or propose within their grants;
authorization for mutation, promotion and any future execution is separate.
Reason: a capable assistant is not an approval authority.
Status: accepted.

## D-013 — Simulation is a promotion domain, not execution

Decision: replay, historical simulation, paper and shadow are separately
gated future domains, and V2.0 implements none of them.
Reason: evidence from one mode cannot establish authorization for another.
Status: accepted.

## D-014 — Leverage is capped at 10x

Decision: TIM may plan spot trades (1x) and leveraged trades up to at most 10x.
`MAX_LEVERAGE` in `src/orderflow_scenario/config.py` is a hard cap: no risk
tier and no config file may exceed it, the Risk Engine rejects higher requests
(`leverage_exceeds_max_10x`) and the paper evaluator flags them.
Reason: owner decision (Uzi, 2026-10-20). Still paper only; no real orders.
Status: accepted.
