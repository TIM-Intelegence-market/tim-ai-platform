# Graph Report - .  (2026-07-29)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1573 nodes · 3355 edges · 84 communities (76 shown, 8 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 119 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `925ad91e`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 72
- Community 73
- Community 74
- Community 75
- Community 77
- Community 78
- Community 79

## God Nodes (most connected - your core abstractions)
1. `Trade` - 60 edges
2. `Candle` - 59 edges
3. `Observation` - 48 edges
4. `render()` - 37 edges
5. `DashboardState` - 35 edges
6. `MarketRepository` - 35 edges
7. `scan_project()` - 35 edges
8. `AcceptanceMonitor` - 32 edges
9. `ObservationKind` - 31 edges
10. `KnowledgeRegistry` - 24 edges

## Surprising Connections (you probably didn't know these)
- `PersistedRepository` --uses--> `DashboardState`  [INFERRED]
  tests/test_restart_persisted_cases.py → src/dashboard/app.py
- `_Response` --uses--> `ObservationKind`  [INFERRED]
  tests/test_ollama_policy.py → src/models/market_data.py
- `_Response` --uses--> `Observation`  [INFERRED]
  tests/test_ollama_policy.py → src/models/market_data.py
- `test_doctor_checks_protection()` --calls--> `doctor()`  [EXTRACTED]
  tests/tim_manager/test_acceptance.py → src/tim_manager/cli.py
- `test_grounded_module_question_cites_evidence()` --calls--> `answer()`  [EXTRACTED]
  tests/tim_manager/test_acceptance.py → src/tim_manager/query.py

## Import Cycles
- None detected.

## Communities (84 total, 8 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (56): bucket_start(), _BuildingCandle, CandleAggregator, datetime, timeframe_seconds(), BinanceTradeStream, Public Binance aggregate-trade stream. It has no authenticated endpoints., agg_trade_hash() (+48 more)

### Community 1 - "Community 1"
Cohesion: 0.05
Nodes (40): Settings, HealthChecker, Any, Path, Any, Path, StructuredLog, MetricsCollector (+32 more)

