# TIM P0-002 — Validation

## Validation matrix

| Requirement | Result | Evidence |
|---|---|---|
| All 33 gaps reproduced | PASS | P0-001 fixed interval register |
| All gap durations sum to 430 | PASS | Deterministic range sum |
| Local AggTrades absent | PASS | Zero persisted AggTrades in all missing minutes |
| Local candles absent | PASS | 430 expected 1m timestamps absent |
| Public source existence | PASS | 430/430 official public 1m records returned |
| Source check reproducible | PASS | Two identical summary hashes |
| Disconnect correlation | PASS | 33/33 gap ends have a disconnect within 53 seconds |
| One classification per gap | PASS | 33/33 `DOWNLOAD_FAILED` |
| One decision per gap | PASS | 33/33 `REQUIRES_EXTERNAL_SOURCE` |
| Parsing failure claimed | NOT CLAIMED | No raw message exists for rejected parsing evidence |
| Persistence failure claimed | NOT CLAIMED | No parsed input exists for repository-rejection evidence |
| Aggregation failure claimed | NOT CLAIMED | No persisted raw input exists |
| Historical reconstruction | PASS: NONE | No external record imported or persisted |
| Core modification | PASS: NONE | Read-only investigation |

## Deterministic register test

The fixed local join of gap interval, nearest terminal disconnect, category,
and decision was normalized with sorted compact JSON.

Runs 1–10 all produced:

`935205542f4afaa2cca5add0efc3b00d67a1249fe3bd28566904754ca53f7bcf`

Unique hashes: `1`.

## External-source repeat test

Two complete checks of all 33 gap intervals produced:

`d94f9f78eb1a11c3efd19da0c39109610c06061d8d1b5c6e86cc04a92222726a`

Both runs reported:

```text
available source minutes: 430
source-missing minutes:   0
```

No market payload was saved to TIM.

## Traceability rules

For each register row:

1. gap ID and interval originate in P0-001;
2. public-source count equals expected duration;
3. persisted AggTrade count is zero;
4. terminal runtime-log line is recorded;
5. classification follows the same rule;
6. decision follows the same rule.

Classification rule:

```text
IF public source minutes = expected minutes
AND persisted raw minutes = 0
AND terminal WebSocket disconnect exists
THEN category = DOWNLOAD_FAILED
```

Decision rule:

```text
IF local raw evidence is absent
AND public external evidence exists
AND recovery is prohibited
THEN decision = REQUIRES_EXTERNAL_SOURCE
```

## Protected evidence hashes

Hashes recorded after the read-only investigation:

| Artifact | SHA-256 |
|---|---|
| `config/core_manifest.json` | `82bfe439178299adc5bca0ac1de17614a3fd5fe6ed72a110861f88af9d014ca6` |
| `data/research/status/tim_v1_readiness.json` | `7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a` |
| `TIM_COVERAGE_GAP_REGISTER.md` | `0e2379152b9b5cf7def51d7fab7542bd1c787faf3f4a3ef6fe063447c7347a17` |
| `data/operational/events.jsonl` | `0900ed3403e090ad609d0be54d82cd225e36abf5dd5daf4c6efa50f0eddff678` |
| `data/operational/runtime_launchd.err.log` | `2ce5c691479ccebf8c274a98541bd01f22ba369ee005f65227e12721077e4d64` |

Only the four authorized P0-002 Markdown deliverables were created.

## Final cause distribution

```text
DOWNLOAD_FAILED: 33 gaps / 430 minutes / 100.000 %
all other mandatory categories: 0
```

## Recoverability distribution

```text
REQUIRES_EXTERNAL_SOURCE: 33 gaps / 430 minutes
RECOVERABLE:               0
PERMANENTLY_MISSING:       0
UNDER_INVESTIGATION:       0 at pipeline-stage level
```

Within current governance, all 430 minutes remain absent. “Requires external
source” is not authorization to recover them.

## Remaining uncertainty

The failure boundary is proven. The physical origin of the connection failures
is not: available evidence cannot allocate responsibility among host,
network, intermediate path, or remote WebSocket termination.

This uncertainty does not alter the pipeline-stage category.

## Coverage impact

Coverage remains:

```text
663 / 1,093 = 60.659 %
```

No external existence result is counted as persisted TIM evidence.

## Blocker status

**OPEN**

The forensic classification is reproducible and suitable for independent
verification, but the missing data remain absent and the 95% gate remains
failed.

## Status

**P0-002 MISSING INPUT FORENSICS COMPLETE**
