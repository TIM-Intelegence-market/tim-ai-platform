# Graphify Backend Evaluation Report

Date: 2026-07-29

## Predeclared acceptance threshold

A backend passes only with:

- 100% canary completion;
- 100% syntactically valid JSON;
- 100% schema-valid output;
- zero truncations/timeouts;
- zero excluded paths;
- stable repeated output within documented tolerance;
- zero critical unsupported relationships;
- no repository modification.

Primary responses are never repaired.

## Evaluated backend

`qwen2.5:7b` (`845dbda0ea48`), local Ollama 0.32.0.

Fixed configuration:

- temperature `0`;
- seed `42`;
- context `16,384`;
- timeout `180` seconds per document;
- retries `0`;
- non-streaming;
- thinking disabled;
- strict JSON Schema in Ollama `format`;
- deterministic manifest order;
- one request per document.

Evaluation harness:

`scripts/integrations/graphify_semantic_canary.py`

Machine-readable evidence:

- `graphify-evaluation/qwen2.5-7b-official-run1-summary.json`
- `graphify-evaluation/evidence-official-run1/`

## Full canary result

| Metric | Result | Required |
|---|---:|---:|
| Documents attempted | 8 / 8 | 8 / 8 |
| Completion rate | 50.0% | 100% |
| Valid JSON rate | 50.0% | 100% |
| Schema-valid rate | 50.0% | 100% |
| Primary acceptance rate | 37.5% | 100% |
| Timeout rate | 50.0% | 0% |
| Average runtime | 128.629 s | bounded by 180 s |
| Excluded-path findings | 0 | 0 |
| Repository writes by backend | 0 | 0 |

## Per-document result

| Document | Seconds | Result | Entities | Relations | Failure |
|---|---:|---|---:|---:|---|
| `docs/tim_v2/architecture.md` | 180.143 | FAIL | — | — | timeout |
| `docs/governance/repository_governance.md` | 91.715 | FAIL | 1 | 7 | seven unknown node references |
| `docs/tim_v2/research_platform_implementation.md` | 180.136 | FAIL | — | — | timeout |
| `docs/tim_v2/dataset_platform.md` | 180.157 | FAIL | — | — | timeout |
| `docs/tim_v2/knowledge_platform.md` | 122.628 | PASS | 7 | 6 | — |
| `docs/tim_v2/observation_platform_implementation.md` | 32.245 | PASS | 1 | 1 | — |
| `docs/TIM_FINAL_SCIENTIFIC_RECONCILIATION_REPORT.md` | 180.137 | FAIL | — | — | timeout |
| `TIM_MASTER_PROMPTS/02_RESEARCH_PLATFORM.md` | 61.872 | PASS | 3 | 2 | — |

The Governance response was syntactically and structurally valid but connected
seven edges to node IDs absent from its node list. No repair or inferred node
creation was applied.

## Repeatability evidence

The smallest Observation document was evaluated three times after the schema
contract was corrected to allow native Graphify weight `0`.

- completion: 3/3;
- primary acceptance: 3/3;
- unique canonical hashes: 1;
- entity/relationship counts: 1/1 in every run;
- runtimes: 34.837 s, 21.434 s, 21.661 s.

This proves a narrow stable capability, not corpus reliability. Repeating the
entire corpus was not practical or decision-relevant after four of eight
documents timed out and another produced critical dangling references. One
complete run is sufficient to disprove the 100% acceptance requirement.

Peak per-request memory is not exposed by the Ollama API. During evaluation the
model was shown by `ollama ps` as 100% GPU with roughly 5.2 GB loaded at 16k
context; this is an observation, not a precise peak-RSS measurement.

## Gate decision

**SEMANTIC BACKEND NO-GO**

The backend fails completion, schema-validity, timeout, unsupported-
relationship, and full-corpus stability requirements. Full semantic indexing
must not start.
