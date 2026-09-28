# TIM V2 Data-Gap Root Cause Analysis

Forensic cut-off: `2026-08-01T15:15:27.258264Z`

Technical RCA status: **CAUSES IDENTIFIED, INDEPENDENT SIGN-OFF OPEN**

Readiness blocker V2-B02: **OPEN**

This analysis classifies the current canonical minute ranges without changing
historical data or claiming blocker closure. Its structured companion is
[system_downtime_evidence.json](../../artifacts/v2_readiness/system_downtime_evidence.json).

## Priority semantics

The 283 range records are machine-labelled P1 because no prospective qualifying
scientific interval has been approved. This does not reduce blocker priority:
V2-B02 is OPEN P0 in the binding blocker register. The register also refers to a
"frozen qualifying window", while the remediation plan requires a prospectively
defined qualifying window. Therefore the 33 ranges/430 minutes in the frozen
published interval are recorded as P0 candidates pending a human Governance and
Integrity interpretation. The ambiguity is fail-closed and cannot promote
readiness. Machine-readable semantics are in
`artifacts/v2_readiness/gap_priority_policy.json`.

## Count reconciliation

Several existing artifacts use the word “gap” for different units. They must
not be compared as if they were one metric.

| Count | Unit and cut-off | Meaning |
|---:|---|---|
| 367 | Raw log records at frozen quality cut-off | Every `known_data_gaps` item in the frozen quality artifact |
| 63 | Raw log records after the first maturity-history timestamp | Readiness generator’s `unresolved_new_gap_count` |
| 33 | Canonical contiguous minute ranges | Frozen coverage interval, 430 missing minutes |
| 283 | Canonical contiguous minute ranges | Frozen start through forensic current cut-off, 4,600 missing minutes |

The 63 value is calculated in
[research_infrastructure_review.py](../../scripts/research_infrastructure_review.py)
by counting log events, not unique intervals. The readiness program requires a
canonical immutable ledger; that ledger does not yet exist as a reviewed
artifact.

## Coverage-boundary findings

At the forensic cut-off:

- total missing minutes: **4,600** in **283** canonical ranges;
- longest range: **685 minutes**;
- frozen interval: **430 minutes** in **33** ranges;
- after the frozen interval: **4,170 minutes** in **250** ranges;
- missing minutes with no persisted aggTrade in the same minute: **4,597**;
- missing minutes with persisted aggTrades but no closed `1m` candle: **3**.

The absence of raw data in 4,597 missing minutes places the dominant failure at
or before collection, not merely at candle derivation.

## Range-level cause allocation

| Cause class | Ranges | Minutes | Evidence strength | Disposition |
|---|---:|---:|---|---|
| Frozen local-host sleep | 33 | 430 | Existing forensic reports correlate all frozen ranges with sleep/disconnect evidence | Cause supported; historical loss retained |
| Current host sleep, overlap at least 90% | 244 | 3,333 | Read-only `pmset -g log` correlation | Cause supported; mutable OS log |
| Current host-sleep boundary overlap | 4 | 14 | Partial overlap at transition boundaries | Cause supported with boundary qualification |
| Host/process downtime, 2026-07-27 | 1 | 138 | Reboot history, runtime resume, raw/candle boundary | Cause supported |
| Host shutdown/reboot, 2026-08-01 | 1 | 685 | Shutdown, reboot and PID start align with range | Cause supported |
| **Total** | **283** | **4,600** | Complete arithmetic allocation | Not a signed blocker closure |

The two long process ranges are:

- `[2026-07-27T06:59:00Z, 2026-07-27T09:17:00Z)`, 138 minutes. Host reboot
  history reports a reboot at `2026-07-27 10:56` Europe/Berlin; TIM resumed at
  approximately `11:16` local.
- `[2026-08-01T03:18:00Z, 2026-08-01T14:43:00Z)`, 685 minutes. Host history
  reports shutdown at `05:18`, reboot at `16:42`, and TIM PID 552 start at
  `16:43:33` Europe/Berlin.

The frozen evidence is documented in
[TIM Transport Reliability Report](../../TIM_TRANSPORT_RELIABILITY_REPORT.md),
[TIM WebSocket Failure Analysis](../../TIM_WEBSOCKET_FAILURE_ANALYSIS.md), and
[TIM Coverage Root Cause Analysis](../../TIM_COVERAGE_ROOT_CAUSE_ANALYSIS.md).
The official-source activity check in
[TIM Missing Input Forensics Report](../../TIM_MISSING_INPUT_FORENSICS_REPORT.md)
found Binance kline activity for all 430 frozen missing minutes. That check
proves market activity but does not itself recover or substitute aggTrades.

