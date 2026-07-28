# TIM v1 Controlled-Unfreeze Final Audit Report

Run ID: `TIM-V1-UNFREEZE-20260727T170852Z`  
Decision: **PASS WITH DOCUMENTED RISKS**  
Operating mode: **OBSERVE-only**

## Executive summary

TIM v1 was backed up, restored in isolation, inventoried and exercised through a ten-run deterministic end-to-end audit. The live database was inspected without mutation. No trading or authenticated exchange path exists. Scientific event-time boundaries, persistence ordering, atomicity, fixed orderflow direction, forward-only validation and content hashes are coherent.

The controlled unfreeze did not change Core rules, metrics, thresholds, schema, configuration, database rows, snapshots or historical reports. It added only audit documentation, machine-readable evidence and a standalone test-only pipeline runner.

## Backup and rollback

- External backup: `/Users/tim/Documents/TIM/backups/tim_v1_pre_unfreeze_20260727T170226Z`
- Files: 247
- Inventory SHA-256: `9e817d14f23f44aa70a0d355e7d62b391a24d4d7f97318a4da6f985e0d312dad`
- Isolated restore: 247/247 hashes matched
- Import smoke test: PASS
- Baseline test discovery: 172 tests

## Data integrity

At the audit cut:

- 2,458,107 aggTrades
- 10,258 candles
- 7,041 candle observations
- 15,708 research cases
- 14,660 orderflow observations
- 14,653 orderflow validations
- duplicate aggTrade identities: 0
- duplicate candle identities: 0
- future rows checked: 0

AggTrades are persisted before aggregation. Exact reconnect replays are ignored and conflicting same-ID payloads are rejected. Observation/case and validation/case writes are transactional.

## Scientific pipeline

Orderflow direction follows Binance semantics:

- `buyer_is_maker = false`: aggressive buyer volume
- `buyer_is_maker = true`: aggressive seller volume

Metrics sort by exchange time and aggregate-trade ID, use Decimal arithmetic after persistence, and hash a canonical trade list. Observations require two deterministic clauses. Outcomes use only post-observation trades at matured 5/15/30-minute horizons.

No future leakage was found. LLM output, dashboard state and manual text do not feed scientific rules.

## Reproducibility

Ten identical end-to-end runs produced one unique value for each hash:

| Hash | Value |
|---|---|
| dataset | `ee7c4b770368a035a816f306943d9a0211e55d538b625774192cd23beac5d8c7` |
| input | `71417848d23c90871f484973571cab2da54e57967358367fa64560b8bd22d8e4` |
| output | `dbe3a06dc91f7696687639b398ea95141a9306f50b516428a31407f6f5fb2c62` |
| replay | `c0c2e1fc8c1eb7e3be1fe35da0cbeebdf238e3c65b1cc2ba5b38f94552d30bd1` |

The fixture is explicitly TEST_ONLY and is not presented as market evidence.

## Model, RAG and external-source assessment

- Ollama is disabled by default and used only for optional explanations/planning.
- Model output is prohibited from creating orders and is not persisted as scientific truth.
- Module A is deterministic and local; external search reports `false`.
- Module B accepts only explicitly supplied local evidence and preserves citations.
- News and GoatHub ingestion require source authorization.
- No embedding/vector retrieval pipeline was found; therefore embedding leakage and vector nondeterminism are not active concerns.

## Findings

No P0 scientific-integrity defect was reproduced.

Documented risks:

1. Live transport gaps cannot be reconstructed by v1 (P1).
2. Exchange decimal strings are converted to float64 before Decimal arithmetic (P1).
3. Wall-clock `created_at` metadata is outside scientific equality (P2).
4. Equal-timestamp live ordering relies on Binance delivery order (P2).
5. Active candle state is memory-resident across abrupt restart boundaries (P2).
6. Historical research artifacts retain known governance/hash-contract limitations (P2).
7. The pytest launcher has a stale absolute shebang; the verified command is `python -m pytest` (P3).

These findings do not authorize historical reconstruction or Core mutation.

## Scope compliance

- Core functionality changed: no
- Schema changed: no
- Database changed: no
- Historical artifacts changed: no
- Trading enabled: no
- Orders executed: no
- Synthetic data used as evidence: no
- Runtime interrupted: no

## Conclusion

TIM v1's implemented scientific pipeline is internally coherent and reproducible within its declared event-time and persistence contracts. It remains unsuitable for claims requiring uninterrupted data coverage during documented transport gaps. Future work should address transport reliability and exact decimal contracts in a separately versioned design, not by rewriting TIM v1 history.
