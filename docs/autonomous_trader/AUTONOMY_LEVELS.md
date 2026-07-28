# TIM Autonomy Levels

## Scope

This baseline classifies the executable repository at
`/Users/tim/Documents/TIM/tim`. It is an architectural assessment, not an
authorization to trade. TIM Core 1.0 remains `FROZEN` and `OBSERVE` according
to [`config/core_manifest.json`](../../config/core_manifest.json).

## Level model

| Level | Required runtime capability | Evidence in TIM | Missing evidence | Assessment |
|---|---|---|---|---|
| L0 — Data collection | Receive public market data and persist it | `main.py:TIMApplication.on_trade`; `src/data_ingestion/binance_ws.py:BinanceTradeStream`; `src/database/repository.py:insert_agg_trade` | Coverage is below the future 99.5% target; historical gaps exist | COMPLETE, with data-quality limitations |
| L1 — Research observations | Generate versioned, deterministic observations without execution | `src/observation/engine.py:ObservationEngine`; `src/orderflow/observations.py:OrderflowObservationEngine`; `main.py:process_orderflow_window` | Some requested observation families are absent; no data-quality gate blocks every observation path | COMPLETE for implemented rules |
| L2 — Setup proposals | Produce a complete, machine-readable setup with entry, invalidation, exit and risk | `src/models/market_data.py:Setup` is only a disabled data model | No runtime setup engine, complete strategy contract, decision ID or risk approval | NOT REACHED |
| L3 — Paper orders | Create lifecycle-managed virtual orders and fills | `src/paper/automation.py` provides disabled TEST_ONLY outcome journaling | No paper order state machine, broker, fills, positions, rejection/partial-fill lifecycle or runtime wiring | NOT REACHED |
| L4 — Shadow execution | Compare intended orders with executable market outcomes without sending orders | No implementation found | Entire capability and safety boundary | NOT REACHED |
| L5 — Limited live | Send a bounded live order after explicit human approval | No private client or order endpoint found | Entire capability, independent audit and explicit authorization | NOT REACHED / PROHIBITED |
| L6 — Supervised autonomy | Execute bounded orders autonomously under continuous supervision | No implementation found | Entire capability and governance framework | NOT REACHED / PROHIBITED |

## Evidenced current level

**Highest evidenced level: L1.**

The reachable path is:

```text
public Binance Spot aggTrade
→ immutable persistence
→ deterministic candles and orderflow metrics
→ observations
→ research cases
→ retrospective validation
→ read-only dashboard
```

Evidence:

- `main.py:TIMApplication.run` starts the public stream and dashboard.
- `main.py:TIMApplication.on_trade` persists unique AggTrades before candle
  aggregation and observation evaluation.
- `main.py:process_orderflow_window` creates research observations and cases.
- `src/orderflow/validation.py` documents later outcomes and explicitly states
  that it never predicts them.
- `src/paper/automation.py:PaperPolicy` rejects `test_only=False`, is disabled
  by default, and has no exchange interface.
- Static search found no authenticated exchange client, order endpoint,
  account operation or wallet operation. See
  [LIVE_EXECUTION_RISK_REGISTER.md](LIVE_EXECUTION_RISK_REGISTER.md).

Confidence: **HIGH** for visible repository code. External or undisclosed
systems remain outside this assessment.

## Hard transition gates

| Transition | Mandatory gate |
|---|---|
| L0 → L1 | Deterministic input ordering, versioned rules, input hashes, provenance and data-quality rejection |
| L1 → L2 | One complete strategy contract; no ambiguous entry, exit, invalidation or risk field |
| L2 → L3 | Safety contracts, mode controller, risk authority, kill switch, audit correlation and paper order state machine |
| L3 → L4 | 30–60 days of technically stable paper operation, deterministic replay and independent review |
| L4 → L5 | Separate explicit authorization, independent security/safety audit, manual approval per order and isolated credentials |
| L5 → L6 | Not planned by this baseline; requires a new governance program and separate authorization |

## Prohibition of implicit promotion

No document, model name, dependency, dashboard label, test fixture or
configuration value may promote TIM to a higher level. Promotion requires:

1. reachable runtime code;
2. complete contracts and tests;
3. persisted acceptance evidence;
4. independent approval;
5. a versioned mode transition.

Unknown modes and missing evidence must fail closed. This baseline authorizes
no implementation and no level transition.

