# TIM V2 Knowledge Platform - implementation record

Status: implementation in progress; not accepted or merged.

## Scope

The module `src/tim_v2/knowledge/` is an in-memory, immutable knowledge
registry. It implements structured Source, Evidence, Claim, Fact,
Contradiction, DecisionHistory and ResearchLink contracts. It contains no RAG
index, model call, network client, data ingestion, Research execution, TIM-IM
write path, strategy logic or trading/execution capability.

## Guarantees

- Sources and evidence are hash- and provenance-bearing records.
- Claims require registered evidence, confidence and temporal validity.
- Facts require supported claims and an explicit validation policy.
- Conflicting supported claims produce an explicit `ABSTAIN` result until the
  contradiction is resolved.
- Repeated equal inserts are idempotent; changed records with the same ID are
  rejected as immutable conflicts.

## Current verification

`tests/test_tim_v2_knowledge_registry.py` covers provenance tracing, temporal
queries, unsupported-claim abstention, immutability, facts, missing evidence,
contradictions and decision/research references. Final phase acceptance remains
required before this platform can be merged or before Research work may start.
