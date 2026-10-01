# Changelog

## Unreleased — TIM on a Debian server (systemd)

- Added `ops/systemd/`: systemd counterparts of the launchd runtime, watchdog,
  candle finalizer, rolling liveness, maintenance and coverage worker, a polkit
  rule that lets the `tim` user control only `tim-runtime.service`, and
  `tim.env.example` (file secret provider, no secret values). Install steps in
  `ops/systemd/README.md`.
- `scripts/timctl` uses `systemctl` and `ss` on Linux and keeps launchd and
  netstat on macOS. All start/stop gates are unchanged; `status` and
  `safe-stop` report `service_manager`.

## Unreleased — Broncx Discord feed as external guidance

- Added `src/knowledge/broncx_feed.py` (post store and guidance parser) and
  `src/sources/broncx_discord.py` (read-only poller for a forward channel in the
  owner's own Discord server) with `scripts/broncx_discord_bot.py` and a
  launchd agent.
- The orderflow scenario pipeline accepts `external_posts`; the guidance is
  written to the audit (`external_context`) and the report
  (`BRONCX-LEITFADEN`).
- Broncx's newest active direction weights the analysis: scenarios in his
  direction +0.08 score, opposing ones -0.08; his LEVEL prices within 1 % of
  price become scenarios (`X-<bias>-<level>`, at most two) with TIM's own
  mandatory confirmations; stop and invalidation prices never do.
  It never confirms a scenario or creates a trade plan by itself; stale,
  invalidated, mixed or not-yet-known posts have no effect (tested).
- `ofsc --broncx-feed DIR [--broncx-max-age-hours H]`.
- Chart images: a position-tool direction also counts when his text names no
  direction ("Took this") and no earlier view of his is still open (the same
  now holds for image-only posts); never against
  his text, a withdrawn direction ("closed my short"), trade management
  ("stopped out", "tp1 hit") or a renewal ("still valid"); chart levels are marked "aus Bild, geschätzt" in the
  report; `fetch-images` retries a failed image of a post; daily charts keep
  their timeframe (`1d`).

## Unreleased — repository foundation

- Prepared contribution, security, conduct, Git governance, AI access, release,
  and Graphify indexing policies.
- Added a platform-neutral knowledge-graph metadata schema and index policy.
- No runtime, research, trading, historical-data, or accepted-platform behavior
  changed.
- GitHub publication, branch protection, tags, and releases remain pending.

## UI V3 — Operations & Research Control Center redesign

- Added `src/dashboard/design_system.py`: centralized semantic severity system
  (ok / info / warn / degraded / fail / blocked / unknown / disabled) with
  reusable presentation primitives (status chips, state banner, attention list,
  pipeline, status rows, metric strips, coverage rows, gate rows, horizons).
- Redesigned the global shell: grouped navigation (OPERATIONS / RESEARCH /
  READINESS / INTELLIGENCE / SYSTEM), a persistent global status matrix
  (SYSTEM, LIVE DATA, QUEUE, DATA QUALITY, RESEARCH, TRADING LOCKED) that is
  server-rendered and refreshed by the existing 5-second poll, and a cleaner
  safety strip.
- Rebuilt all ten operations pages on the new primitives; the Overview now
  answers in order: primary system state, active problems, pipeline health,
  research readiness (SHORT/MID/LONG + V2 gates). Missing evidence renders as
  UNAVAILABLE and is never shown as a value.
- Renamed pages/routes only in label: Gap Explorer → Incidents & Gaps,
  Qualification Campaign → Qualification, Research & Independent Cases →
  Independent Cases (URLs unchanged).
- Additive operations-contract keys: `live` (pass-through of live operational
  states) and `audit.incidents` (bounded, newest-first incident list). Existing
  contract semantics are unchanged; read-only/trading-locked guard keys are
  untouched.
- No trading, execution, ingestion, database, or research-artifact behavior
  was modified. The UI remains read-only OBSERVE evidence.

## TIM Core 1.0 Freeze

- Declared the implemented Core component set frozen in OBSERVE-only mode.
- Added a machine-readable version and change-policy manifest.
- Added a deterministic monthly research snapshot protocol with explicit data
  coverage and version-isolation requirements.
- No runtime, market-rule, threshold, outcome, or validation behaviour changed.

## Research Insights Engine (external to Core)

- Added deterministic, retrospective statistics over copied persisted
  orderflow research data.
- Added strict version partitions, sample labels, TEST_ONLY exclusions, quality
  warnings, stable hashes, and JSON/CSV/Markdown exports.
- Added the read-only `/insights` dashboard page. The engine remains
  `NOT_YET_ELIGIBLE` while Core 1.0 evidence gates are unmet.

## Research Operations (external to Core)

- Added a read-only Research Audit Engine for artifact, hash, provenance,
  version, schema, timestamp, and documentation checks.
- Added deterministic Research Quality reporting without repair or inference.
- Added reproducible monthly snapshots with explicit `IN_PROGRESS` status for
  active months, persisted database counts, 1-minute candle coverage, replay
  status, known limitations, and stable hashes.

## 2026-07-19 — Intelligence V1 specifications

### Added

- Versioned deterministic Observation Engine with stable IDs, provenance, rule versions and input hashes.
- Historical Market Memory with transparent, future-safe similarity search.
- Reproducible Research Cases with evidence, missing evidence, outcomes and rule versions.
- Local Human Assistant Dashboard V1 with HTML and JSON state endpoints.
- Authorized-record News Intelligence with deterministic historical linking.
- GoatHub Knowledge search with explicit authorization, line citations and content hashes.
- Descriptive Long-Term Intelligence for market, dominance, sector and macro context.
- OBSERVE-only Short-Term Assistant that exposes evidence, conflicts and missing context.
- Disabled-by-default, TEST_ONLY Paper Automation journal with nonzero costs and delayed evaluation.
- Vision 2030 governance and evolution roadmap.

### Safety

- No private exchange endpoints, credentials, account access, wallet access, real orders or execution.
- Models remain explanation-only and cannot create observations, rules or actions.
- News and knowledge inputs require provenance; knowledge requires explicit authorization.
- Paper evaluation cannot be instantiated as non-test operation.

### Passive continuation

- Added manually invoked, read-only local connectors for News and GoatHub knowledge.
- Added explicit host/path allowlists, file-size bounds, atomic manifests, content hashes, snapshots and deduplication.
- Retention remains dry-run only; no source or evidence deletion is performed.
# 2026-07-20 — Operational validation and data quality

- Added restart-safe 72-hour OBSERVE validator with structured JSONL logging.
- Added CPU, RSS, disk, database, dashboard, and required-file health metrics.
- Added deterministic quality validation with duplicate, timestamp, provenance,
  and observation metadata checks.
- Added explicit completeness, freshness, integrity, candle-gap, report schema,
  and reproducible CLI validation.
- Added permanent versioned research benchmarks and comparison reports.
- Added an idempotent local PostgreSQL 18 bootstrap with explicit TimescaleDB
  verification and no stored administrator credential.
