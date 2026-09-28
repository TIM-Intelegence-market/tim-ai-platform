# Mission 06 — Legacy evidence boundary and verified bounded collection

## Scope and authorization

The user authorized one real, finite public market-data collection after tests
and the bounded-live gate passed. The ordinary TIM launchd WebSocket setting
remains `ws://127.0.0.1:1`. No trading, historical catch-up, backfill, repair of
legacy records or rewriting of old reports is part of this implementation.

New collection data lives in its own durable SQLite journal under
`artifacts/verified_collections/<collection_id>/journal.sqlite3`. Production
PostgreSQL is queried read-only for pre/post checks. This separation is deliberate:
the new source starts at the first live ID it observes and does not move the
legacy cursor across its unresolved historical interval.

The public Spot endpoint is
`wss://stream.binance.com:443/ws/btcusdt@aggTrade`, supported by the
[official Binance Spot WebSocket documentation](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md).
It has no authentication, account or order API. There is no reconnect loop.

## Legacy evidence debt

The persistent sidecar is `artifacts/collections/legacy_evidence_status.json`.
It classifies the historical population as `LEGACY_UNVERIFIED_INGRESS`, with
`status=INCOMPLETE` and `remediation_possible=NO`: there is no reliable historical
per-collection receipt journal or equivalent prospective baseline.

The `unproven_ingress_count` is the number of existing raw events without full
collection receipt lineage, not the number of unobserved message occurrences.
Unknown historical message multiplicities remain null. This is different from
`unproven_worker_completion_count`, which identifies old raw events without the
CANDLE_V1 completion evidence. Neither population is relabeled as processed.

Lifetime duplicates and capacity rejections are documented as lifetime context,
never supplied to a current collection equation. Legacy history remains usable
for analysis with `LEGACY_EVIDENCE_INCOMPLETE`. Its warning does not veto an
independent, completely evidenced new collection.

## Prospective contract and receipt boundary

Before connecting, the program persists a contract containing collection ID,
source, symbol, endpoint, source-code hashes, event limit, duration budget,
automatic stop criteria and immutable observe-only settings. The first real
run is capped at 10,000 application-delivered WebSocket frames, or 300 seconds,
whichever ends the session first. The duration budget includes connection setup.

“Received” means a data message returned by this collection's `socket.recv()`.
Ping/control frames and OS/WebSocket-buffered messages never delivered to that
call after closure are not market-event receipts in the collection. The reader
checks the limit before another recv, uses a one-frame receive buffer, closes
the socket explicitly and never silently appends more receipts to the report.

Every delivered message is committed before parsing. SQLite uses WAL,
`synchronous=FULL` and foreign keys. Receipt sequence and a hash chain bind the
exact received public payload bytes to the collection. Even malformed text or
binary data is retained and classified; it is not skipped by the stream parser.

Each receipt stores:

- collection_id, source, symbol, sequence/receipt ID;
- event_id when identifiable, received_at and source_timestamp;
- SHA-256 of exact raw payload, plus the public payload for independent audit;
- validation_result and ACCEPTED / DUPLICATE / REJECTED disposition;
- rejection_reason and a collection-qualified durable_record_id where applicable;
- preceding and current receipt-chain hashes.

An UNKNOWN receipt is persisted if classification is interrupted. UNKNOWN,
application-vs-journal count mismatch or incomplete processing cannot produce
READY. The final independent application counter must equal the journal count.
An unclean session cannot reopen its network connection on resume.

## Accounting and processing evidence

For the current collection only:

```text
received = accepted_unique + duplicates + rejected

accepted_unique = completed + pending + processing + retry + quarantined
```

PENDING is included because it is a real persisted worker state. It must be zero
along with processing, retry and quarantine at healthy closure. Thus:

```text
accepted_unique = completed
```

Duplicates reuse an existing event ID only when its normalized trade hash
matches. Conflicting payloads and out-of-order new IDs are rejected and stop
the session. Invalid and rejected messages remain receipts and count toward
the hard message limit. No lifetime counter or retrospective baseline enters
these equations.

The collection worker is explicitly **COLLECTION_CANDLE_V1**. It uses TIM's
existing `CandleAggregator` for 1m, 5m, 15m and 1h, records raw input and output
hashes per accepted event, and atomically persists candle output and completion.
This proves raw-to-candle processing within this collection. It does not claim
TIMApplication's downstream orderflow/research/observation work was performed.
That is the next intelligence phase, not silently included in this acceptance.

Verification reparses all receipts, checks collection/event membership and
hashes, replays every accepted event through a fresh native aggregator, compares
each output hash and compares the final persisted candle table. It is an actual
recomputation, not merely hashing the same snapshot twice. Reopening a closed
journal for an offline audit cannot duplicate events or reopen the source.

## Gate and stopping conditions

Before source connection, every current gate must pass:

- exactly one stable TIM runtime, same PID/restart counter across observations;
- clean production queue, no PROCESSING/RETRY/QUARANTINED records;
- recalculated valid legacy cursor hash;
- durable new journal active, finite contract and automatic stops active;
- passing tests bound to the exact source hashes;
- recent OBSERVE/zero-action runtime evidence; ordinary legacy stream disabled;
- exclusive collection process lock.

