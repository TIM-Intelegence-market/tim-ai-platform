# TIM Implementation Roadmap

## Authority boundary

This roadmap is planning only. It authorizes no implementation, secret use,
private exchange call, shadow execution or live trading.

## Phases

| Phase | Goal and prerequisites | Planned modules/tests | Acceptance gate | Stop conditions | Role |
|---|---|---|---|---|---|
| 0 Governance/safety | approved autonomy levels and safety contracts | mode, kill switch, limits, protected paths, audit contracts; negative tests | no code path can execute a real order | ambiguous owner/mode/limits | Governance + Safety |
| 1 Data stability | prospective capture window; Core-compatible quality work only | quality gates, freshness, reconnect evidence, provenance/replay tests | ≥99.5% coverage, no unknown gaps/mismatch, provenance per row | reconstruction or denominator manipulation required | Data Reliability |
| 2 Feature engine | Phase 1 PASS; frozen input contract | missing deterministic features, versions and hashes | identical input → identical features/hashes | float ambiguity or incomplete quality | Quant Research Engineering |
| 3 Observation engine | quality-approved features | versioned evidence rules and validation queue | no observation on insufficient quality/evidence | subjective/AI rule introduced | Scientific Systems |
| 4 Strategy specification | independent scientific approval | exactly one machine-readable research strategy; no execution code | every hypothetical trade reconstructible | incomplete field or discretionary rule | Research Lead + Governance |
| 5 Backtest | frozen strategy/data/contracts | forward-only engine, fees, slippage, funding, latency and look-ahead tests | reproducible and passes look-ahead audit | missing required data/model | Backtest + Independent Audit |
| 6 Walk-forward/OOS | frozen backtest and predeclared splits | regime/session reports | predeclared stability criteria met out of sample | split changed after results | Scientific Reviewer |
| 7 Risk engine | approved risk contract | deterministic denial authority, limits, kill switch tests | can block every decision | any bypass or warning-only failure | Risk/Safety |
| 8 Paper trading | Phases 0–7 PASS | virtual broker, fills, rejects, journal | 30–60 days without technical integrity failure | live adapter/secret required | Paper Execution QA |
| 9 Shadow | separate future approval only | disabled comparison simulator | robust real-condition simulation without orders | any order-capable call | Independent Release Authority |
| 10 Limited live | explicitly not authorized | prerequisites only | separate human approval and audit | current task or roadmap used as authority | Release Authority |

Research parameters such as 0.25% per-trade risk, 1% daily loss, maximum three
trades and stop after three losses are only future paper-study parameters, not
financial advice or authorization.

## Sprint sequence

| Sprint | Scope | Entry gate | Exit evidence |
|---|---|---|---|
| 1 System boundaries | inventory, autonomy level, risk register, contracts | baseline accepted | approved documents and no code change |
| 2 Data quality | coverage/gaps/reconnect/freshness/replay/provenance | Sprint 1 approval | prospective quality report |
| 3 Feature engine | deterministic features/versions/hashes | data gate PASS | golden replay |
| 4 Observation engine | evidence rules/missing evidence/queue | feature gate PASS | quality-denial tests |
| 5 Strategy contract | one complete machine-readable strategy | independent review | frozen contract |
| 6 Backtesting | costs, forward-only, look-ahead protection | strategy freeze | reproducible report |
| 7 Risk engine | limits, cooldowns, kill switch | safety approval | denial/bypass suite |
| 8 Paper trading | paper broker/state machine/journal/dashboard | all prior gates PASS | stable paper runtime |
| 9 Validation | 30–60-day fixed-rule window | paper integrity PASS | signed final report |

## Dependencies and largest risks

- Phase 1 is blocked by lack of a prospectively defined qualifying window and
  historical host-sleep gaps.
- Futures funding, mark price, order-book and latency sources are missing.
- Strategy, risk and order lifecycle contracts do not exist.
- Git/project ownership boundaries are not cleanly isolated.
- Current test environment has two known failures.

## Transition governance

Each phase requires a versioned approval citing input artifacts, tests, risks
and stop conditions. Failure or UNKNOWN never promotes the system. Data from
different Core, metric, rule, validation or strategy versions remains isolated.

## Recommended next action

Approve and, only under a new explicit implementation request, execute the
contract-only Sprint 01 specified in
[SPRINT_01_SPECIFICATION.md](SPRINT_01_SPECIFICATION.md). It must not add an
exchange adapter, strategy or order path.

