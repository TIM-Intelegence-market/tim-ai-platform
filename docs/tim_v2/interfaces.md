# TIM V2 Interface Baseline

All interfaces are planning contracts. Names and payloads require schema review
before implementation.

## Common envelope

Every cross-module record must carry:

- `record_id` and `record_type`;
- `schema_version`;
- `created_at_utc` and applicable event/valid time;
- `source_refs` and content hashes;
- code, configuration and dataset identities;
- sensitivity and trust classification;
- producer and deterministic/model metadata;
- supersession/tombstone state where applicable.

## Principal interfaces

| Producer | Consumer | Contract | Failure behavior |
|---|---|---|---|
| Data Layer | Dataset Registry | validated observation batch | quarantine invalid batch |
| Dataset Registry | Knowledge | dataset identity and lineage | expose gap/stale state |
| Knowledge | TIM-IM | evidence, claims, contradictions | abstain on unsupported state |
| Knowledge | Research | immutable evidence view | fail if provenance incomplete |
| Research | Feature Store | experiment/result manifest | reject unvalidated result |
| Feature Store | Signals | versioned feature vector | mark missing; never fabricate |
| Signals | Strategies | candidate signal set | no automatic promotion |
| Strategies | Evaluation | strategy candidate manifest | reject mutable inputs |
| Evaluation | Decision | evaluation and limitations | block on failed gate |
| Risk | Decision | limits and constraints | fail closed |
| Decision | Simulation | decision record | no direct execution |
| Simulation | Paper | approved scenario/order intent | isolated fake adapter only |
| Paper | Shadow | operational acceptance evidence | manual promotion |
| Shadow | Live Controller | governance package | explicit human authorization |
| TIM-IM | MCP/Dashboard | read-only management view | abstain/degrade read-only |
| Agents | Orchestrator | task result and evidence refs | cancel on budget/policy breach |

## API rules

- schemas are versioned before producers and consumers deploy;
- consumers ignore additive unknown fields but reject unsupported major
  versions;
- identifiers are stable and never reused;
- retries require idempotency keys;
- ordering assumptions are explicit;
- event time and observation time are separate;
- errors are typed and never encoded as successful empty facts;
- no interface crosses into Execution without Risk and Governance records.

## MCP and agent contract

Read tools may expose canonical state, source health, risks, contradictions,
search and grounded queries. Mutation tools require a separate server,
authentication, authorization, audit and explicit deployment approval. The
TIM-IM V1 MCP remains read-only.
