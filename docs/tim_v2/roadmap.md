# TIM V2 Roadmap

The roadmap is sequential by evidence gate, not by calendar promise.

| Release | Focus | Principal outputs | Entry gate | Exit gate |
|---|---|---|---|---|
| V2.0 | Foundation | repository, contracts, architecture, CI plan, governance | TIM-IM V1 tag | approved interfaces and clean baseline |
| V2.1 | Research Platform | hypothesis, experiment and result lifecycle | V2.0 contracts | reproducible experiment replay |
| V2.2 | Dataset Platform | catalog, lineage, temporal and quality rules | Research contracts | dataset identity and restore verification |
| V2.3 | Knowledge Platform | claim/evidence/provenance graph | Dataset contracts | deterministic graph and migration evidence |
| V2.4 | Feature Platform | feature definitions and temporal contracts | Dataset + knowledge contracts | leakage and integrity validation |
| V2.5 | Evaluation Platform | evaluation registry and promotion gates | candidate features/strategies | independent reproducibility |
| V2.6 | Simulation Platform | scenarios, replay and failure testing | Decision contracts | deterministic replay and rollback |
| V2.7 | Decision Platform | evidence-backed recommendations and decisions | Evaluation gates | deterministic, auditable decision records |
| V2.8 | Agent Platform | bounded roles, routing and audit | V2.0 security/governance | least-privilege evidence |
| V2.9 | Integration | approved adapters and end-to-end contracts | platform acceptance | read-only, recoverable integration proof |
| V3.0 | Autonomous Research | bounded agent-assisted research | mature governance | human-approved autonomy envelope |

## Cross-cutting tracks

- Security, Governance and Observability begin in V2.0 and gate every release.
- Schema evolution and migration rehearsal accompany every contract change.
- Dataset and result immutability are enforced before feature work.
- No milestone automatically authorizes the next execution mode.
