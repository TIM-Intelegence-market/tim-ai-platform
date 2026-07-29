# Graphify Validation

Date: 2026-07-29

Status: **FAIL**

The status is FAIL because the mandatory full document index and TIM Manager
end-to-end connection were not achieved. A valid deterministic code graph and
local MCP read path were produced and verified, but those partial results do
not satisfy the master-prompt PASS criteria.

## Produced graph

| Property | Result |
|---|---:|
| Graphify version | 0.9.29 |
| Source commit embedded in graph | `925ad91e` |
| Nodes | 1,573 |
| Edges | 3,355 |
| Communities | 84 |
| Extracted relationships | 96% |
| Inferred relationships | 4% |
| Ambiguous relationships | 0% |
| Naive corpus estimate | 104,866 tokens |
| Average graph query estimate | 9,141 tokens |
| Estimated query reduction | 11.5x |

Produced artifacts:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `graphify-out/graph.json` | 1,857,521 | `60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513` |
| `graphify-out/graph.html` | 1,535,363 | `5659c15c3f344e436448b084680859e71813b2a8abe19e45b29ece66103dc3ea` |
| `graphify-out/GRAPH_REPORT.md` | 18,086 | `e1619533b5f0b268b06f76efa87a2a5daa83df4b42526d4204df39d25872c901` |
| `graphify-out/manifest.json` | 29,508 | `66ff585067b452e11f92e24288f6ddcbda56aca591ae4984702c0f1e8931bd12` |
| `graphify-out/.graphify_analysis.json` | 100,532 | `4489222fc2f7162688123fb56fe610d37458bbe4d7f3b4f3a13cc1519cc71ffd` |

Local absolute-root metadata and local caches are excluded from Git.

## Coverage

| Source group | Nodes | Result |
|---|---:|---|
| `src/` | 621 | PASS |
| `tests/` | 364 | PASS |
| `schemas/` | 455 | PASS |
| `config/` | 5 | PARTIAL; non-code JSON may not create nodes |
| `docs/` | 0 | FAIL |
| `TIM_MASTER_PROMPTS/` | 0 | FAIL |
| Sanitized metadata catalog | 0 | LIMITATION; manifest only |
| `artifacts/` content | 0 | PASS, excluded |
| `research/` content | 0 | PASS, excluded/not configured |
| `datasets/` content | 0 | PASS, excluded/not configured |
| `data/` content | 0 | PASS, excluded |

The complete code-only scan discovered 161 supported code/config/schema files.
It explicitly skipped 151 documentation files because `--code-only` was
required after both local semantic models failed validation.

## Semantic extraction attempts

1. `qwen2.5:7b`, local Ollama, default 60,000-token budget:
   produced invalid JSON and hollow responses; Graphify entered adaptive
   truncation retries. The run was stopped as incomplete.
2. `qwen2.5:7b`, local Ollama, 3,000-token budget:
   again produced summary prose instead of valid graph JSON. The run was
   stopped as incomplete.
3. `llama3.2:latest`, local Ollama, controlled single-document test:
   timed out after 180 seconds and produced no document nodes.

No external LLM provider was called, and no corpus was transmitted outside the
local machine.

## Security validation

- No graph node source matched `.env`, secrets, private, wallet, key, backup,
  raw data, `data/`, artifacts, research, or datasets.
- No private-key block, GitHub token pattern, or OpenAI-style secret pattern
  was found in the reviewable graph outputs.
- The graph reports only repository-relative source paths.
- `graphify-out/.graphify_root`, caches, provider cost records, and interpreter
  paths are ignored.
- The graph was served only on `127.0.0.1` for the bounded MCP test and the
  server was stopped afterward.

## Query and relationship validation

The local CLI query `TIM Manager knowledge graph integration` found TIM Manager
models, tests, scanner, storage, security, Knowledge Registry, and the
knowledge-graph schema with file-and-line citations.

The MCP server completed protocol initialization, exposed 10 read/query tools,
reported the graph statistics above, and returned a successful `query_graph`
response. This proves the local graph is machine-queryable. It does not prove a
ChatGPT workspace or TIM Manager client is connected.

## Mandatory failures

- README and general documentation are not graph nodes.
- `docs/` and `TIM_MASTER_PROMPTS/` are not indexed.
- The sanitized metadata catalog does not produce nodes.
- No verified TIM Manager client consumes the Graphify MCP server.

No PASS may be reported until those failures are remediated and the full
security scan is repeated.
