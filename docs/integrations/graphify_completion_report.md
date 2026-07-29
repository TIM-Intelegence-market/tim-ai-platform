# Graphify Semantic Recovery and TIM Manager MCP Integration

Date: 2026-07-29

## Exact final verdict

**FAIL**

The existing codegraph remains operational, but neither required completion
gate passed. The local semantic candidate failed the deterministic canary, and
TIM Manager has no MCP client layer through which the Graphify server can be
connected and tested. No complete integration is claimed.

## 1. Baseline

The verified baseline matched before work continued:

- branch: `codex/github-foundation`;
- initial HEAD: `39a9d79e8af7ce12b88d6609b16432797f240d71`;
- Graphify: `0.9.29`;
- codegraph: 1,573 nodes, 3,355 relationships, 84 communities;
- graph SHA-256:
  `60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513`;
- local Graphify MCP server: initialization successful, ten tools exposed;
- baseline working tree: clean.

The graph records source commit
`925ad91e6b920edb5d7fcb372ed1bb39fa43bda4`; this is the extraction source,
not the later commit that first stored the graph and reports.

## 2. Canary corpus

`docs/integrations/graphify_canary_manifest.json` contains eight existing,
non-sensitive files selected from `docs/` and `TIM_MASTER_PROMPTS/`. It covers
architecture, governance, research, Dataset, Knowledge, Observation, an
independent review, headings/lists, a longer document, and a Master Prompt.

Each manifest entry records its repository-relative path, SHA-256, byte size,
document class, and reason. Authoritative source files were referenced, not
copied or rewritten.

## 3. Backend candidates

The local inventory covered:

- `qwen2.5:7b` (`845dbda0ea48`);
- `llama3.2:latest` (`a80c4f17acd5`);
- `deepseek-r1:8b` (`6995872bfe4c`);
- `llava:7b` (`8dd30f6b0cb1`).

Only `qwen2.5:7b` was approved for the controlled full-canary evaluation. No
model was downloaded, no paid API was used, and no repository content was sent
to an external provider.

## 4. Backend evaluation

The acceptance thresholds were declared before selection: 100% completion,
valid JSON, schema validity, no truncation or timeout, no excluded paths, stable
results, no critical unsupported relationships, and no repository writes.

Fixed evaluation settings:

- local Ollama `0.32.0`;
- temperature `0`;
- seed `42`;
- context `16,384`;
- timeout `180` seconds per document;
- zero retries;
- fixed prompt, schema, and document order;
- repairs disabled.

| Metric | Observed | Required |
|---|---:|---:|
| Documents attempted | 8 / 8 | 8 / 8 |
| Completed | 4 / 8 (50.0%) | 8 / 8 |
| Valid JSON | 4 / 8 (50.0%) | 8 / 8 |
| Schema-valid | 4 / 8 (50.0%) | 8 / 8 |
| Fully accepted | 3 / 8 (37.5%) | 8 / 8 |
| Timeouts | 4 / 8 (50.0%) | 0 |
| Critical dangling-reference result | 1 | 0 |
| Excluded paths | 0 | 0 |
| Repository writes by backend | 0 | 0 |
| Average runtime | 128.629 seconds | bounded |

The small Observation canary completed three deterministic repetitions with
one canonical result hash. This narrow success does not satisfy corpus-wide
reliability. Further full repetitions were not decision-relevant after the
first complete corpus run had already disproved the 100% gate.

The strict output-contract self-test passed ten cases: one valid fragment was
accepted and nine invalid forms were rejected. The schema and all
machine-readable manifests/summaries validate as JSON.

Gate 1: **FAIL — SEMANTIC BACKEND NO-GO**

## 5. Semantic indexing result

Full semantic indexing was **not run** because the canary gate failed.
Accordingly, no semantic index manifest was fabricated and no partial semantic
graph was promoted.

## 6. Semantic validation

There is no accepted semantic graph to validate. The required representative
semantic document queries were not claimed.

