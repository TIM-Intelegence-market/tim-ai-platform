# TIM V2 Milestones

## V2.0 Foundation

- authoritative repository and release process;
- module ownership and dependency rules;
- interface and schema registry plan;
- local verification and future CI specification;
- threat model and data-classification baseline.

Exit: no V2 runtime code; architecture and governance approved.

## V2.1 Knowledge Graph

- typed Evidence, Claim, Contradiction and Decision records;
- stable identity and temporal semantics;
- lineage queries and graph export;
- migration from TIM-IM projections without rewriting source evidence.

Exit: deterministic reconstruction from fixtures.

## V2.2 Research Engine

- hypothesis and experiment records;
- immutable inputs/configuration;
- controlled run orchestration;
- result and failure provenance.

Exit: identical input reproduces identical deterministic result identity.

## V2.3 Dataset Registry

- dataset versions, partitions and schemas;
- availability, quality and freshness;
- temporal and leakage metadata;
- retention, backup and restore.

Exit: catalog completeness and restore drill.

## V2.4 Orderflow Intelligence

- orderflow dataset contract;
- observation and feature definitions;
- quality, latency and missing-data behavior;
- independent validation suite.

Exit: scientific validation; no execution dependency.

## V2.5 Scientific Evaluation

- evaluation definitions and immutable run manifests;
- benchmark and holdout governance;
- robustness, leakage and reproducibility checks;
- promotion decision records.

Exit: independent rerun and signed-off limitations.

## V2.6 Decision Engine

- recommendation, abstention and decision records;
- evidence weighting and conflict visibility;
- risk inputs and human approval states;
- deterministic replay.

Exit: no decision can directly bypass Risk or mode gates.

## V2.7 Simulation

- scenario catalog and deterministic clock;
- portfolio, costs and failure injection;
- reproducible reports and recovery tests.

Exit: stable replay and explicit model-risk register.

## V2.8 Paper Trading

- isolated fake execution adapter;
- operational metrics and kill switch;
- reconciliation and incident procedures.

Exit: technical proof that no real order endpoint is reachable.

## V2.9 Shadow Trading

- live-data observation with disabled order path;
- latency and decision-quality measurement;
- audit and incident drills.

Exit: sustained zero-order evidence and governance approval.

## V3.0 Autonomous Research

- bounded task planning and agent budgets;
- hypothesis generation separated from validation;
- human approval for promotions;
- full agent provenance and revocation.

Exit: independently audited autonomy envelope.
