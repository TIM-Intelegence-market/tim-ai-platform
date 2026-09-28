# Mission 08 — Verified history expansion and missing feature completion

Status: implementation and bounded research run delivered; full Mission 08
acceptance NOT achieved. Sufficient new SHORT live history has NOT been collected.
Research only; execution and live trading disabled. No old collection, legacy
row, queue, recovery code or Mission 07 artifact is modified.

## Exact deterministic history contract, version 2.0.0

| Horizon | Primary closed bars | Additional calendar context | Price-level profile | Minimum actual trade observations |
|---|---|---|---|---|
| SHORT | 60 consecutive 1m | 2 consecutive closed UTC 1h | trailing 60 full minutes | >=60, at least one per profile minute; volume reconciles to minute bars |
| MID | 168 consecutive 1h (10,080 complete 1m constituents) | 2 closed 1h, 2 closed 4h, 2 closed Daily | trailing 10,080 minutes | >=10,080, at least one per profile minute |
| LONG | 90 consecutive Daily (129,600 complete 1m constituents) | 2 closed Daily, 2 closed Weekly, 2 closed calendar Monthly | trailing 129,600 minutes | >=129,600, at least one per profile minute |

Counts are conjunctive, not additive; periods can share input minutes. SHORT
therefore also needs 120 complete minute constituents spanning two aligned hour
windows, and real trade evidence to verify those bars. At an arbitrary collection
start, up to approximately three hours are needed to close two fully observed
hours. MID does not require Weekly/Monthly bars; SHORT does not require Daily,
Weekly or Monthly bars. These are still reported when supported. LONG must pass
its independent Monthly gate: 90 Daily bars do not always contain two full
calendar months. Weeks start Monday 00:00 UTC; months use calendar boundaries,
including leap years. Partial first/last periods never count.

The prior-20-bar structure, relative-volume and volatility calculations need
21 primary bars; close-pair structure needs 2, imbalance needs 3, four-bar-pair
proxy needs 8, signed latest volume needs 1. Existing 60/168/90 primary windows
are retained as explicit research sampling policies, not falsely represented as
mathematically necessary lookbacks or calibrated profitable strategy windows.
The additional profile/context rules above use all their declared inputs. The
registry supplies versions, inputs, lookbacks, quality and missing-data behavior.

History sufficiency requires primary, required HTF and profile coverage. READY
also requires >=80% verified evidence and full feature scope. Zero-trade minutes
are not synthesized. Freshness requires the latest full period to end at the
current period boundary. Old, separated collections cannot fill intervening gaps.

## Implemented calculations and evidence

Volume profile uses actual timestamped trade prices/quantities, Decimal sums,
fixed 10 USDT floor bins and deterministic lower-price ties. POC is the center
of the largest-volume bin. VA expands into adjacent bins until >=70% of volume;
VAL is its lower edge, VAH its upper edge. Empty internal bins have zero volume.
A >100,000-bin price span fails closed. HVN/LVN are strict local maxima/minima
among occupied neighboring bins, descriptive rather than inferred liquidity.
Price-bin constants are research conventions, not an adaptive fit. A partial
profile may show descriptive levels but stays NOT_READY. Publication/event
filtering occurs before binning and hashes; duplicated trade IDs are deduplicated,
conflicting IDs rejected. Trade volume must reconcile to every profile minute.

HTF aggregation requires every expected valid minute, without interpolation.
Context compares the latest two closed high/low pairs; it does not claim a
20-period Weekly/Monthly BOS. An aggregate with any legacy minute is labeled
LEGACY; exact verified-minute count remains visible. Bar evidence weighs
VERIFIED=1 and LEGACY=0.5, with >=80% fully verified bars required for READY.
Legacy trades were not imported or invented. SHORT uses only verified candles;
MID/LONG additionally use a bounded read-only legacy snapshot.

Legacy candles lack historical publication timestamps. Their availability is
set to the database snapshot timestamp, so they cannot support retrospective
claims before that timestamp. The snapshot is frozen, includes original rows,
and is copied into the versioned research artifacts. One malformed OHLC minute
is separately recorded in legacy_rejections.json and omitted, never repaired.

## Derivative source inventory

The deployed collection is Binance SPOT aggTrade. Code inventory finds derivative
interpretation fields, but no configured validated OI/Funding/Liquidations feed;
the read-only database inventory finds no corresponding tables. No derivative
network adapter is fabricated, activated or marked READY. All three stay MISSING.

The pure normalized replay contract is tested with explicitly synthetic fixtures:
OI requires two distinct observations <=300s apart, latest age <=300s; funding
requires a settled observation aged <=28,800s (a policy TTL, not a claim about
an exchange's funding schedule); liquidations require authenticated continuous
300s coverage, with zero events allowed only when coverage itself is proved.
Source, market, symbol, provenance, event time and availability are checked.
These contract tests are not proof of a deployed available feed. Missing inputs
veto readiness and theses; they receive no redistributed confidence weight.
The expanded feature-coverage multiplier can only reduce Mission 07 confidence.

## Collection boundary and remaining blocker

The existing hash-bound VerifiedJournal contract enforces <=300 seconds and
<=10,000 events. This run respects it and collects 2,274 new verified events,
including 4 complete minutes, before automatically closing. With the previous
collection, there are 4,249 events and 8 complete minutes in two separated
segments. There is no claim of uninterrupted coverage between the segments.
The 120 minute constituents for SHORT's two closed hours are not available.

Smallest safe next step: implement and validate an isolated, explicitly bounded
continuous collection campaign that preserves one socket and proves continuity
across <=300s journal segments, without changing the stable journal/queue/recovery
internals. It must have a whole-campaign time/event limit, runtime/resource checks,
fail-closed interruption handling and cross-segment receipt/ID coverage tests.
Then run it until two fully observed UTC hours and the trailing profile close,
or its boundary/safety stop is reached. Reconnecting short sessions is not proof
of continuity. No such campaign is implicitly scheduled or left running here.

MID/LONG additionally remain blocked by stale/discontinuous legacy evidence,
insufficient Daily/Weekly/Monthly coverage and missing derivative sources. The
Mission 07 quote quality, actual passive absorption, spot-vs-perp and long-term
spot-demand/accumulation evidence gaps also remain explicit; technical scope is
not falsely declared complete.

## Reproducibility and tooling

Run the new test file together with the existing research/verified-collection
and collection accounting/reporting suites. The Mission 08 entrypoint requires a
passing source-hash-bound test proof, checks journals read-only twice, compares
full results and per-horizon hashes, and verifies journal bytes are unchanged.
Analysis directories include source and test identity and are created exclusively.
The previous Mission 07 inputs are separately reassessed, and before/after
coverage, evidence, direction, state and confidence are recorded.

Graphify performs a fresh local code-only AST extraction of the intelligence
module. It does not claim semantic or whole-repository coverage. Its graph and
manifest are delivered separately with the final acceptance artifacts. Ollama
(llama3.2:latest, local) reviews only aggregate quality findings read-only; its
advisory output cannot enter feature decisions or hashes. No Omniroute call is
needed: the blockers are directly observable, not unresolved statistical issues.