The collector samples runtime health, queue, receipt/processing rates, source
lag, current collection cursor and gaps. A source error/disconnect, idle timeout,
lag above 30 seconds, rejected frame, new intra-collection ID gap, processing
failure or changed runtime safety stops the session. No recovery is attempted.
After source closure, remaining accepted events are drained and checked.

The legacy cursor and the new collection cursor have different named scopes.
No continuity between them is asserted. Known historical gaps remain visible;
any new gap inside the collection prevents its acceptance.

## Acceptance semantics and horizons

`GLOBAL_LEGACY_DATA_QUALITY` may remain WARN while
`CURRENT_COLLECTION_DATA_QUALITY` and
`MISSION_04_CURRENT_COLLECTION_ACCEPTANCE` pass. `VERIFIED_COLLECTION` is only
assigned after complete receipt/processing proof and healthy closure.
`TIM_AUTONOMOUS_COLLECTION_READY` refers to this bounded collection, not a
release of unlimited runtime ingestion, old historical acceptance, or trading.

The old orchestrator SAFE_STOP and old reports remain historical evidence;
they are not overwritten to manufacture the new collection's acceptance.

The report states both:

> Legacy historical ingress evidence is incomplete.

> Current bounded collection has complete ingress and processing evidence.

The second statement is emitted only when the current collection passes.
SHORT remains LIMITED for such a small sample. MID and LONG may use historical
data, but remain LIMITED by `LEGACY_EVIDENCE_INCOMPLETE` and unresolved coverage.
First and last candle windows can be partial; a closed native candle flag alone
does not establish full-window coverage. No horizon or trading strategy is
artificially promoted to READY.

## Tests

82 focused tests passed before the first live run, including all 16 requested
test areas: legacy warning separation; complete journals; hard event and time
stops; exact received/accepted/duplicate/rejected/completed accounting;
collection isolation; idempotent closed resume; unknown-accounting SAFE_STOP;
zero trading/disabled live trading; and reproducible replay/result hashes.
Additional checks detect byte/candle tampering, missing completion evidence,
receipt-count mismatch, invalid binary frames and intra-collection gaps.
Tests use temporary journals and mocked transport, not production PostgreSQL.

The persisted test proof contains the passing count and SHA-256 of the exact
collector, runner and native aggregator source. The live entrypoint refuses
stale proofs. The checked source is stored again in the collection contract.

## Artifact layout

Each collection folder contains its journal, prestart gate, immutable contract
(inside the journal and result), legacy evidence sidecar, test proof, telemetry,
production pre/post snapshots, postflight safety evidence, result JSON, management
and technical reports, and a file-hash manifest. `RESULT_HASH` covers the
deterministic result fields; timing telemetry remains a separate artifact.

## Executed result — 06 September 2026

Collection **verified-btcusdt-20260906T115023Z** ran once, from 2026-09-06T11:50:23.838599+00:00 to 2026-09-06T11:55:23.801867+00:00 UTC. Stop: **DURATION**; source connection closed; no reconnect.

Received / accepted unique / completed: **1,975 / 1,975 / 1,975**. Duplicates, rejected, unknown, PENDING, PROCESSING, RETRY and QUARANTINED: **0**.

New event IDs: **4056354541–4056356515**, with no intra-collection gap. COUNTS_ACCOUNTED, ALL_UNIQUE_EVENTS_PROCESSED, DETERMINISM and current Mission-04 acceptance: **PASS**.

Maximum measured source lag: **0.596 s**; average input/processing rate: **6.475/6.475 events/s**.

Receipt admission stopped at the 300-second deadline. The subsequent WebSocket
close/teardown took about five seconds; total measured lifecycle was 305.007
seconds. No additional receipts were admitted during teardown. The reported
average rates use this whole lifecycle as their denominator.

An independent read-only reopen verified SQLite integrity, every manifested file, exact result-hash reproduction, receipt lineage, replayed candle outputs and unchanged legacy artifacts/core data. Four complete interior one-minute windows were observed (11:51–11:55 UTC); the first and last windows remain partial. SHORT/MID/LONG therefore remain LIMITED.

Result hash: `aabe071ae480a733637c44267cc4337f9bd372084ebb06522d59ae137b7d2b17`.

Primary evidence: `../artifacts/verified_collections/verified-btcusdt-20260906T115023Z/collection_result.json`. Independent proof: `../artifacts/verified_collections/verified-btcusdt-20260906T115023Z-independent-verification.json`.

Legacy ingress lineage is unproven for 7,572,705 existing raw events; this is distinct from the 6,222,112 old events without durable worker-completion evidence. Unknown historical message occurrences remain unknown. No old row or old SAFE_STOP record was rewritten.

**TIM_AUTONOMOUS_COLLECTION_READY = YES for this verified bounded collection.** Ordinary live ingestion and live trading remain disabled, trading actions = 0. Next permissible strategic work: SHORT / MID / LONG trading intelligence using the explicitly verified collection evidence; no real trade.
