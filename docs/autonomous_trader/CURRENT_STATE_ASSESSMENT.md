# TIM Current State Assessment

## Scope and method

Repository assessed: `/Users/tim/Documents/TIM/tim`.

Method: read-only source inspection, call-path tracing, configuration and SQL
review, static keyword search, test inventory and review of persisted
scientific reports. Conclusions are labelled:

- **BELEGT:** directly supported by code or persisted evidence.
- **ABGELEITET:** derived from multiple direct sources.
- **UNVERIFIED:** insufficient runtime evidence.

No service was started or stopped, no private endpoint was called and no
existing project file was changed by this baseline task.

## Repository inventory

| Area | Primary paths | Inputs → outputs | Side effects | Runtime/reife |
|---|---|---|---|---|
| Entry point | `main.py` | settings → application lifecycle | DB, dashboard, public WebSocket | OPERATIONAL_VERIFIED; reachable |
| Public ingestion | `src/data_ingestion/binance_ws.py` | Binance Spot aggTrade JSON → `Trade` | public WebSocket only | OPERATIONAL_VERIFIED; reconnect lacks catch-up |
| Aggregation | `src/data_ingestion/aggregator.py` | ordered trades → 1m/5m/15m/1h candles | none | OPERATIONAL_VERIFIED |
| Persistence | `src/database/connection.py`, `repository.py`, `schema.sql` | trades/candles/observations/cases → PostgreSQL | transactional writes | OPERATIONAL_VERIFIED |
| Structure rules | `src/analysis/bos_detector.py`, `bronxc_rules.py` | closed candles → observations | none | OPERATIONAL_VERIFIED for implemented rules |
| Observation layer | `src/observation/engine.py` | candles → stable observations | in-memory dedup state | OPERATIONAL_VERIFIED |
| Orderflow metrics | `src/orderflow/metrics.py` | persisted AggTrades → Decimal metrics/hash | DB read | OPERATIONAL_VERIFIED |
| Orderflow observations | `src/orderflow/observations.py` | adjacent metric windows → observations/cases | none until repository write | OPERATIONAL_VERIFIED |
| Outcome validation | `src/orderflow/validation.py` | later persisted trades → retrospective outcome | DB write through `main.py` | OPERATIONAL_VERIFIED |
| Research cases | `src/research/case_engine.py` | observations → evidence containers | persisted atomically with observations | OPERATIONAL_VERIFIED |
| Memory/analytics | `src/memory`, `src/analytics`, `src/insights` | persisted research → descriptive statistics | read-only outputs/exports | OPERATIONAL_VERIFIED |
| Optional LLM | `src/llm/ollama_client.py` | observation prompt → explanation JSON | local HTTP when explicitly enabled | PARTIAL; optional, not decision authority |
| Research modules | `src/research/module_a`, `module_b`, `router.py`, `trigger.py` | injected evidence → research artifact | local cache/report writes | PARTIAL; Module B environment currently fails a dependency test |
| Paper research | `src/paper/automation.py` | closed case + reference prices → hypothetical journal entry | in-memory TEST_ONLY journal | EXPERIMENTAL; not a broker |
| Dashboard | `src/dashboard/app.py` | persisted/live state → read-only HTTP UI/API | local HTTP | OPERATIONAL_VERIFIED |
| Operations | `src/operational`, `src/acceptance`, `scripts/*` | state/logs/DB → health and reports | local report/state writes | PARTIAL; stale historical and live statuses require separation |
| Quality/replay | `src/quality`, `src/benchmark`, `src/research_ops` | persisted datasets → deterministic reports | report files | OPERATIONAL_VERIFIED with open historical findings |
| News/knowledge | `src/news`, `src/knowledge`, `src/sources/passive.py` | authorized records/files → read-only research context | allowlisted snapshots | PARTIAL; no default external connector |
| Scheduler/worker | no project-owned scheduler module found beyond operational runner | — | — | MISSING as an explicit application scheduler |
| Backtest/walk-forward | no engine found | — | — | MISSING |
| Risk/order/position management | no engine found | — | — | MISSING |
| Exchange adapter | public Spot WebSocket only | — | no private action | LIVE adapter MISSING |

