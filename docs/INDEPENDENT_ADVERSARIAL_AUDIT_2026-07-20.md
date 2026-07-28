# TIM Independent Adversarial Audit — 2026-07-20

## Verdict

**ACCEPTANCE FAILED**

This audit made no code changes. Test-only database mutations were either executed inside rolled-back transactions or explicitly deleted. Runtime interruptions were logged as controlled audit events. The final state contains one TIM runtime, one validator, and an HTTP-200 dashboard.

## Reproducible failures

### AUD-001 — Persisted candle gaps are reported as gap-free

- **Priority:** P0
- **Cause:** `scripts/acceptance_check.py:25` checks only BTCUSDT 1m data from the latest hour and only gaps greater than five minutes. It does not test exact timeframe cadence, older data, or the configured 5m/15m/1h streams.
- **Evidence:** An ordered SQL `lag(open_time)` audit found eight nonconforming intervals: four 1m gaps (2m, 2m, 4m, 2m), two 5m gaps (10m each), and two 15m gaps (30m each). At 2026-07-20T17:27:43Z the official check nevertheless returned `candle_sequence_gap_free=true` and overall health `GREEN`.
- **Reproduction:** For every configured timeframe, order BTCUSDT candles by `open_time`, compute `open_time - lag(open_time)`, and compare it with the timeframe's exact duration. Then run `.venv/bin/python scripts/acceptance_check.py`.
- **Affected files:** `scripts/acceptance_check.py`, `src/acceptance/monitor.py`
- **Impact:** The 72h acceptance process can certify a run containing real data loss.
- **Recommended correction:** Audit the entire persisted acceptance interval for exact cadence per configured timeframe and fail on every missing bucket unless a separately persisted, authorized gap classification exists.

### AUD-002 — Governance-invalid records are accepted by PostgreSQL

- **Priority:** P0
- **Cause:** The schema has no allowlist/check constraints for timeframes, provenance, kinds, rule IDs or rule versions; it permits empty or arbitrary hashes and has no future-time guard.
- **Evidence:** In a transaction, PostgreSQL accepted: (1) an observation using timeframe `99x`, provenance `UNKNOWN_PROVENANCE`, rule version `999.999.999`, and hash `MANIPULATED_HASH`; and (2) a candle dated 30 days in the future using timeframe `99x`. The transaction was rolled back and both cleanup counts were zero.
- **Reproduction:** Insert the values above into `observations` and `candles` inside a transaction, query their presence, then roll back.
- **Affected files:** `src/database/schema.sql:32-75`, `src/database/repository.py`
- **Impact:** Invalid or forged records can enter the canonical store and later be treated as evidence.
- **Recommended correction:** Enforce schema-level allowlists, nonempty cryptographic hashes, version registries, timestamp bounds at ingestion, and a quarantine path for rejected rows.

### AUD-003 — One observation ID can be stored twice

- **Priority:** P1
- **Cause:** The observation primary key is `(observation_id, observed_at)`, not `observation_id` alone.
- **Evidence:** Two rows with the same UUID and different timestamps were accepted in one rolled-back transaction; the query count was two.
- **Reproduction:** Insert an observation UUID at `t0`, insert the same UUID at `t0 + 30 days`, and count rows by `observation_id`.
- **Affected files:** `src/database/schema.sql:48`, `src/database/repository.py:34-37`
- **Impact:** ID uniqueness and deduplication can be violated even though the acceptance query currently compares total rows with distinct IDs.
- **Recommended correction:** Make `observation_id` uniquely constrained independently of the Timescale partition design, or use a separate identity table with referential integrity.

### AUD-004 — Observation and case persistence is not atomic

- **Priority:** P1
- **Cause:** `main.py:52-59` saves an observation and its research case in separate database acquisitions/transactions.
- **Evidence:** A TEST_ONLY observation was saved, a failure was injected before case persistence, and an orphan observation was observable (`orphan_after_mid_pipeline_failure=1`). It was then deleted (`cleanup_remaining=0`).
- **Reproduction:** Call `save_observation`, raise an exception before `upsert_research_case`, and query for observations not referenced by any case.
- **Affected files:** `main.py:52-59`, `src/database/repository.py`, `src/database/connection.py`
- **Impact:** Process failure can leave partial state that a restart interprets as complete input.
- **Recommended correction:** Persist the observation, case, trigger linkage, and related state in one explicit transaction with idempotent retry semantics.

### AUD-005 — Dashboard Research Cases diverge from PostgreSQL after restart

