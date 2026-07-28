# TIM V2 Roadmap

The roadmap is sequential by evidence gate, not by calendar promise.

| Release | Focus | Principal outputs | Entry gate | Exit gate |
|---|---|---|---|---|
| V2.0 | Foundation | repository, contracts, architecture, CI plan, governance | TIM-IM V1 tag | approved interfaces and clean baseline |
| V2.1 | Knowledge Graph | claim/evidence/provenance graph | V2.0 contracts | deterministic graph and migration evidence |
| V2.2 | Research Engine | hypothesis, experiment and result lifecycle | Knowledge Graph | reproducible experiment replay |
| V2.3 | Dataset Registry | catalog, lineage, temporal and quality rules | Research contracts | dataset identity and restore verification |
| V2.4 | Orderflow Intelligence | governed observations and features | Dataset Registry | leakage and integrity validation |
| V2.5 | Scientific Evaluation | evaluation registry and promotion gates | candidate features/strategies | independent reproducibility |
| V2.6 | Decision Engine | evidence-backed recommendations and decisions | Evaluation gates | deterministic, auditable decision records |
| V2.7 | Simulation | scenarios, portfolios and failure testing | Decision contracts | deterministic replay and rollback |
| V2.8 | Paper Trading | isolated execution rehearsal | Simulation gate | no-live-order proof and operational acceptance |
| V2.9 | Shadow Trading | live-input decision observation | Paper acceptance | zero-order guarantee and incident drills |
| V3.0 | Autonomous Research | bounded agent-assisted research | mature governance | human-approved autonomy envelope |

## Cross-cutting tracks

- Security, Governance and Observability begin in V2.0 and gate every release.
- Schema evolution and migration rehearsal accompany every contract change.
- Dataset and result immutability are enforced before feature work.
- No milestone automatically authorizes the next execution mode.