### Community 2 - "Community 2"
Cohesion: 0.09
Nodes (64): _age_seconds(), _card_markup(), _case_for_observation(), _case_row(), DashboardServer, DashboardState, _data_quality_exceptions_page(), _diagnostic_card() (+56 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (28): Citation, GoatHubKnowledge, KnowledgeDocument, KnowledgeResult, Path, _tokens(), NewsIntelligence, NewsItem (+20 more)

### Community 4 - "Community 4"
Cohesion: 0.09
Nodes (36): Protocol, Deterministic statistics over persisted Binance Spot aggTrades., AggTradeReader, _canonical_trade(), _decimal(), OrderflowMetric, OrderflowMetricsEngine, OrderflowMetricsService (+28 more)

### Community 5 - "Community 5"
Cohesion: 0.12
Nodes (26): AcceptanceMonitor, Criterion, EventCategory, Any, datetime, Path, StrEnum, Deterministic evaluator. It never advances time or fabricates evidence. (+18 more)

### Community 6 - "Community 6"
Cohesion: 0.13
Nodes (38): _canonical(), _decimal(), _evidence_signature(), _hash(), _number(), _percentile(), Any, datetime (+30 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (28): canonical(), digest(), parse_time(), Any, datetime, Path, Read-only validator for persisted research artifacts., ResearchAuditEngine (+20 more)

### Community 8 - "Community 8"
Cohesion: 0.13
Nodes (26): Immutable, provenance-first knowledge contracts for TIM V2., Claim, ClaimStatus, Contradiction, DecisionHistory, Evidence, Fact, Observation (+18 more)

### Community 9 - "Community 9"
Cohesion: 0.05
Nodes (44): type, pattern, type, pattern, type, $ref, type, minLength (+36 more)

### Community 10 - "Community 10"
Cohesion: 0.11
Nodes (28): Dataset catalog contracts; deliberately no data ingestion or storage., dataset_from_manifest_json(), DatasetVersion, StrEnum, QualityMetrics, Immutable V2 dataset metadata contracts. The platform stores metadata and…, Decode one strict metadata manifest without opening its source URI., TimeRange (+20 more)

### Community 11 - "Community 11"
Cohesion: 0.05
Nodes (41): coverage_percent, duplicate_record_count, end, missing_record_count, record_count, start, additionalProperties, maximum (+33 more)

### Community 12 - "Community 12"
Cohesion: 0.05
Nodes (41): duplicate_records, generated_at, input_hash, issues, provenance_counts, quality_score, records_checked, valid_records (+33 more)

### Community 13 - "Community 13"
Cohesion: 0.11
Nodes (25): Observation, ResearchCase, ShortTermAssistant, ShortTermReport, BenchmarkSuite, Any, Path, Observation (+17 more)

### Community 14 - "Community 14"
Cohesion: 0.10
Nodes (27): FilesystemAdapter, GitAdapter, Any, Path, sha256_file(), structured_metadata(), freshness_status(), Classify source freshness from evidence, never from reachability alone. (+19 more)

### Community 15 - "Community 15"
Cohesion: 0.15
Nodes (31): CaptureFixture, Path, scan_project(), utc_now(), test_global_progress_is_not_invented(), test_identical_evidence_has_identical_snapshot_id(), test_real_scan_is_incrementally_idempotent(), test_snapshot_exposes_empty_integrity_lists() (+23 more)

### Community 16 - "Community 16"
Cohesion: 0.06
Nodes (31): artifact_added, artifact_changed, artifact_deleted, artifact_moved, artifact_reclassified, claim_superseded, module_status_changed, risk_resolved (+23 more)

### Community 17 - "Community 17"
Cohesion: 0.07
Nodes (30): 1.0, 1.1, boolean, type, pattern, type, type, type (+22 more)

### Community 18 - "Community 18"
Cohesion: 0.15
Nodes (21): _canonical_claim_value(), _claim_payload(), _claim_value(), extract_claims(), _identifier(), _incompatible(), _interval(), _parse_time() (+13 more)

### Community 19 - "Community 19"
Cohesion: 0.08
Nodes (25): additionalProperties, format, type, type, pattern, type, $id, type (+17 more)

### Community 20 - "Community 20"
Cohesion: 0.23
Nodes (21): doctor(), main(), run_scan(), call_tool(), handle(), Any, serve(), answer() (+13 more)

### Community 21 - "Community 21"
Cohesion: 0.21
Nodes (23): detect_contradictions(), build_module_states(), build_snapshot(), Any, artifact(), conflicting_artifacts(), Any, MonkeyPatch (+15 more)

### Community 22 - "Community 22"
Cohesion: 0.19
Nodes (6): _json_value(), MarketRepository, datetime, Observation, ResearchCase, _validate_observation_for_persistence()

### Community 23 - "Community 23"
Cohesion: 0.13
Nodes (10): OllamaClient, Any, Probe the local Ollama API without running a model., observation_prompt(), Observation, test_ollama_availability_accepts_models_endpoint(), test_ollama_availability_handles_unreachable_service(), _Response (+2 more)

### Community 24 - "Community 24"
Cohesion: 0.13
Nodes (11): ResearchRouter, asyncio, test_async_module_a_uses_only_injected_tim_data(), test_module_b_writes_cited_local_report(), test_router_refuses_deep_module_without_authorization(), test_sync_router_rejects_running_event_loop(), test_trigger_ignores_unconfigured_pattern(), test_trigger_is_idempotent_and_persists_audit() (+3 more)

### Community 25 - "Community 25"
Cohesion: 0.12
Nodes (21): type, null, null, type, type, preference_reason, preferred_claim_id, repository_commit (+13 more)

### Community 26 - "Community 26"
Cohesion: 0.20
Nodes (14): Deterministic, read-only analytics over persisted TIM research data., _average(), _distribution(), _most_common(), Any, datetime, Pure statistics. Input is never mutated and no observations are produced., ResearchAnalyticsEngine (+6 more)

### Community 27 - "Community 27"
Cohesion: 0.22
Nodes (14): canonical_json(), load_config(), Any, TIM Intelligence Manager: isolated, read-only project intelligence., classify(), config_hash(), content_manifest_hash(), Hash stable source identity without borrowing a parent Git commit. (+6 more)

### Community 28 - "Community 28"
Cohesion: 0.18
Nodes (11): BroncxRules, Observation, Small deterministic Week-1 observation rules; never emits trading instructions., ObservationEngine, Central deterministic event layer. It enriches rules; it never infers values., make(), test_rejection_and_absorption_are_evidence_based(), test_rules_require_closed_history() (+3 more)

### Community 29 - "Community 29"
Cohesion: 0.22
Nodes (13): _validate_candle_for_persistence(), _validate_observation_input_hash(), Candle, candle_input_hash(), Observation, asyncio, test_observation_rolls_back_when_case_persistence_fails(), candle() (+5 more)

### Community 30 - "Community 30"
Cohesion: 0.17
Nodes (8): _features(), MarketMemory, Observation, Deterministic historical memory. Similarity is Jaccard overlap, not a forecast., SimilarObservation, PersistedRepository, asyncio, test_restart_dashboard_uses_persisted_case_without_reconstruction()

### Community 31 - "Community 31"
Cohesion: 0.22
Nodes (12): PaperAutomation, PaperJournalEntry, PaperPolicy, datetime, ResearchCase, Explicit TEST_ONLY case evaluation. It has no exchange or order interface., closed_case(), datetime (+4 more)

### Community 32 - "Community 32"
Cohesion: 0.12
Nodes (16): active, superseded, format, type, properties, minLength, type, claim_id (+8 more)

### Community 33 - "Community 33"
Cohesion: 0.13
Nodes (16): claim_id, claim_type, claims, contradicting_claims_preserved, contradiction_type, contradictions, evidence_refs, predicate (+8 more)

### Community 34 - "Community 34"
Cohesion: 0.27
Nodes (7): Feature contracts only; no calculation or execution., FeatureDefinition, FeatureValidity, FeatureRegistry, feature(), test_contract_is_deterministic_and_immutable(), test_missing_dependency_and_lookahead_are_rejected()

### Community 35 - "Community 35"
Cohesion: 0.13
Nodes (15): direct_fact_conflict, high, interpretation_conflict, low, medium, const, format, type (+7 more)

### Community 36 - "Community 36"
Cohesion: 0.15
Nodes (13): authoritative_git_repository, config_hash, content_manifest_hash, data_gaps, generated_at_utc, known_unknowns, module_states, repository_commit (+5 more)

### Community 37 - "Community 37"
Cohesion: 0.15
Nodes (13): content_sha256, dataset_id, event_time, license_name, observation_time, publication_time, quality, retention_policy (+5 more)

### Community 38 - "Community 38"
Cohesion: 0.15
Nodes (12): additionalProperties, additionalProperties, type, additionalProperties, type, $defs, claim, contradiction (+4 more)

### Community 39 - "Community 39"
Cohesion: 0.31
Nodes (7): BOSDetector, Observation, SwingPoint, candle(), test_bearish_break_of_structure(), test_bullish_break_of_structure_requires_closed_cross(), test_no_bos_with_insufficient_or_open_candle()

### Community 40 - "Community 40"
Cohesion: 0.21
Nodes (12): agg_trades, agg_trades_reject_future_time, candles, candles_reject_future_time, observations, observations_reject_future_time, orderflow_observations, orderflow_validations (+4 more)

### Community 41 - "Community 41"
Cohesion: 0.29
Nodes (5): Observation, ObservationRegistry, item(), test_immutable_deterministic_observation(), test_time_order_rejected()

### Community 42 - "Community 42"
Cohesion: 0.17
Nodes (12): agent_interpretation, human_decision, model_inference, observed_fact, overlapping, recommendation, research_observation, unknown (+4 more)

### Community 43 - "Community 43"
Cohesion: 0.21
Nodes (3): ManagerStore, Any, Path

### Community 44 - "Community 44"
Cohesion: 0.36
Nodes (5): EvaluationPlan, EvaluationRegistry, plan(), test_evaluation_is_recommendation_only(), test_leakage_blocks_evaluation()

### Community 45 - "Community 45"
Cohesion: 0.36
Nodes (5): SimulationRun, SimulationRegistry, run(), test_execution_is_rejected(), test_simulation_contract_is_immutable()

### Community 46 - "Community 46"
Cohesion: 0.36
Nodes (5): StrategyCandidate, StrategyRegistry, test_candidate_is_immutable_and_non_executable(), test_execution_state_is_rejected(), value()

### Community 47 - "Community 47"
Cohesion: 0.18
Nodes (11): minLength, type, format, type, properties, entity_type, name, observed_at (+3 more)

### Community 48 - "Community 48"
Cohesion: 0.20
Nodes (10): type, pattern, collector, commit, provenance, repository, additionalProperties, properties (+2 more)

### Community 49 - "Community 49"
Cohesion: 0.22
Nodes (4): Database, Any, Path, repository()

### Community 50 - "Community 50"
Cohesion: 0.22
Nodes (9): acceptance_report, architecture_decision, branch, commit, document, module, platform, test (+1 more)

### Community 51 - "Community 51"
Cohesion: 0.22
Nodes (9): artifact_id, classification, content_hash, normalized_path, size_bytes, source_id, provenance, required (+1 more)

### Community 52 - "Community 52"
Cohesion: 0.22
Nodes (9): entity_id, event_id, event_type, event_version, occurred_at, payload, source_refs, entity_type (+1 more)

### Community 53 - "Community 53"
Cohesion: 0.22
Nodes (9): items, minItems, type, uniqueItems, type, items, type, evidence_refs (+1 more)

### Community 54 - "Community 54"
Cohesion: 0.53
Nodes (5): LongTermContext, LongTermIntelligence, LongTermSnapshot, test_longterm_context_is_deterministic_and_descriptive(), test_missing_longterm_evidence_is_explicit()

### Community 55 - "Community 55"
Cohesion: 0.25
Nodes (8): id, index_mode, name, relationships, source, source_hash, required, version

### Community 56 - "Community 56"
Cohesion: 0.25
Nodes (8): target_id, type, additionalProperties, required, type, relationships, items, type

### Community 57 - "Community 57"
Cohesion: 0.25
Nodes (8): items, minItems, type, items, type, $ref, claims, contradictions

### Community 58 - "Community 58"
Cohesion: 0.29
Nodes (7): properties, target_id, type, minLength, type, minLength, type

### Community 59 - "Community 59"
Cohesion: 0.33
Nodes (5): additionalProperties, $id, $schema, title, type

### Community 60 - "Community 60"
Cohesion: 0.47
Nodes (4): _json_object(), Normalize asyncpg JSONB output without hiding corrupt persisted data., test_json_object_accepts_asyncpg_string_and_mapping(), test_json_object_keeps_invalid_storage_visible()

### Community 61 - "Community 61"
Cohesion: 0.40
Nodes (5): provisionally_resolved, resolved, unresolved, resolution_status, enum

### Community 62 - "Community 62"
Cohesion: 0.60
Nodes (3): plan(), test_immutable_hypothesis_and_unknown_replay_abstain(), test_plan_manifest_and_replay_are_deterministic()

### Community 63 - "Community 63"
Cohesion: 0.50
Nodes (4): full_content, metadata_only, enum, index_mode

### Community 64 - "Community 64"
Cohesion: 0.50
Nodes (4): unversioned, versioned, repository_status, enum

### Community 65 - "Community 65"
Cohesion: 0.50
Nodes (4): source, minLength, pattern, type

### Community 66 - "Community 66"
Cohesion: 0.50
Nodes (3): asyncio, Path, test_module_b_local_report_and_isolated_gpt_researcher()

### Community 67 - "Community 67"
Cohesion: 0.67
Nodes (3): minLength, type, id

### Community 68 - "Community 68"
Cohesion: 0.67
Nodes (3): source_hash, pattern, type

### Community 69 - "Community 69"
Cohesion: 0.67
Nodes (3): pattern, type, config_hash

## Knowledge Gaps
- **286 isolated node(s):** `Settings`, `$schema`, `$id`, `title`, `type` (+281 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Observation` connect `Community 13` to `Community 0`, `Community 3`, `Community 39`, `Community 22`, `Community 23`, `Community 28`, `Community 29`, `Community 30`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Why does `DashboardState` connect `Community 2` to `Community 24`, `Community 26`, `Community 30`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `required` connect `Community 36` to `Community 33`, `Community 51`, `Community 37`, `Community 38`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Are the 16 inferred relationships involving `Trade` (e.g. with `_BuildingCandle` and `CandleAggregator`) actually correct?**
  _`Trade` has 16 INFERRED edges - model-reasoned connections that need verification._
- **Are the 13 inferred relationships involving `Candle` (e.g. with `BOSDetector` and `SwingPoint`) actually correct?**
  _`Candle` has 13 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `Observation` (e.g. with `BOSDetector` and `SwingPoint`) actually correct?**
  _`Observation` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 2 inferred relationships involving `DashboardState` (e.g. with `ResearchAnalyticsEngine` and `PersistedRepository`) actually correct?**
  _`DashboardState` has 2 INFERRED edges - model-reasoned connections that need verification._