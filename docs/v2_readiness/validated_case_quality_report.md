# TIM V2 Validated Case Quality Report

Status: **FAIL**

Scientific gate: **NOT MET**

Mode: **OBSERVE**

This report audits the frozen historical case claim. It does not approve V2,
change Core 1.0, authorize trading, or combine the frozen population with the
later mutable database total.

## 1. Frozen scope and reconstruction

| Field | Fixed value |
|---|---|
| Case evidence cut-off | 2026-07-23T14:27:42.127641Z |
| Case period | 2026-07-22T21:29:00Z through 2026-07-23T13:57:00Z |
| Elapsed span | 16 hours 28 minutes across two UTC dates |
| Market | Binance Spot |
| Instrument | BTCUSDT |
| Timeframe | 60 seconds |
| Reconstruction rule | Complete orderflow validations with validated_through at or before the fixed cut-off |
| Frozen complete labels | 1,339 |

The fixed cut reconstructs the published 1,339-label population without using
records created after the cut-off. The 21,474 complete validations observed at
the separate 2026-08-01 operational baseline are live, later evidence and are
not a frozen replacement for this population.

## 2. Referential and identity integrity

The fixed population has:

- 1,339 unique observation IDs;
- 1,339 unique input hashes;
- 1,339 unique validation hashes;
- zero missing expected research-case links;
- zero case status/outcome mismatches; and
- zero case-to-observation link mismatches.

These checks support internal referential integrity. They do not establish
statistical independence. An orderflow observation hash includes the
observation kind and evidence, so distinct labels on the same market window
can legitimately have distinct input hashes.

## 3. Quality, deduplication, and independence

The correct unit distinction is label versus underlying market window.

| Audit view | Count | Interpretation |
|---|---:|---|
| Complete validation labels | 1,339 | Raw published count |
| Unique underlying observation times/source windows | 554 | Same minute can emit multiple observation kinds |
| Labels missing at least one required 5/15/30-minute horizon | 64 | Raw complete flag is too permissive |
| Labels whose two-minute input or 30-minute outcome interval overlaps a persisted aggregate-trade-ID discontinuity | 429 | Source continuity is not demonstrated |
| Strict labels with all three horizons, intact case/provenance relationships, and no source-gap overlap | 910 | Conservative quality-screened label count |
| Strict unique underlying source windows | 378 | Deduplicated by observation time in this one-market, one-timeframe population |
| Greedy non-overlapping 30-minute windows, all raw labels | 30 | Upper independence check before strict quality screen |
| Greedy non-overlapping 30-minute windows, strict population | 14 | Conservative independent evidence count |
| Required quality-screened independent cases | 1,000 | Documented gate |

The horizon and source-gap filters overlap and therefore must not be subtracted
as independent sequential losses. The reproducible strict intersection is
910 labels. After source-window deduplication it is 378, and after a
30-minute non-overlap screen it is 14. The 1,339 raw labels cannot be used as
1,339 independent, quality-screened cases.

Underlying-window label multiplicity was:

| Labels emitted at one observation time | Number of source windows |
|---:|---:|
| 1 | 171 |
| 2 | 150 |
| 3 | 115 |
| 4 | 71 |
| 5 | 43 |
| 6 | 4 |

These 554 windows account for all 1,339 labels.

## 4. Source-gap evidence at the fixed cut

The fixed-cut aggregate-trade sequence contained 39 discontinuity events and
158,066 missing aggregate trade IDs. The first audited discontinuity begins
around 2026-07-22T20:13:59.509Z, the last recovery is around
2026-07-23T12:26:38.597Z, and the largest single missing-ID interval contains
13,222 IDs.

The existence of a 30-minute outcome is not evidence that every intermediate
trade was present. The frozen rows were created under pre-remediation behavior
that could mark a result complete without all intermediate horizons or source
continuity. Final prospective code now requires 5/15/30-minute horizons and a
continuous aggregate-trade-ID sequence before `complete=true`; it deliberately
does not rewrite the frozen rows. The strict historical screen therefore
remains necessary.

