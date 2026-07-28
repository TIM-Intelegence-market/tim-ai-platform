# TIM V2 Risk Register

| ID | Risk | Likelihood | Impact | Mitigation | Gate |
|---|---|---:|---:|---|---|
| R-01 | V1 behavior changes during V2 work | medium | high | freeze contract, versioned interfaces, full regressions | every release |
| R-02 | Lookahead or temporal leakage | medium | critical | event-time contracts, holdout governance, leakage tests | Research/Evaluation |
| R-03 | Model output becomes canonical fact | medium | high | claim classes, evidence gates, abstention | Knowledge |
| R-04 | Hidden dataset/version drift | high | high | registry, immutable manifests, hashes | Datasets |
| R-05 | Agent exceeds tool authority | medium | critical | scoped tools, budgets, approvals, audit | Agents |
| R-06 | Execution path activates prematurely | low | critical | physical adapter separation, fail-closed gates | Paper/Shadow/Live |
| R-07 | Schema migration loses provenance | medium | high | additive migration, rehearsal, rollback | all schemas |
| R-08 | Derived RAG index treated as truth | medium | medium | source references and replaceable index policy | Knowledge/RAG |
| R-09 | Secrets enter Git or logs | medium | critical | secret store, scans, redaction and review | Security |
| R-10 | Runtime data bloats repository | medium | medium | ignore policy and external object storage | Foundation |
| R-11 | Optional source absence is hidden | medium | medium | explicit NOT CONFIGURED/NOT FOUND states | TIM-IM |
| R-12 | pytest-asyncio breaks on Python 3.16 | high | medium | planned dependency compatibility lane | Foundation |
| R-13 | No remote/CI causes local-only assurance | high | medium | separate remote and CI authorization | Release |
| R-14 | Recovery procedure is untested | medium | high | scheduled restore and incident drills | Operations |
| R-15 | Scientific and engineering approvals conflict | medium | high | RACI and decision log | Governance |

Risks are not closed by prose. Each mitigation requires executable or
independently reviewable evidence at the named gate.
