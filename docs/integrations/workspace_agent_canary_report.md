# Workspace Agent Local Canary Report

Status: **20/20 PASS**

Command: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager/test_workspace_gateway.py`

| ID | Scenario | Evidence | Result |
|---:|---|---|---|
| 1 | Default disabled | `test_canary_01_safe_default_is_disabled_and_fail_closed` | PASS |
| 2 | Explicit local enablement | same test | PASS |
| 3 | Health | `test_gateway_health_reports_all_local_components_and_hash_integrity` | PASS |
| 4 | Request reaches manager adapter | `test_canary_04_authorized_query_is_mapped_to_existing_read_only_client` | PASS |
| 5 | Manager reaches Graphify | real eight-operation local run | PASS |
| 6 | Provenance | `test_canary_16_response_contract_has_graph_provenance_and_trust_boundary` | PASS |
| 7 | Graph hash | same test and real run | PASS |
| 8 | Unknown operation denied | `test_canary_05_unknown_and_explicit_write_operations_are_denied` | PASS |
| 9 | Write denied | same test | PASS |
| 10 | Unknown tool denied | same test and nested-dispatch test | PASS |
| 11 | Prompt injection inert | `test_canary_12_prompt_and_shell_text_remain_inert_data` | PASS |
| 12 | Shell fragment inert | same test | PASS |
| 13 | Excluded path no result | `test_canary_13_excluded_path_returns_no_result_and_path_traversal_is_inert` | PASS |
| 14 | Oversized request denied | `test_canary_10_request_query_and_result_bounds_are_enforced` | PASS |
| 15 | Rate limit | `test_canary_09_rate_limit_fails_closed` | PASS |
| 16 | Timeout bounded | `test_canary_15_timeout_returns_error_without_unbounded_wait` | PASS |
| 17 | Graphify outage | `test_canary_14_downstream_failure_is_bounded_and_provenanced` | PASS |
| 18 | Manager/client outage | same bounded downstream test | PASS |
| 19 | Audit has no secrets | `test_canary_19_audit_is_structured_and_redacts_secret_material` | PASS |
| 20 | Shutdown/no file mutation | CLI refusal, path test, protected-state comparison | PASS |

Additional tests cover MCP handshake, all mappings, response-size limit,
invalid provenance/hash, schemas, anonymous access, stale timestamps, replay,
and configuration fail-closed behavior. The real local run exercised all eight
operations against Graphify with unchanged hash
`60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513`.