The pre-existing codegraph remains operational. A bounded CLI query for
`Knowledge Platform` returned 52 code nodes before display truncation, and a
god-node query succeeded. Its before/after SHA-256 remained unchanged.

## 7. MCP tool inventory

The local Graphify server exposes ten tools:

1. `get_community`
2. `get_neighbors`
3. `get_node`
4. `get_pr_impact`
5. `god_nodes`
6. `graph_stats`
7. `list_prs`
8. `query_graph`
9. `shortest_path`
10. `triage_prs`

Seven are local graph-read candidates. The three PR tools are network-reading
and governance-adjacent and must be denied. Direct exposure is also unsafe
because Graphify adds caller-controlled `project_path` and supports optional
query logging. A future adapter must fix the graph path, remove that argument,
disable logging, bound results, and expose only the seven local tools.

## 8. TIM Manager configuration

Discovery found a TIM Manager MCP **server**, but no MCP **client**:

- no client library;
- no client lifecycle;
- no server registry;
- no client transport configuration;
- no remote-tool allowlist;
- no client timeout or permission policy.

There is no existing client configuration to back up or safely extend.
Implementation stopped as required. A versioned read-only adapter design is
documented separately; implementing it would be new feature development and
requires architecture approval.

MCP client result: **NOT PRESENT / NOT CONNECTED**

## 9. End-to-end results

Status: **FAIL — NOT EXECUTED THROUGH TIM MANAGER**

The Graphify server was validated independently, but that is not a TIM Manager
connection. Eight positive retrieval scenarios and the adversarial runtime
scenario remain not run through TIM Manager. The excluded-path check passed
only at graph level. No connection, provenance flow, or runtime injection
boundary was simulated.

## 10. Security and trust boundaries

The required design enforces:

- repository content is untrusted retrieved data;
- retrieved instructions cannot override policy;
- no retrieved command is executed;
- no Git, governance, capital, exchange, strategy, or trading authority;
- fixed local graph path and local transport;
- seven-tool allowlist with all PR tools denied;
- no caller-controlled `project_path`;
- disabled query logging;
- bounded input, traversal, timeout, and output;
- source provenance on every result.

The repository secret-pattern scan passed. The existing graph contained no
forbidden source path. No external service was installed and no content left
the host.

## 11. Regression results

| Check | Command | Exit | Result |
|---|---|---:|---|
| Output-contract self-test | deterministic valid/invalid fixture run | 0 | PASS, 10 cases |
| Schema/manifests | Draft 2020-12 and JSON parsing | 0 | PASS |
| Doctor | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli doctor` | 0 | PASS |
| Validate | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli validate` | 0 | PASS |
| Complete TIM suite | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q` | 0 | 271 passed |
| Codegraph query | bounded `Knowledge Platform` query | 0 | PASS |
| Codegraph integrity | before/after SHA-256 | 0 | unchanged |
| Protected scope | diff from initial HEAD | 0 | PASS |
| Secret-pattern scan | scoped new artifacts | 0 | PASS |

The complete suite emitted the existing 145 `pytest-asyncio` deprecation
warnings. They remain technical debt and did not cause a test failure.

## 12. Protected paths and change scope

Only new integration documentation, schema, evaluation evidence, and the
bounded evaluation script were added. No protected Constitution, review,
research conclusion, feature/observation/strategy semantics, historical
evidence, acceptance report, trading component, or existing TIM Manager source
was modified.

No merge, tag, release, branch deletion, force push, trading activation, or
exchange connection occurred.

## 13. Exact unresolved blockers

1. No approved local semantic backend satisfies the 100% canary requirements.
   `qwen2.5:7b` accepted only 3 of 8 documents, timed out on 4, and produced one
   structurally valid but critically dangling relationship set.
2. TIM Manager has no MCP client layer. A separately approved read-only adapter
   must be implemented before Graphify can be connected and the ten end-to-end
   scenarios can be executed.
3. Because blocker 1 prevented full semantic indexing, documentation and Master
   Prompt semantic retrieval remain unavailable.

Final verdict: **FAIL**
