# TIM V1 Scientific Validation Report

## Scope and method

This report records a read-only, repeatable-read database snapshot taken at `2026-07-22T23:02:37.321353+00:00`. No record was created, altered, reconstructed, estimated, or promoted. TIM Core remains `1.0.0`, the database schema is unchanged, and operation remains OBSERVE-only.

## Case coverage

| Measure | Result |
|---|---:|
| Orderflow observations | 246 |
| Eligible observations | 246 |
| Fully validated cases | 165 |
| Excluded or pending | 81 |
| Coverage of all eligible observations | 67.0731707317% |
| Coverage of observations old enough for 30-minute validation | 100.0000000000% |
| Required target | 1,000 |
| Deficit | 835 |

Every observation was governance-valid and linked to a research case. The 81 non-complete cases did not fail validation. They were excluded from the completed population by the forward-only clock: 39 awaited the 30-minute horizon, 31 awaited the 15-minute horizon, and 11 awaited the initial 5-minute horizon. There were zero mature observations without validation, zero governance rejects, and zero missing case links at the snapshot.

Pipeline classification was derived from observation time, the fixed snapshot time, research-case linkage, and persisted validation horizons. This avoids treating immature cases as failed cases.

## DATA_GAP audit

The closed 1-minute candle series spans `2026-07-20T13:45:00+00:00` through `2026-07-22T23:01:00+00:00`. A complete minute grid contains 3,437 intervals; 1,464 are persisted and 1,973 are absent. Coverage is therefore 42.5952865871%. The missing intervals form 156 separate ranges: 14 minutes on July 20, 1,084 on July 21, and 875 on July 22 (UTC).

The largest ranges were 17 minutes each: `2026-07-22 13:41–13:58`, `13:06–13:23`, `12:45–13:02`, `02:23–02:40`, and `2026-07-21 15:28–15:45` UTC. Exact enumeration is reproducible with the query below; the machine-readable report records the totals, daily distribution, and largest ranges.

Operational stderr contains 147 `Binance public stream disconnected` entries, including keepalive timeouts and missing close frames. Every detected gap range contained zero persisted AggTrades. Raw AggTrade persistence began only at `2026-07-22T20:13:21.782000+00:00`; therefore earlier missing market records cannot be distinguished further or reconstructed from TIM persistence. The defensible classification is `SOURCE_OR_PERSISTENCE_GAP_DURING_STREAM_DISCONNECTIONS`, not an inferred market state.

Impact: candles are absent for 1,973 expected intervals. Observations and cases that would have required those candles cannot exist. The historical interval is unsuitable for claims requiring continuous coverage. Existing orderflow cases begin after raw persistence and remain internally forward-only, but they do not repair the historical coverage deficit.

Detection proof: the Acceptance health matrix reports `candle_sequence_gap_free=false` and critical `DATA_GAP`. The quality audit also reports `UNDOCUMENTED_DATA_GAP` because no corresponding `DATA_GAP` event exists in `events.jsonl`. No backfill or synthetic reconstruction was performed.

Reproducible check, conceptually: generate every minute between the first and last persisted closed 1-minute candle; left-join closed BTCUSDT 1-minute candles; group consecutive absent minutes; then count persisted AggTrades whose exchange timestamps fall in each absent range. Run inside one repeatable-read, read-only transaction.

## Replay, hashes, versions and governance

Two immediate reads of `/api/insights` returned byte-identical payloads with SHA-256 `4a02539690c25eb98e9b841ac2201b026baab39e3c976565f9ae6ae68bedc2d9`. Both contained dataset hash `88fe24801108df443fccc18e4c144312556b3bc6ca5fdfd91624fa3b342d8c2d` and output hash `794c3675e350b009d225408a54382b69ed19d1907ea7a3929510e76985bf5738`.

The read-only Insights exports were generated successfully and hashed: JSON `1c9dee5f9fa72dc3d383048b6c16ff662e9f2923eeac337dfae03fc187a99411`, CSV `eeb3a39d25ba840bc5c18ffed84e40ca0e6fa8772caa6180ed42965f5d716409`, and Markdown `f87295a6c34502481473f9f474b085b66fb0e08a0334394fdb228bc473c5fb24`. Export generation occurred after the fixed database snapshot while the live stream continued; these hashes prove serialization integrity for that export instant and are not substituted for the fixed coverage counts.

Core, metrics, rules, and validation versions were all `1.0.0`. Schema validation, timestamp integrity, forward-only validation, and OBSERVE-only checks passed. Export/research artifact hashes are enumerated in `data/research/audit/latest.json`; 11 of 12 artifacts passed integrity inspection.

The artifact audit and quality report remain FAIL. Exactly 1,172 legacy Module A cache records lack `artifact_hash`, `generator_version`, and `schema_version`. Acceptance provenance coverage is incomplete, and the detected gap lacks a matching event record. These source records were intentionally not rewritten because this audit is read-only and retroactive metadata would not establish historical provenance.

## Data quality and scientific limitations

The completed orderflow population is deterministic for the fixed input set and all mature eligible cases are validated. Its size is nevertheless only 165, far below the required 1,000. The data window is short, historical minute coverage is 42.5952865871%, and the missing intervals are not randomizable or recoverable from persisted raw data. No claim of broad statistical representativeness is justified.

TIM Research V1.0 is therefore not scientifically complete. Completion requires at least 835 additional naturally matured, fully validated cases, a sufficiently documented continuous data window, and closure or explicit acceptance of the provenance/documentation findings. This conclusion contains no market interpretation, forecast, score, or recommendation.

## Evidence

- `data/research/validation/tim_v1_scientific_validation.json`
- `data/research/audit/latest.json`
- `data/research/quality/latest.json`
- `data/research/snapshots/2026-07.in_progress.json`
- `data/operational/state.json`
- `data/operational/runtime_launchd.err.log`