## Raw-present candle-persistence anomalies

Exactly three missing candle minutes contain persisted source trades:

| Minute UTC | Raw trades | Aggregate-trade IDs | Technical cause |
|---|---:|---|---|
| `2026-07-27T06:59:00Z` | 155 | `4022922860`–`4022923014` | Last active bucket before host/process downtime was never durably flushed |
| `2026-07-27T09:16:00Z` | 41 | `4022998419`–`4022998459` | Candle close rejected at the wall-clock boundary; aggregator had already advanced |
| `2026-08-01T03:18:00Z` | 13 | `4027457348`–`4027457360` | Last active bucket before shutdown was never durably flushed |

For the middle anomaly,
[runtime_launchd.err.log](../../data/operational/runtime_launchd.err.log)
line 12060 records at `2026-07-27 11:16:59,985` local:
`Future candle timestamps are not allowed`. The first trade of the next minute
closed the `09:16Z` candle about 15 milliseconds before the wall clock reached
its `09:17Z` close timestamp.

## Causal chain in the implementation at the forensic cut-off

The following findings are bound to committed evidence
`5382e9cc399fea6f2f5a535d6b612f139768ad4f` and can be reproduced with
`git show 5382e9cc399fea6f2f5a535d6b612f139768ad4f:<path>`. Concurrent uncommitted
work now visible in the shared working tree expands restart replay and adds a
one-second close-time tolerance. Those changes are remediation candidates, not
evidence that the historical cause or readiness blocker has passed; this audit
did not restart the runtime or validate them against a qualifying run.

At the forensic baseline, the causal chain was:

1. [binance_ws.py](../../src/data_ingestion/binance_ws.py) reconnects the
   forward-only WebSocket but performs no aggregate-trade-ID catch-up.
2. [main.py](../../main.py) persists each raw trade, mutates the in-memory
   aggregator, and only then persists returned candles in a separate operation.
3. [aggregator.py](../../src/data_ingestion/aggregator.py) holds the active
   candle only in memory and advances to the next bucket before persistence is
   confirmed.
4. The baseline version of
   [repository.py](../../src/database/repository.py) rejected a candle whenever
   `close_time` is even fractionally ahead of wall clock.
5. The baseline restart restoration in [main.py](../../main.py) replayed only
   the current hour, not from the last durable aggregate-trade ID or incomplete
   candle.

The resulting root-cause classes are `LOCAL_HOST_SLEEP`,
`HOST_OR_PROCESS_DOWN`, `NO_SEQUENCE_CATCHUP`, `IN_MEMORY_UNFLUSHED_BUCKET`,
and `CLOCK_BOUNDARY_VALIDATION_WITH_NONATOMIC_ADVANCE`.

The remediation commit `5e6d9bb` now allows only a bounded one-second close
boundary skew, replays raw data from the oldest latest durable candle, and
persists replay-emitted completed candles. Targeted tests and one controlled
launchd restart passed. This prospectively repairs the confirmed close-boundary
and current-hour/discard defects; it does not add exchange-ID catch-up or alter
the 4,600 historical missing minutes.

## Required remediation evidence

The following work is required before V2-B02 can be independently verified:

- an append-only canonical ledger containing all 283 ranges, original event
  references, UTC boundaries, duration, affected streams, cause, recovery,
  scientific impact, owner, disposition, and evidence hashes;
- durable tracking of the last aggregate-trade ID and deterministic catch-up;
- retry-safe candle persistence without losing aggregator state;
- independently accept the implemented durable-boundary replay;
- independently accept the bounded clock-boundary tolerance;
- collector supervision and an explicit host-sleep prevention/availability
  policy for approved observation runs;
- an independent reviewer’s reconciliation and signature.

No historical value is reconstructed by this RCA. Official-source backfill is
a separate governance-conflicted workstream and cannot close this blocker
without an approved V2 evidence boundary.

## Conclusion

The physical and implementation causes are supported for all current ranges,
but the deterministic reviewed ledger and closure signatures are absent.
Therefore V2-B02 remains **OPEN** and contributes no readiness PASS.
