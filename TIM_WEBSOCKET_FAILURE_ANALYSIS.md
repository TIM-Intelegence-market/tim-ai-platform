# TIM P0-003 — WebSocket Failure Analysis

## Reader implementation

TIM uses `websockets 15.0.1` under Python `3.14.6`.

Connection parameters:

```text
ping_interval = 20 seconds
ping_timeout  = 20 seconds
close_timeout = 5 seconds
max_queue     = 2048
```

The reader:

1. opens one raw Binance `btcusdt@aggTrade` stream;
2. awaits frames in an async loop;
3. parses each frame;
4. awaits the handler, including database persistence;
5. reconnects after an exception with exponential backoff plus random jitter,
   capped near 30 seconds;
6. does not request missed trade IDs or historical intervals after reconnect.

## Failure-pattern statistics

| Metric | Result |
|---|---:|
| Gap groups | 33 |
| Terminal disconnects correlated | 33/33 |
| Maximum gap-end/disconnect difference | 53 seconds |
| `no close frame received or sent` | 28 |
| keepalive ping timeout | 5 |
| Fatal runtime errors in interval | 0 |
| Memory/resource errors in interval | 0 |

The approximately 15–18 minute repetition is not a Binance 24-hour
disconnect. It follows macOS Maintenance Sleep / DarkWake cadence.

## Host-sleep correlation

macOS records 33 completed sleep intervals overlapping the 33 gaps:

| Metric | Result |
|---|---:|
| Total gap seconds | 25,800 |
| Sleep-overlap seconds | 25,673 |
| Aggregate sleep overlap | 99.508% |
| Lowest individual overlap | 96.548% |
| Highest individual overlap | 100.000% |

Normalized overlap-analysis SHA-256:

`626139e92c9740ddbdf1fc9d63abe8c0603303f9f1cb5968f8fa700346060511`

The analysis produced this same hash in 10/10 runs.

## Heartbeat behavior

Binance documents that its server sends ping frames and requires timely pong
responses. The Python client also has its own 20-second ping interval and
20-second timeout.

During deep idle sleep:

- the Python event loop does not continuously execute;
- application ping/pong timers cannot run normally;
- application frames cannot be consumed;
- TCP keepalive configuration does not make the Python handler execute;
- a stale connection is detected only when the host receives a maintenance
  wake opportunity.

This explains why the log records disconnects at DarkWake boundaries rather
than at the beginning of the missing minute range.

## Reconnect behavior

After detection, the implementation reconnects in approximately 2–3 seconds
on the first retry. During a short DarkWake, the connection can receive and
persist limited current traffic. macOS then returns to maintenance sleep,
causing another gap.

The reconnect mechanism is forward-only. It does not:

- compare aggregate trade IDs across connections;
- record the first/last exchange ID per connection;
- request missing IDs from a historical endpoint;
- delay scientific completeness claims until continuity is verified.

These are observations, not requested fixes.

## Backpressure and queue analysis

The client queue is bounded at 2,048 frames and the handler is awaited
serially. This design can create backpressure in principle. However:

- no queue-overflow exception is logged;
- no handler/persistence exception is logged for the gap boundaries;
- the gaps align with host sleep at 99.508%;
- the terminal errors are connection-close/ping errors.

Backpressure is therefore not classified as the cause of these incidents.

## Exception handling

Malformed individual messages are logged and skipped. Outer connection
exceptions trigger retry. No malformed-message sequence aligns with the
missing ranges. The observed outer exceptions are transport-heartbeat
failures.

## Official-rule comparison

| Binance rule | Observed relevance |
|---|---|
| Connection valid for 24 hours | Does not match short repeated gaps |
| Server ping / timely pong required | Host sleep prevents reliable timely processing |
| Reconnect expected after disconnect | TIM reconnects |
| Connection/message limits | No limit violation evidence |
| Public market-data endpoint available | Source availability verified separately |

## Causal conclusion

```text
Primary category: LOCAL_HOST
Trigger: macOS idle/maintenance sleep
Failure manifestation: WebSocket heartbeat/connection loss
Data consequence: live-only messages missed before parsing
Recovery consequence: forward reconnect cannot recover history
```

## Open technical questions

These questions cannot be answered from retained evidence:

- whether frames arrived at the network interface during DarkWake;
- whether the local router or ISP also experienced disruption;
- exact TCP state during each sleep interval;
- whether remote endpoint closure or local timeout was first on the wire.

They do not change the primary host-sleep conclusion.

## Status

**READY_FOR_VERIFICATION**
