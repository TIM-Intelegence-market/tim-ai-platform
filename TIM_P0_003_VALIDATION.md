# TIM P0-003 — Validation

## Test matrix

| Test | Result | Evidence |
|---|---|---|
| All 33 gaps analyzed | PASS | Fixed P0-001 gap register |
| Sleep evidence available | PASS | macOS `pmset` historical log |
| Sleep interval count | PASS | 33 completed intervals |
| Every gap overlaps sleep | PASS | Minimum overlap 96.548% |
| Aggregate overlap | PASS | 25,673 / 25,800 seconds = 99.508% |
| Disconnect correlation | PASS | 33/33 within 53 seconds of gap end |
| Source availability | PASS | 430/430 public source minutes |
| Process crash in interval | NOT FOUND | Zero fatal/error-memory runtime records |
| Resource exhaustion | NOT FOUND | Zero retained memory-pressure/jetsam/OOM records |
| Binance 24-hour rule match | FAILS AS EXPLANATION | Connections fail on host sleep cadence |
| One category per gap | PASS | 33/33 `LOCAL_HOST` |
| Deterministic analysis | PASS | 10/10 normalized hashes identical |
| Data reconstruction | NONE | No historical market record written |
| Core modification | NONE | Read-only investigation |

## Deterministic classification

Classification rule:

```text
IF a documented local-host sleep interval overlaps the gap
AND the public source has market activity
AND the terminal WebSocket failure aligns with wake/gap end
THEN cause = LOCAL_HOST
```

All 33 gaps satisfy the rule.

Normalized result hash for runs 1–10:

`626139e92c9740ddbdf1fc9d63abe8c0603303f9f1cb5968f8fa700346060511`

Unique hashes: `1`.

## Quantitative verification

```text
gap duration total:       25,800 seconds
sleep overlap total:      25,673 seconds
non-sleep boundary time:     127 seconds
sleep overlap:               99.508 %
```

The 127 boundary seconds do not constitute complete persisted 1m intervals
and are distributed around second-level sleep/wake transitions.

## Category distribution

| Category | Gaps | Minutes |
|---|---:|---:|
| LOCAL_HOST | 33 | 430 |
| LOCAL_NETWORK | 0 | 0 |
| INTERNET_PATH | 0 | 0 |
| REMOTE_ENDPOINT | 0 | 0 |
| SOFTWARE_FAILURE | 0 | 0 |
| RESOURCE_EXHAUSTION | 0 | 0 |
| CONFIGURATION | 0 | 0 |
| UNKNOWN | 0 | 0 |

The current power configuration is a contributing condition, but each
incident is assigned exactly once to the observed physical category
`LOCAL_HOST`.

## Protected artifact hashes

| Artifact | SHA-256 |
|---|---|
| `config/core_manifest.json` | `82bfe439178299adc5bca0ac1de17614a3fd5fe6ed72a110861f88af9d014ca6` |
| `data/research/status/tim_v1_readiness.json` | `7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a` |
| `TIM_GAP_CLASSIFICATION_REGISTER.md` | `48805f92ca161a6007a4912494c9ac602f67303441823af9bfda864489a10e6f` |
| `src/data_ingestion/binance_ws.py` | `d39ddbec81ae23e093b41bb93e3a338fb8997051a0b87fe2a5b2d6ed243baf11` |
| `main.py` | `a14566d3df9b641aedccd6097027ab4d7e1323e26c572d5e946f3f553336b79c` |

Operational logs are append-only live artifacts; their whole-file hashes may
continue changing after this investigation. Evidence line references and
normalized analysis hashes provide the reproducible cut.

## Evidence limitations

- No packet capture exists.
- No historical router/ISP telemetry exists.
- Current proxy/VPN state cannot prove historical state.
- No per-frame receive log exists.
- No historical event-loop-lag metric exists.

None of these limitations negates the direct sleep overlap.

## Risks

- Future runs on a sleep-capable workstation can reproduce the same loss.
- A process-liveness check can remain true while the event loop is suspended.
- TCP keepalive does not guarantee application processing during deep sleep.
- Forward-only reconnect preserves a permanent historical gap.

## Requirements outcome

Future V2 planning must include:

- continuous-execution host policy;
- power-state telemetry;
- last-message watchdog;
- exchange-ID continuity detection;
- multi-layer health and independent observation;
- network and backpressure telemetry;
- explicit reconnect and recovery provenance;
- prospective coverage verification.

No requirement has been implemented by this investigation.

## Blocker status

**READY_FOR_VERIFICATION**

The cause is deterministically reproduced from retained evidence and is ready
for independent review. The blocker is not automatically closed.

## Status

**P0-003 TRANSPORT RELIABILITY INVESTIGATION COMPLETE**
