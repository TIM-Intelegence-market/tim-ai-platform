# TIM P0-002 — Data Source Forensics

## Question examined

Did BTCUSDT source data not exist, or did TIM fail to receive/persist existing
source data?

## TIM source configuration

Configured source:

```text
Binance Spot public WebSocket
wss://stream.binance.com:9443/ws/btcusdt@aggTrade
```

The stream has no credentials and no private endpoint. Incoming JSON
`aggTrade` messages are parsed in memory and passed directly to database
persistence. TIM does not create a raw AggTrade file before parsing.

## Local artifact search

The project contains:

- persisted `agg_trades` database rows;
- runtime and operational logs;
- no gap-specific raw AggTrade files;
- no downloaded Binance daily ZIP for 2026-07-23;
- no extraction manifest;
- no batch-import completion marker for the affected ranges.

Consequently, file integrity, archive extraction, and interrupted file import
cannot be evaluated because those stages did not exist in this acquisition
path.

## Public-source existence test

The official public Binance Spot kline endpoint was queried only to establish
existence and minute continuity:

```text
GET https://api.binance.com/api/v3/klines
symbol=BTCUSDT
interval=1m
startTime=<gap start>
endTime=<gap end minus 1 ms>
```

No response payload was written into TIM or retained as a project artifact.
Only counts, HTTP status, and a normalized summary hash were observed.

Results:

| Check | Result |
|---|---|
| Gap requests | 33/33 HTTP 200 |
| Expected source minutes | 430 |
| Returned source minutes | 430 |
| Source-missing minutes | 0 |
| Minimum per-minute trade count | positive in every minute |
| Repeat summary hash | identical |

Summary SHA-256 on both executions:

`d94f9f78eb1a11c3efd19da0c39109610c06061d8d1b5c6e86cc04a92222726a`

This establishes that the market source contained activity for every gap
minute. It does not establish that the WebSocket endpoint delivered every
individual message to TIM at the time.

## Runtime transport evidence

The local runtime log includes a terminal WebSocket disconnect at every gap
end:

- 33/33 correlated;
- maximum difference from exclusive gap end: 53 seconds;
- 28 `no close frame received or sent`;
- 5 keepalive `ping timeout`.

The reconnect loop uses an approximately 2–3 second backoff after a detected
disconnect. It does not request missing historical IDs or time ranges after
reconnection.

Observed implication:

```text
public source record exists
AND local raw/persisted trade does not exist
AND connection terminates at gap boundary
THEREFORE failure boundary = live transport/reception
```

This does not identify the physical owner of the transport fault. No
timestamped evidence distinguishes:

- local network interruption;
- host sleep or network suspension;
- intermediate path failure;
- remote WebSocket termination;
- another connection-layer condition.

It does distinguish the fault from `SOURCE_NOT_AVAILABLE`.

## Integrity status

The same-day daily Binance Vision archive URL returned HTTP 404 during the
investigation. Same-day daily archives need not yet be published. The 404 is
not used as gap evidence because the public REST source independently
confirmed all 430 minutes.

No checksum can be evaluated for a daily archive that is not present. No
download or extraction was attempted.

## Forensic decision

| Question | Decision |
|---|---|
| Did public market data exist? | YES, for 430/430 minutes |
| Did TIM persist it? | NO |
| Did a local raw file exist? | NO |
| Was parsing rejection proven? | NO |
| Was database rejection proven? | NO |
| Was candle aggregation loss proven? | NO |
| Was live transport failure proven? | YES, at all 33 gap boundaries |
| Is the physical network owner proven? | NO |

## Governance consequence

The records are externally available in principle but absent from the frozen
TIM dataset. They must remain absent unless a future, explicit governance
decision authorizes a separately versioned external-source recovery. Such a
decision is outside this investigation.

## Status

**OPEN**

Source availability is verified; historical TIM completeness is not restored.