## Reachable runtime path

`main.py:async_main` constructs `TIMApplication`; `run` connects to PostgreSQL,
restores persisted state, starts the read-only dashboard and awaits
`BinanceTradeStream.run`. Each new trade is persisted before aggregation.
Exact duplicate AggTrades return `False` and do not re-enter aggregation.
Observation and case writes use explicit transactions in
`MarketRepository.save_observation_with_case` and
`save_orderflow_observation_with_case`.

No call from the observation, research or dashboard layers reaches an exchange
order API. This is **BELEGT** for the inspected repository.

## Runtime dependencies

| Dependency | Purpose | Evidence | Risk |
|---|---|---|---|
| PostgreSQL/optional TimescaleDB | durable market and research state | `config/settings.py`, `src/database/*` | availability and schema deployment |
| Binance public Spot WebSocket | BTCUSDT AggTrades | `config/settings.py`, `binance_ws.py` | no historical catch-up; host sleep caused gaps |
| Ollama | optional explanations | `TIM_ENABLE_OLLAMA=false` default | resource contention; must never become decision authority |
| Local dashboard | read-only visibility | default `127.0.0.1:8765` | stale snapshot labels can be misleading |
| Filesystem reports | audit, quality and snapshots | `src/research_ops/*` | historical metadata incomplete |

## Reifegrad and central findings

1. **BELEGT, HIGH:** L1 research operation is reachable and deterministic for
   implemented rules.
2. **BELEGT, HIGH:** no live execution path was found.
3. **BELEGT, HIGH:** current Core is frozen and OBSERVE-only.
4. **BELEGT, HIGH:** continuous coverage at the frozen cut-off was 60.659%
   (663/1,093 one-minute intervals); 430 minutes were missing.
5. **BELEGT, HIGH:** host sleep correlated with all 33 canonical gap groups;
   see `TIM_TRANSPORT_RELIABILITY_REPORT.md`.
6. **BELEGT, HIGH:** replay and hash consistency passed the readiness snapshot,
   while historical audit metadata and hash-domain semantics remained open.
7. **BELEGT, HIGH:** no complete strategy, risk engine, backtest engine, paper
   broker or order state machine exists.
8. **UNVERIFIED:** current long-run coverage after the frozen cut-off was not
   recomputed during this read-only baseline.

## Current autonomy level

**L1**, as detailed in [AUTONOMY_LEVELS.md](AUTONOMY_LEVELS.md).

## Evidence gaps

- No unambiguous project-local Git repository boundary; the parent home
  directory is the visible Git root. This limits clean worktree attribution.
- No packet-level transport telemetry for historical wake periods.
- No current, prospectively defined ≥99.5% qualifying data window.
- No paper order lifecycle or live/shadow execution evidence.
- No strategy contract or risk limits approved for implementation.
- Two tests in the last safe local suite were not green: live research health
  fixture/state mismatch and isolated GPT Researcher dependency failure.

## Read register

Core evidence inspected:

- `README.md`, `config/settings.py`, `config/core_manifest.json`, `main.py`
- `src/models/market_data.py`
- `src/data_ingestion/binance_ws.py`, `aggregator.py`
- `src/database/schema.sql`, `connection.py`, `repository.py`
- `src/analysis/*`, `src/observation/engine.py`
- `src/orderflow/metrics.py`, `observations.py`, `validation.py`
- `src/research/case_engine.py`, `router.py`, `trigger.py`
- `src/paper/automation.py`
- `src/operational/*`, `src/acceptance/monitor.py`
- `tests/*.py` via complete test-function inventory and targeted source reads
- `docs/TIM_CORE_1_0_FREEZE.md`, `docs/TIM_V1_LIVE_STATUS.md`
- `TIM_COVERAGE_ROOT_CAUSE_ANALYSIS.md`
- `TIM_TRANSPORT_RELIABILITY_REPORT.md`
- `TIM_OUTPUT_HASH_ROOT_CAUSE_REPORT.md`
- `TIM_V2_SCIENTIFIC_READINESS_ASSESSMENT.md`

Confidence applies only to this visible repository and its inspected evidence.

