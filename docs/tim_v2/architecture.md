# TIM V2 Architecture Baseline

Status: planning only
No V2 runtime component is implemented by this document.

## 1. System context

```mermaid
flowchart LR
    Operator["Researcher / Operator"] --> Dashboard["TIM Dashboard"]
    AgentClient["Approved Agent Client"] --> MCP["TIM MCP Gateway"]
    Market["Market and Reference Sources"] --> Data["TIM Data Layer"]
    Data --> Platform["TIM V2 Platform"]
    Platform --> TIMIM["TIM Intelligence Manager"]
    TIMIM --> Dashboard
    TIMIM --> MCP
    Platform --> External["Explicitly Gated External Systems"]
```

## 2. Container diagram

```mermaid
flowchart TD
    Sources["Source Adapters"] --> Ingest["Data Ingest and Validation"]
    Ingest --> DataStore["Versioned Data Catalog"]
    DataStore --> Knowledge["Knowledge and Provenance Layer"]
    Knowledge --> TIMIM["TIM-IM"]
    Knowledge --> Research["Research Engine"]
    Research --> Feature["Feature Engine"]
    Feature --> Strategy["Strategy Engine"]
    Strategy --> Evaluation["Evaluation Engine"]
    Evaluation --> Decision["Decision Engine"]
    Decision --> Simulation["Simulation Engine"]
    Simulation --> Paper["Paper Boundary"]
    Paper --> Shadow["Shadow Boundary"]
    Shadow --> Live["Live Controller Boundary"]
    TIMIM --> API["MCP / Query / Dashboard Read APIs"]
```

## 3. Module diagram

```mermaid
flowchart TB
    subgraph Foundation["Foundation"]
        Core["Core"]
        Infrastructure["Infrastructure"]
        Developer["Developer Platform"]
        Security["Security"]
        Governance["Governance"]
        Configuration["Configuration"]
    end
    subgraph KnowledgePlane["Knowledge Plane"]
        Knowledge["Knowledge"]
        RAG["RAG"]
        Memory["Memory"]
        TIMIM["TIM Intelligence Manager"]
    end
    subgraph Science["Science Plane"]
        Research["Research"]
        Datasets["Datasets"]
        Orderflow["Orderflow"]
        MarketStructure["Market Structure"]
        MMT["MMT"]
        Macro["Macro"]
        FeatureStore["Feature Store"]
        Signals["Signals"]
        Strategies["Strategies"]
        Evaluation["Evaluation"]
    end
    subgraph DecisionPlane["Decision and Execution Plane"]
        Risk["Risk"]
        Decision["Decision"]
        Simulation["Simulation"]
        Execution["Execution"]
        Paper["Paper"]
        Shadow["Shadow"]
    end
    subgraph Access["Access and Automation"]
        Agents["Agents"]
        Routing["Routing"]
        MCP["MCP"]
        Dashboard["Dashboard"]
    end
    Foundation --> KnowledgePlane
    KnowledgePlane --> Science
    Science --> DecisionPlane
    KnowledgePlane --> Access
    DecisionPlane --> Access
```

## 4. Data flow

```mermaid
flowchart LR
    Raw["Raw observations"] --> Validate["Schema and quality validation"]
    Validate --> Catalog["Dataset registry and lineage"]
    Catalog --> Claims["Evidence and claims"]
    Claims --> Research["Experiments"]
    Research --> Features["Versioned features"]
    Features --> Strategies["Candidate strategies"]
    Strategies --> Evaluation["Leakage-safe evaluation"]
    Evaluation --> Decisions["Decision records"]
    Decisions --> Simulation["Simulation outcomes"]
    Simulation --> Paper["Paper observations"]
    Paper --> Shadow["Shadow observations"]
    Shadow --> LiveGate{"Human and risk gate"}
    LiveGate -->|authorized| Live["Live Controller"]
    LiveGate -->|denied| Stop["No action"]
```

## 5. Dependency graph

```mermaid
flowchart TD
    Core --> Infrastructure
    Infrastructure --> Data
    Data --> Knowledge
    Knowledge --> TIMIM
    Knowledge --> Research
    Research --> FeatureStore
    FeatureStore --> Signals
    Signals --> Strategies
    Strategies --> Evaluation
    Evaluation --> Risk
    Evaluation --> Decision
    Risk --> Decision
    Decision --> Simulation
    Simulation --> Paper
    Paper --> Shadow
    Shadow --> Execution
    Security --> Infrastructure
    Security --> Knowledge
    Security --> Execution
    Governance --> Research
    Governance --> Decision
    Governance --> Execution
```

