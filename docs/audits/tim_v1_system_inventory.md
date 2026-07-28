# TIM v1 System Inventory

Audit run: `TIM-V1-UNFREEZE-20260727T170852Z`  
Mode: read-only inspection; production remains `OBSERVE`.

## Runtime and entry points

- `main.py`: composition root for database, public Binance Spot aggTrade stream, deterministic aggregation, observations, cases, validation, optional explanations, dashboard.
- `src/data_ingestion/binance_ws.py`: unauthenticated `btcusdt@aggTrade` transport, parsing, ping/pong and retry.
- `src/data_ingestion/aggregator.py`: in-memory UTC bucket aggregation for 1m/5m/15m/1h.
- `src/database/{connection,repository}.py`: async PostgreSQL pool and persistence boundary.
- `src/dashboard/app.py`: read-only HTTP dashboard and JSON APIs.
- `src/operational/runner.py`: operational validator, metrics, benchmark and health cycles.

## Scientific components

- Candle observations: `src/analysis`, `src/observation`.
- Orderflow arithmetic: `src/orderflow/metrics.py`.
- Orderflow observations/cases: `src/orderflow/observations.py`.
- Forward outcome validation: `src/orderflow/validation.py`.
- Research cases/memory/analytics: `src/research`, `src/memory`, `src/analytics`, `src/insights`.
- Quality/audit/snapshots: `src/quality`, `src/research_ops`, `src/acceptance`.
- Local research text: Module A and Module B. External web retrieval is disabled.
- Optional Ollama explanations are isolated from persistence and disabled by default.

## Data stores

- PostgreSQL: `agg_trades`, `candles`, `observations`, `research_cases`, `orderflow_observations`, `orderflow_validations`.
- File artifacts: `data/research`, `data/operational`, `data/system`, `data/source_snapshots`.
- Immutable pre-audit backup: `/Users/tim/Documents/TIM/backups/tim_v1_pre_unfreeze_20260727T170226Z`.

## Live inventory at audit time

| Dataset | Rows |
|---|---:|
| agg_trades | 2,458,107 |
| candles | 10,258 |
| observations | 7,041 |
| research_cases | 15,708 |
| orderflow_observations | 14,660 |
| orderflow_validations | 14,653 |

AggTrade UTC range: 2026-07-22 20:13:21.782 through 2026-07-27 17:06:55.148. Distinct persisted trade minutes: 6,448.

## External integrations

- Binance Spot public WebSocket only.
- Local PostgreSQL.
- Optional local Ollama endpoint.
- Authorized news/knowledge ingestion APIs exist, but no automatic external connectors are enabled.
- No authenticated exchange endpoint, API-key order path, or execution component was found.

## Environment and repository boundary

The TIM directory is not a dedicated Git repository. Its enclosing user-home repository was therefore not branched or committed. The external content-addressed backup is the rollback boundary. The local pytest launcher contains a stale absolute interpreter path; `.venv/bin/python -m pytest` is the verified invocation.
