# TIM Test Readiness Matrix

## Legend

- **STRONG:** direct deterministic and negative tests exist.
- **PARTIAL:** some behavior is tested; critical lifecycle cases are absent.
- **MISSING:** no test class found.
- **BLOCKED:** test exists but the current environment does not pass it.

## Current execution evidence

The latest safe local suite executed during the surrounding maintenance
session produced:

```text
166 passed
2 failed
```

Failures:

1. `tests/test_operational_validation.py::test_live_research_monitor_matrix_is_green`
   — persisted live state was RED while the test expected GREEN.
2. `tests/test_research_module_b.py::test_module_b_local_report_and_isolated_gpt_researcher`
   — isolated environment could not import `pydantic_core`.

This baseline did not install dependencies, start services or mutate tests.

## Matrix

| Test area | Evidence | Status | Principal gap |
|---|---|---|---|
| Unit tests | analysis, models, quality, metrics, observations, analytics | STRONG | not every error branch/property is covered |
| Integration persistence | AggTrade, atomic observation/case, restart cases | STRONG | no failure-injection against a real PostgreSQL outage |
| End-to-end live pipeline | `smoke_binance.py`, dashboard tests | PARTIAL | live smoke is not a deterministic CI E2E proof |
| Replay/determinism | benchmark, AggTrade replay, metrics, observations, insights | STRONG | no full database-to-dashboard golden replay across all components |
| Replay mismatch | audit/quality tampering tests | PARTIAL | no universal cross-domain hash-contract validator |
| Feature hashes | orderflow metrics and insights | STRONG for implemented features | absent features have no tests |
| Data quality/gaps | `test_data_quality.py`, `test_acceptance.py` | STRONG | future 99.5% operational window not proven |
| Forward-only/look-ahead | validation, memory, news, research cases | STRONG for research | no backtest engine exists |
| Fees/slippage | `test_paper_automation.py` | PARTIAL | fixed arithmetic only |
| Funding | none | MISSING | source and engine absent |
| Latency | dashboard/API operational checks | PARTIAL | no event/fill latency |
| Walk-forward/OOS | none | MISSING | engine absent |
| Risk engine and limits | none | MISSING | engine absent |
| Paper broker | TEST_ONLY journal tests | PARTIAL | no orders, positions or broker |
| Partial fills/rejections | none | MISSING | paper order state machine absent |
| Order state machine | none | MISSING | — |
| Kill switch | none | MISSING | contract and implementation absent |
| Audit integrity | research audit/quality/health tests | PARTIAL | historical metadata and hash-domain issue remain |
| Governance | repository constraints, OBSERVE-only, forbidden LLM output | STRONG for current Core | no future mode-controller tests |
| Dashboard read-only | extensive route, restart and no-controls tests | STRONG | live/historical status semantics recently required clarification |

## Safety coverage

Current safety is primarily absence-based: no exchange adapter exists. Tests
prove that TEST_ONLY paper mode cannot become non-test mode and that execution
events fail acceptance. They do not yet prove a protected path, kill switch,
risk authority or credential isolation because those components are absent.

## Priority test gaps

1. **P0:** future mode controller must fail closed for missing/unknown modes.
2. **P0:** protected path registry must reject every direct execution bypass.
3. **P0:** kill switch and risk denial must dominate any strategy decision.
4. **P0:** bad freshness, coverage, provenance or replay must block decisions.
5. **P1:** paper order lifecycle including rejected and partial fills.
6. **P1:** forward-only backtest with realistic fees, slippage and latency.
7. **P1:** deterministic full-pipeline golden replay.
8. **P2:** dependency-isolated Module B health and reproducible environment.

No existing test name is treated as proof beyond its asserted behavior.