Dependencies must point downward toward more stable contracts. Execution may
not be imported by Research, Knowledge or TIM-IM.

## 6. Agent graph

```mermaid
flowchart LR
    Orchestrator["Multi-Agent Orchestrator"] --> ResearchAgent["Research Agent"]
    Orchestrator --> DataAgent["Dataset Agent"]
    Orchestrator --> EvaluationAgent["Evaluation Agent"]
    Orchestrator --> GovernanceAgent["Governance Agent"]
    Orchestrator --> ReleaseAgent["Release Agent"]
    ResearchAgent --> ReadTools["Read-scoped tools"]
    DataAgent --> ReadTools
    EvaluationAgent --> ReadTools
    GovernanceAgent --> TIMIM["TIM-IM evidence"]
    ReleaseAgent --> Repo["Repository tools"]
    Orchestrator --> Budget["Budgets / timeouts / approvals"]
    Budget --> Audit["Agent audit log"]
```

No agent receives execution authority through the read MCP gateway.

## 7. Storage graph

```mermaid
flowchart TD
    Git["Git: code, schemas, docs, manifests"] --> Build["Reproducible build"]
    ObjectStore["Object store: immutable datasets/results"] --> Catalog["Dataset catalog"]
    Postgres["Postgres: operational structured state"] --> Knowledge["Knowledge projection"]
    Index["Derived search/RAG indexes"] --> Knowledge
    EventLog["Append-only events"] --> Knowledge
    Knowledge --> Snapshot["Canonical snapshots"]
    Snapshot --> Reports["Reports and dashboards"]
    Backup["Backups"] --> Restore["Restore verification"]
    Restore --> ObjectStore
    Restore --> Postgres
```

Derived indexes are replaceable. Git never stores secrets, live runtime state
or raw high-volume market data.

## 8. Configuration graph

```mermaid
flowchart LR
    Defaults["Versioned defaults"] --> Resolver["Configuration resolver"]
    Environment["Environment overrides"] --> Resolver
    Secrets["External secret store"] --> Resolver
    Policy["Governance policy"] --> Resolver
    Resolver --> Validated["Schema-validated effective config"]
    Validated --> Runtime["Module runtime"]
    Validated --> Provenance["Config hash and provenance"]
```

Effective configuration must be reproducible without committing secret values.

## 9. Security zones and trust boundaries

```mermaid
flowchart LR
    subgraph Z1["Zone 1: Untrusted Inputs"]
        Market["Market feeds"]
        Documents["External documents"]
        Models["Model outputs"]
    end
    subgraph Z2["Zone 2: Validation"]
        Parser["Passive parsers"]
        Quality["Schema / quality gates"]
        Redaction["Secret and sensitivity filters"]
    end
    subgraph Z3["Zone 3: Canonical Knowledge"]
        Evidence["Evidence store"]
        TIMIM["TIM-IM"]
    end
    subgraph Z4["Zone 4: Decision"]
        Evaluation["Evaluation"]
        Decision["Decision records"]
        Risk["Risk gates"]
    end
    subgraph Z5["Zone 5: Execution"]
        Paper["Paper"]
        Shadow["Shadow"]
        Live["Live Controller"]
    end
    Z1 --> Z2
    Z2 --> Z3
    Z3 --> Z4
    Z4 --> Z5
```

Every zone transition requires typed data, provenance and policy validation.

## 10. Observability layer

```mermaid
flowchart TD
    Modules["All modules"] --> Logs["Structured logs"]
    Modules --> Metrics["Metrics"]
    Modules --> Traces["Trace/correlation IDs"]
    Modules --> Events["Domain events"]
    Logs --> Health["Health and alerting"]
    Metrics --> Health
    Traces --> Health
    Events --> Audit["Immutable audit view"]
    Health --> TIMIM["TIM-IM status"]
    Audit --> TIMIM
```

Observability data must not silently become scientific evidence; promotion
requires an explicit evidence record.

## 11. Failure domains

