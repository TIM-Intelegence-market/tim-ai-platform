# Graphify Semantic Validation Report

Date: 2026-07-29

Gate 1 result: **FAIL**

## Execution decision

The Canary backend gate failed. In accordance with the master prompt:

- full `docs/` indexing was not started;
- full `TIM_MASTER_PROMPTS/` indexing was not started;
- no semantic index manifest was fabricated;
- the existing deterministic codegraph remains the active Graphify artifact.

## Canary integrity

Eight existing documents were referenced by path, size, and SHA-256. No
authoritative document was copied, rewritten, or edited. Hash verification was
performed before every model request.

The set covers architecture, governance, scientific/research documentation,
Dataset, Knowledge, Observation, headings/lists, long-form text, and one Master
Prompt.

## Security and provenance

- Model execution was local through Ollama.
- No external provider received repository content.
- No excluded path appeared in accepted or rejected structured fragments.
- Every accepted node and relationship used its exact repository-relative
  canary source.
- Master Prompt content was delimited as untrusted source data.
- No response altered Constitution, review, platform, research, or governance
  source files.
- Invalid output was neither repaired nor merged.

## Representative semantic queries

Queries for Constitution, Dataset, Knowledge, Research, Feature, Observation,
independent reviews, and Graphify governance were not run against a semantic
graph because no accepted full semantic graph exists. Reporting such queries as
successful would conceal the failed gate.

The existing codegraph remains operational, but it contains zero `docs/` and
zero `TIM_MASTER_PROMPTS/` nodes and cannot serve as semantic-validation
evidence for these queries.

## Required remediation

Gate 1 requires a backend that completes every canary document under the fixed
contract, produces no dangling references, and repeats within tolerance.
Candidate selection must remain local or receive explicit approval for any
external content transfer.