- **Priority:** P1
- **Cause:** Restart recovery reconstructs cases from observations (`main.py:88-95`) instead of loading persisted cases. Trigger documentation, status, outcomes, and other persisted case state are therefore not restored.
- **Evidence:** After controlled restarts, 11 of 18 dashboard cases had default documentation while PostgreSQL stored trigger/module/artifact documentation for the same case IDs.
- **Reproduction:** Compare `/api/state.research_cases` by `case_id` with `research_cases` immediately after restarting TIM.
- **Affected files:** `main.py:88-95`, `src/dashboard/app.py`, `src/database/repository.py`
- **Impact:** Operators see state that is not the canonical database state; closed cases or outcomes would also be reconstructed incorrectly.
- **Recommended correction:** Add a read path for persisted cases and restore them verbatim before accepting new stream events.

### AUD-006 — Manipulated report content/hash passes Research Health

- **Priority:** P1
- **Cause:** `src/operational/research_health.py:48-54` checks only file readability, metadata key presence, a provenance suffix, and OBSERVE mode. It does not recompute `input_hash`, hash report content, or validate provenance against an allowlist.
- **Evidence:** A temporary report containing `MANIPULATED CONTENT`, metadata provenance `FORGED_DETERMINISTIC`, and declared hash `DECLARED_BUT_NOT_RECOMPUTED` passed `reports_readable`, `metadata_complete`, and `report_provenance_deterministic`.
- **Reproduction:** Create a report/metadata pair with all required keys but unrelated content and arbitrary values ending in `DETERMINISTIC`; run `ResearchHealthChecker.check()`.
- **Affected files:** `src/operational/research_health.py:48-60`
- **Impact:** Forged or modified research artifacts can be reported healthy.
- **Recommended correction:** Use an explicit provenance allowlist and recompute/compare canonical input and artifact hashes.

### AUD-007 — Dashboard headline counts are not database counts

- **Priority:** P2
- **Cause:** The dashboard exposes capped lists and displays their lengths as counts without also exposing canonical totals.
- **Evidence:** At audit time PostgreSQL contained 274 candles and 180 observations, while `/api/state` exposed and displayed 50 candles and 50 observations. Research Cases exposed 18 of 18.
- **Reproduction:** Compare `count(*)` in PostgreSQL with the lengths of `/api/state.candles` and `/api/state.observations`.
- **Affected files:** `main.py:85-95`, `src/dashboard/app.py`
- **Impact:** The dashboard count labels do not represent the canonical totals requested for operational comparison.
- **Recommended correction:** Label capped lists as recent items and expose separate canonical total counts from the database.

## Controls that did not fail in this audit

- Three isolated replays produced the same hash `9d7c7903bf1380f710a5d82ae238ff4e553d60cf07c40f827c175beadac6652c`, 96 observations, 14 cases, identical observation IDs, and identical case payloads.
- Three immediate dashboard domain snapshots (excluding the intentionally changing response timestamp) were identical.
- A controlled restart snapshot preserved all 272 candle keys, 178 observation IDs, and 18 case IDs with no additions during the four-second comparison window.
- After restart, exactly one runtime was active and an established TCP connection to Binance port 9443 was present.
- Transaction rollback removed all adversarial database rows.
- PostgreSQL reported zero deadlocks at audit time.
- No `TRADE_EXECUTED` event was found by the active validator.

These passing controls do not offset any failure above.

## Performance measurements

- Dashboard `/api/state`, 30 requests: min 1.099 ms, mean 2.456 ms, p95 4.251 ms, max 15.760 ms.
- Database size: 8,689,343 bytes.
- Stream delay at 2026-07-20T17:27:11Z: 11.096 seconds from the latest persisted 1m close.
- Operational metrics: 133 samples at final collection; RSS min 20.672 MB, max 69.719 MB, latest 24.438 MB in the earlier 131-sample snapshot; CPU min 0%, max 39.5%, mean 1.716%.
- Observed RSS linear slope over the available sample sequence: +0.033669 MB/sample. This is a measurement only, not proof of a memory leak.
- Current artifact sizes at measurement: events 110,466 bytes/204 lines; metrics 32,154 bytes/133 lines; Module A cache 72,809 bytes/85 lines; trigger events 21,108 bytes/78 lines.

## Long-run limitation

Only 2.244 real hours of the persisted 72h window had elapsed when the final official check was run. Therefore memory leaks, queue growth, event drift, thread leaks, and latency evolution over 72 hours cannot yet be accepted or rejected from the available evidence. The official check correctly reported `deadline_reached=false`, but incorrectly reported the existing candle sequence as gap-free.

## Test-suite coverage result

The unchanged suite passed **89 tests** while AUD-001 through AUD-007 remained reproducible. Therefore a green unit suite is not evidence that the acceptance properties above hold.

## Final decision

**ACCEPTANCE FAILED**

The decision is caused independently by persisted data gaps, governance bypasses, duplicate-ID acceptance, non-atomic persistence, dashboard/database divergence, and ineffective artifact hash validation.