```mermaid
flowchart TB
    FeedFailure["Source/feed failure"] --> DataGap["Data gap; no fabricated value"]
    ParserFailure["Parser failure"] --> Quarantine["Artifact quarantine"]
    DBFailure["Database failure"] --> ReadOnly["Read-only degraded mode"]
    ModelFailure["Model failure"] --> Abstain["Abstain; deterministic path remains"]
    AgentFailure["Agent failure"] --> Cancel["Cancel task; preserve audit"]
    EvalFailure["Evaluation failure"] --> BlockPromotion["Block promotion"]
    RiskFailure["Risk service failure"] --> BlockExecution["Fail closed"]
    ExecutionFailure["Execution boundary failure"] --> KillSwitch["Stop / kill switch"]
```

## 12. Recovery paths

```mermaid
flowchart LR
    Detect["Detect failure"] --> Isolate["Isolate affected domain"]
    Isolate --> Snapshot["Capture state and provenance"]
    Snapshot --> Restore["Restore last verified backup"]
    Restore --> Validate["Run schema, integrity and regression checks"]
    Validate --> Compare{"Hashes and acceptance match?"}
    Compare -->|yes| Resume["Resume previous safe mode"]
    Compare -->|no| Escalate["Human incident and rollback decision"]
```

## 13. Package and lifecycle rules

```mermaid
flowchart TB
    Contracts["tim_v2.contracts\nversioned envelopes"]
    Domains["tim_v2.domains\npure domain records"] --> Contracts
    Services["tim_v2.services\nuse-case orchestration"] --> Domains
    Adapters["tim_v2.adapters\nstores, sources, MCP"] --> Services
    Apps["tim_v2.apps\nUI and future workers"] --> Services
    Tests["tests\ncontract + integration"] --> Apps
    Tests --> Adapters
```

The diagram is a future package rule, not an instruction to create packages in
V2.0. Dependencies point toward contracts and domains; contracts do not import
adapters, applications or execution capabilities.

```mermaid
stateDiagram-v2
    [*] --> Proposed
    Proposed --> Validated: schema/provenance valid
    Proposed --> Quarantined: invalid or unsafe
    Validated --> Reviewed: owner review
    Reviewed --> Accepted: governance rule met
    Reviewed --> Rejected: evidence insufficient
    Accepted --> Superseded: successor version
    Quarantined --> [*]
    Rejected --> [*]
```

This lifecycle applies to versioned data, research and knowledge artifacts as
appropriate. Acceptance is not an execution authorization.

## Module registry baseline

| Module | Responsibility | May depend on | Must not do |
|---|---|---|---|
| Core | stable domain primitives | none | import execution |
| Infrastructure | runtime and shared adapters | Core | encode strategy logic |
| Knowledge | claims, evidence, provenance | Core, Data | execute trades |
| Research | hypotheses and experiments | Knowledge, Datasets | promote itself |
| Datasets | catalog, lineage, quality | Data, Governance | hide source identity |
| Orderflow | orderflow observations/features | Datasets, Research | place orders |
| Market Structure | structure observations | Datasets, Research | place orders |
| MMT | MMT research models | Research, Datasets | bypass validation |
| Macro | macro evidence | Research, Datasets | become canonical without evidence |
| Feature Store | versioned feature definitions | Research, Datasets | own strategy decisions |
| Signals | candidate signals | Feature Store | execute |
| Strategies | candidate decision policies | Signals, Risk | bypass evaluation |
| Risk | constraints and limits | Evaluation, Governance | silently approve |
| Execution | external order boundary | Decision, Risk, Security | accept ungated calls |
| Simulation | deterministic scenarios | Strategies, Risk | write live systems |
| Paper | isolated simulated execution | Simulation, Decision | submit real orders |
| Shadow | live-data observation, no orders | Paper, Decision | submit orders |
| Evaluation | scientific and operational gates | Research, Strategies | rewrite results |
| Decision | evidence-backed recommendations and approvals | Evaluation, Risk, Governance | call execution directly |
| Developer Platform | reproducible build, quality and release contracts | Core, Infrastructure, Governance | alter frozen behavior implicitly |
| RAG | derived retrieval indexes | Knowledge | become source of truth |
| Memory | scoped retained context | Knowledge, Governance | store secrets by default |
| Agents | bounded specialized workflows | TIM-IM, Routing | self-authorize |
| Routing | model/tool routing policy | Security, Governance | bypass budgets |
| MCP | typed external tool surface | TIM-IM, Security | expose mutation by default |
| Dashboard | human management UI | TIM-IM | directly mutate canonical state |
| Security | identity, secrets, policy | Infrastructure | depend on strategies |
| Governance | approvals, decisions, audit | Knowledge | infer approvals |