## 5. Population composition

### UTC date

| UTC date | Labels |
|---|---:|
| 2026-07-22 | 402 |
| 2026-07-23 | 937 |

### UTC session

| Session | Labels |
|---|---:|
| Asia | 691 |
| Europe | 246 |
| US | 402 |

### Descriptive outcome

| Outcome | Labels |
|---|---:|
| PRICE_DECREASED | 511 |
| PRICE_INCREASED | 250 |
| PRICE_SIDEWAYS | 578 |

### Observation kind

| Observation kind | Labels |
|---|---:|
| EXTREME_BUY_RATIO_ACTIVITY | 71 |
| EXTREME_SELL_RATIO_ACTIVITY | 90 |
| FALLING_CVD_ACTIVITY | 197 |
| HIGH_TRADE_FREQUENCY | 67 |
| LARGE_INDIVIDUAL_TRADE_ACTIVITY | 517 |
| RISING_CVD_ACTIVITY | 162 |
| STRONG_BUYER_ACTIVITY | 107 |
| STRONG_SELLER_ACTIVITY | 128 |

The outcomes are post-observation price descriptions. They are not
preregistered positive/negative hypothesis labels.

## 6. Bias and review limitations

- Only detector-fired labels are persisted. Rejected and non-triggered windows
  are absent, so the selection-bias denominator cannot be measured.
- Negative/control sampling is absent.
- The population covers one symbol, one market, one timeframe, and less than
  one day of elapsed market time.
- Volatility and liquidity regime labels are absent.
- There is no per-case persisted coverage verdict; the strict screen was
  independently reconstructed.
- Reviewer identity, review status, adjudication, and inter-rater fields are
  absent from the V1 case/validation schema.
- No immutable original case manifest at the fixed cut was supplied; the
  population was reconstructed from persisted timestamps.
- scripts/research_infrastructure_review.py counts complete=true rows and
  treats a raw count of at least 1,000 as PASS. It does not enforce all
  horizons, source continuity, source-window deduplication, temporal
  independence, or manual review.
- That readiness generator is calendar-month scoped. An August rerun changes
  the numerator scope, so it must not be used to merge the July fixed cut with
  later live records.

## 7. Verdict

The validated-case-quality gate **FAILS**. Referential integrity is strong,
but the scientific claim of at least 1,000 deduplicated,
quality-screened, independent cases is not supported:

- strict quality-screened labels: **910**;
- strict unique source windows: **378**;
- strict non-overlapping 30-minute windows: **14**.

Required remediation is a prospectively frozen qualifying dataset with
source-continuity enforcement, explicit negative/control sampling, regime
labels, a preregistered hypothesis and analysis plan, and independent human
review. Until then, the case evidence is descriptive and exploratory only.

## 8. Evidence references

- docs/v2_readiness/pre_remediation_baseline.md
- artifacts/v2_readiness/baseline_manifest.json
- artifacts/v2_readiness/manual_review_sample_manifest.json
- src/v2_readiness/case_audit.py
- scripts/v2_readiness_audit.py
- src/orderflow/validation.py
- scripts/research_infrastructure_review.py
- src/database/repository.py
- TIM_V2_READINESS_CHECKLIST.md

Protected reference hashes:

| Artifact | SHA-256 |
|---|---|
| Frozen July snapshot | 81fb9617b01ddd2f9dcf6651a0a433b8a9641052d6152d9c4541344b0aa0ada3 |
| Frozen readiness status | 7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a |
| Core manifest | 82bfe439178299adc5bca0ac1de17614a3fd5fe6ed72a110861f88af9d014ca6 |
| V2 readiness checklist | 696ad64f88441d65ac5c857ecdc60e73a1d1983bc611b8113a0b97291666f1f5 |
