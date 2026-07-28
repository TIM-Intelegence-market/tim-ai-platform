# TIM P0-002 — Missing Input Forensics Report

## Executive conclusion

The 430 missing BTCUSDT minutes were not source-empty minutes. A read-only
query of Binance's public Spot 1m endpoint returned a real, non-empty market
record for every one of the 430 minutes. No returned record was imported,
persisted, or used to modify TIM.

Every one of the 33 TIM gap ranges ends within 53 seconds of a timestamped
`Binance public stream disconnected` entry in
`data/operational/runtime_launchd.err.log`:

- 28 terminal events: `no close frame received or sent`
- 5 terminal events: keepalive `ping timeout`

TIM persisted zero AggTrades and zero closed 1m candles for those minutes.
The loss is therefore localized to the live WebSocket transport/reception
boundary, before parsing, validation, persistence, and aggregation.

Under the mandatory classification vocabulary, all 33 gaps are classified
**DOWNLOAD_FAILED**. The word “download” denotes failed live transport here;
TIM had no file-download or batch-import pipeline for these records.

## Scope and non-interference

Frozen interval:

```text
start inclusive: 2026-07-22T20:14:00Z
end exclusive:   2026-07-23T14:27:00Z
expected:        1,093 minutes
persisted:       663 minutes
missing:         430 minutes
coverage:        60.659 %
```

This investigation:

- performed read-only database and filesystem inspection;
- made two read-only public-source existence checks;
- did not retain or import returned market payloads;
- did not reconstruct or backfill any minute;
- did not change Core, database, AggTrades, candles, snapshots, reports,
  manifest, validator, or Hash Contract.

## Architecture finding

The active acquisition path in `main.py` and
`src/data_ingestion/binance_ws.py` is:

```text
Binance Spot WebSocket
→ JSON message reception
→ parse_message
→ on_trade
→ insert_agg_trade
→ CandleAggregator
→ candle persistence
```

There is no historical file download, archive extraction, file validation, or
batch import in this path. Repository file inspection found no AggTrade ZIP,
CSV, or local raw-message archive corresponding to the gaps.

## Stage-by-stage forensic result

| Stage | Result | Evidence |
|---|---|---|
| Source availability | AVAILABLE | Binance returned all 430 public 1m records with positive trade counts |
| Download / live transport | FAILED | 33/33 gaps terminate at a WebSocket disconnect; no local raw input exists |
| Archive extraction | NOT APPLICABLE | Runtime consumes WebSocket JSON, not archives |
| File validation | NOT APPLICABLE | No file ingestion exists for this path |
| Parsing | NOT REACHED | No raw message was locally retained for a missing minute |
| Runtime validation | NOT REACHED | No parsed Trade reached repository validation |
| Persistence | NO INPUT RECEIVED | Zero persisted AggTrades in all 430 minutes |
| Aggregation | NO INPUT RECEIVED | No persisted raw input existed for candle formation |

No evidence demonstrates `FILE_CORRUPTED`, `IMPORT_ABORTED`,
`VALIDATION_REJECTED`, `PIPELINE_FAILURE`, `CONFIGURATION_ERROR`, or
`SOURCE_NOT_AVAILABLE`.

## Transport evidence

Runtime timestamps are local Europe/Berlin time and were normalized to UTC.
For each gap, the closest terminal disconnect is between 1 second before and
53 seconds after the exclusive gap end.

The repeated observable sequence is:

1. the live connection stops delivering persistable market messages;
2. TIM records no AggTrades during the interval;
3. TIM records no closed 1m candle;
4. the WebSocket client logs a disconnect;
5. the client retries after approximately 2–3 seconds;
6. later data resumes, but the client performs no historical recovery.

The logs prove a transport/reception failure. They do not prove whether the
physical cause was the host network, operating system, intermediate network,
remote connection termination, or another transport-layer component.

## External-source evidence

Endpoint used for existence testing:

```text
https://api.binance.com/api/v3/klines
symbol=BTCUSDT
interval=1m
fixed startTime/endTime per gap
```

For each of the 33 ranges:

- HTTP status was 200;
- returned minute count equaled expected minute count;
- every returned minute had a positive trade count;
- source-missing minute count was zero.

Across all gaps:

```text
expected source minutes: 430
available source minutes: 430
source-missing minutes:   0
```

The summary was executed twice and produced the same SHA-256:

`d94f9f78eb1a11c3efd19da0c39109610c06061d8d1b5c6e86cc04a92222726a`

The same-day Binance Vision daily ZIP returned HTTP 404 at investigation time;
the daily archive had not yet been published. This does not contradict the
REST evidence and is not classified as source unavailability.

## Definitive cause distribution

| Classification | Gaps | Minutes | Percentage |
|---|---:|---:|---:|
| DOWNLOAD_FAILED | 33 | 430 | 100.000 % |
| SOURCE_NOT_AVAILABLE | 0 | 0 | 0 % |
| FILE_CORRUPTED | 0 | 0 | 0 % |
| IMPORT_ABORTED | 0 | 0 | 0 % |
| VALIDATION_REJECTED | 0 | 0 | 0 % |
| PIPELINE_FAILURE | 0 | 0 | 0 % |
| CONFIGURATION_ERROR | 0 | 0 | 0 % |
| UNKNOWN | 0 | 0 | 0 % |

P0-001's 15-minute `UNKNOWN` range `CG-023` is resolved at the stage level:
the same public-source and terminal-disconnect evidence exists for it.
Its deeper physical network cause remains unknown, but the mandated
pipeline-stage category is unambiguously `DOWNLOAD_FAILED`.

## Decision distribution

All 33 gaps are classified `REQUIRES_EXTERNAL_SOURCE`.

Reason:

- no local raw input exists;
- Binance currently demonstrates source records for every missing minute;
- recovering the historical records would require an external-source fetch;
- such recovery is explicitly prohibited by this investigation and by the
  current frozen-Core governance.

No gap is marked `RECOVERABLE` because that label could imply recovery within
the permitted local evidence set. No gap is marked `PERMANENTLY_MISSING`
because public source evidence exists. No gap remains `UNDER_INVESTIGATION`
at the pipeline-stage level.

## Risk assessment

| Dimension | Assessment |
|---|---|
| Scientific | Critical: uninterrupted-window claims fail; affected intervals cannot support complete orderflow analysis |
| Technical | High: live-only ingestion loses records during transport stalls and does not recover them |
| Governance | High: external recovery is possible in principle but prohibited for frozen historical evidence |
| Readiness | Blocking: 60.659% remains below 95% |

Scientific results computed only from persisted data are not shown to be
corrupted. They are incomplete across the gaps.

## Impact on 95% coverage

This investigation changes no numerator. Coverage remains `60.659 %`.
External availability does not count as TIM persistence and cannot raise the
readiness value.

## Recommended next steps

1. Preserve all 33 historical gaps unchanged.
2. Treat them as `REQUIRES_EXTERNAL_SOURCE` in governance records.
3. For a prospective observation window, capture timestamped connection-state
   and message-sequence evidence with enough granularity to distinguish
   transport stall from process loss.
4. Pre-register the next coverage interval before data collection.
5. Independently verify that no new transport gap occurred before moving the
   blocker to `READY_FOR_VERIFICATION`.
6. Any future backfill proposal must be a separately approved, versioned
   governance decision and must not modify Core 1.0 evidence.

## Status

**OPEN**

The forensic stage is complete, but historical gaps remain absent from TIM and
the coverage gate remains failed.

**P0-002 MISSING INPUT FORENSICS COMPLETE**
