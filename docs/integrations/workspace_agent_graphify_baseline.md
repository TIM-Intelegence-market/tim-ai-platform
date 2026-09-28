# Workspace Agent Graphify Integration Baseline

Date: 2026-07-29

## Decision

**MATCH — capability discovery may continue**

| Check | Required | Observed | Result |
|---|---|---|---|
| Repository | `/Users/tim/Documents/TIM/tim` | same | PASS |
| Branch | `codex/tim-manager-mcp-client` | same | PASS |
| HEAD | `ae80ab871635eba835356619171f3332b0f4a41c` | same | PASS |
| Working tree before this report | clean | clean | PASS |
| GitHub remote | existing origin | `uezeyiraydin-cell/tim-ai-platform` | PASS |
| Python | available | `3.14.6` | PASS |
| TIM Manager | installed package | `1.0.0` | PASS |
| Graphify | installed | `0.9.29` | PASS |
| Client default | disabled | disabled | PASS |
| Client transport | stdio | stdio | PASS |
| Client policy | read-only, fail-closed | active | PASS |
| Allowed tools | seven local graph tools | exact match | PASS |
| Codegraph hash | verified | `60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513` | PASS |
| Nodes | 1,573 | 1,573 | PASS |
| Relationships | 3,355 | 3,355 | PASS |
| Communities | 84 | 84 | PASS |
| Doctor | PASS | PASS, exit 0 | PASS |
| Validate | PASS | PASS, exit 0 | PASS |
| Client tests | 31 PASS | 31 passed, 1 warning | PASS |
| TIM-IM tests | 89 PASS | 89 passed, 1 warning | PASS |
| Complete TIM suite | 302 PASS | 302 passed, 145 warnings | PASS |

The warnings are the existing `pytest-asyncio` deprecations. No semantic
indexing, external connection, model download, global configuration change,
merge, tag, release, Git mutation, or graph write occurred during baseline
verification.
