# TIM V2 Pre-Remediation Baseline

Evidence cut-off: `2026-08-01T15:00:43.767881Z`

Repository: `/Users/tim/Documents/TIM/tim`

Branch at cut-off: `codex/workspace-agent-secure-mcp`
Commit at cut-off: `9d0077af6d6b0af98758edf49c182f4a18914c0d`

This baseline is a read-only checkpoint. It does not approve V2, alter Core
1.0, backfill data, or authorize any trading function.

## Repository state

- Remote: `origin`, `https://github.com/uezeyiraydin-cell/tim-ai-platform.git`.
- The four expected Secure MCP evidence documents were reviewed, tested,
  committed as `9d0077a`, and pushed to the existing MCP branch.
- The tracked working tree was clean immediately after that push.
- No merge, tag, release, or trading change was performed.

## Runtime state

| Component | Evidence | Result |
|---|---|---|
| TIM runtime | launchd `com.tim.runtime`, PID 552 at inspection | RUNNING |
| Dashboard | `127.0.0.1:8765`, `/api/health` HTTP 200 | LOOPBACK / GREEN |
| Public stream | health data age 2 seconds at inspection | GREEN |
| PostgreSQL | `127.0.0.1:5432`, PostgreSQL 18.4 | ACCEPTING CONNECTIONS |
| Ollama service | `127.0.0.1:11434`, four local models | RUNNING, DISABLED BY TIM POLICY |
| TIM mode | API, manifest, schema constraints | OBSERVE-only |
| Queue | direct await, depth 0 | HEALTHY |

No listener was found on `0.0.0.0:8765`. The application contains no
authenticated exchange endpoint, broker, wallet, order, position, or capital
allocation path. The runtime API reports `observe_only=true`; persisted
orderflow records and validations contain only `mode=OBSERVE`.

## Data snapshot

The database was inspected in a read-only, repeatable-read transaction with
snapshot identifier `4598755:4598755:`. The logical manifest is stored in
`artifacts/v2_readiness/baseline_manifest.json`. PostgreSQL occupied about
741 MiB at the later size probe; the live database file was not copied or
hashed while PostgreSQL was writing.

| Relation | Rows | Distinct identity keys | First event (UTC) | Last event (UTC) |
|---|---:|---:|---|---|
| `agg_trades` | 4,008,033 | 4,008,033 | 2026-07-22 20:13:21.782 | 2026-08-01 15:00:43.624 |
| `candles` | 14,628 | 14,628 | 2026-07-20 13:00:00 | 2026-08-01 14:59:00 |
| `observations` | 10,130 | 10,130 | 2026-07-20 13:51:00 | 2026-08-01 15:00:00 |
| `orderflow_observations` | 21,513 | 21,513 | 2026-07-22 21:29:00 | 2026-08-01 15:00:00 |
| `orderflow_validations` | 21,502 | 21,502 | 2026-07-22 21:29:00 | 2026-08-01 14:55:00 |
| `research_cases` | 23,219 | 23,219 | 2026-07-20 13:51:00 | 2026-08-01 15:00:00 |

At this cut-off, 21,474 orderflow validations were complete and 28 were
incomplete. Identity counts matched row counts in every relation above.

## Coverage baseline

The published frozen readiness value remains `663 / 1,093 = 60.659%` for the
fixed interval `2026-07-22T20:14:00Z` through
`2026-07-23T14:27:00Z` (end exclusive).

An independent extension of that same start through the last closed minute at
this baseline cut-off produced:

- expected one-minute intervals: 14,087;
- observed distinct closed one-minute intervals: 9,487;
- missing intervals: 4,600;
- coverage: 67.346%;
- canonical missing ranges: 283;
- largest range: 685 minutes.

This current value is below the 95% gate. It does not replace or rewrite the
frozen historical result. Existing governance also requires a prospectively
approved qualifying window; no such human approval is inferred here.

## Baseline tests

- Secure MCP / Graphify gateway subset: 55 passed, 1 deprecation warning.
- Full suite: 324 passed, 2 setup errors, 145 warnings in 114.89 seconds.
- Both setup errors occurred while `initialize_schema()` attempted to execute
  the production schema against the active 4-million-row database and timed
  out. This is a test-isolation and schema-initialization finding, not a test
  assertion failure. It remains an open technical gate until reproduced in an
  isolated database and remediated.

## Baseline blockers

1. Authoritative continuous coverage is below 95%.
2. Current missing one-minute ranges have not been fully classified.
3. A human-approved prospective qualifying interval is absent.
4. Historical artifact audit and research quality remain `FAIL` at their
   frozen cut-off.
5. Manual scientific review and named independent reviewers are absent.
6. Secure MCP workspace association remains externally blocked by OpenAI.
7. The full suite is not safe or reliable when pointed at the live database.

## Protected evidence hashes

| Artifact | SHA-256 |
|---|---|
| `config/core_manifest.json` | `82bfe439178299adc5bca0ac1de17614a3fd5fe6ed72a110861f88af9d014ca6` |
| `TIM_V2_READINESS_CHECKLIST.md` | `696ad64f88441d65ac5c857ecdc60e73a1d1983bc611b8113a0b97291666f1f5` |
| frozen July snapshot | `81fb9617b01ddd2f9dcf6651a0a433b8a9641052d6152d9c4541344b0aa0ada3` |
| frozen readiness status | `7b682c57521f766c90e18900e490892d0faec2def4e3dbd65343e8380ab2ef6a` |
| operational state | `1d609ae732431b4101e7e37bf75f59d266ba9f5663de110f69325e6cae53a7a6` |
| operational validation report | `1f515a2ca2772efff41c20cc45201584e1f1c9f52c22123f5fdce7abd2b7446e` |
| Graphify graph | `60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513` |

Runtime logs and live research caches remain mutable and are recorded with a
timestamped size/hash in the machine-readable manifest rather than treated as
immutable release evidence.
