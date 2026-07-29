# Graphify Semantic Output Contract

Date: 2026-07-29

## Native Graphify contract

Graphify 0.9.29 instructs semantic backends to return exactly one JSON object
with:

- `nodes`
- `edges`
- optional semantic `hyperedges`
- `input_tokens`
- `output_tokens`

Nodes identify an entity, label, file type, repository-relative source, and
optional source/provenance fields. Edges identify source and target node IDs,
relation, confidence class and score, source provenance, and weight.
Hyperedges group at least three nodes under one typed relation.

Graphify's built-in structured schema constrains only the top-level
`nodes`/`edges`/`hyperedges` arrays and is currently applied to its Claude CLI
backend. The Ollama path used in the previous attempt did not apply an
equivalent JSON Schema constraint.

## TIM acceptance schema

The primary acceptance schema is:

`schemas/integrations/graphify_semantic_fragment.schema.json`

It is intentionally stricter than Graphify's internal parser:

- the top-level object and every entity have explicit required fields;
- unknown properties and unsupported enum values are rejected;
- node IDs and labels must be non-empty;
- paths must be repository-relative;
- confidence scores and relationship weights are bounded to `0..1`;
- hyperedges require at least three unique nodes;
- semantic types and relationships are allowlisted.

The acceptance validator additionally rejects conditions JSON Schema cannot
express conveniently:

- duplicate node IDs;
- duplicate edge identities;
- edges or hyperedges referencing an unknown node;
- a node or relationship attributed to another source file;
- excluded source paths;
- empty extraction for a non-empty document;
- response truncation or non-`stop` completion;
- prose before or after the JSON object;
- Markdown fences, even if their enclosed JSON would parse;
- a response whose hash or metrics cannot be recorded.

## Primary scoring rule

The raw model response is validated exactly as returned. Acceptance parsing
uses `json.loads` on the complete trimmed response and does not search for a
JSON substring, remove a preamble, strip Markdown fences, coerce types, drop
unknown fields, rename relations, invent IDs, or remove duplicates.

Any repair experiment must write a separate output and separate metrics.
Repairs are disabled for the primary reliability score and cannot convert a
failed primary response into a pass.

## Trust boundary

Every canary document is wrapped as untrusted source data. Text inside a
document cannot change the schema, authorize tools, request commands, alter
Git, or override system and governance policy. Master Prompts are indexed as
quoted repository documents, not executed as instructions.

## Fixed evaluation parameters

- deterministic canary order from `graphify_canary_manifest.json`;
- temperature `0`;
- seed `42`;
- local Ollama API only;
- non-streaming responses;
- JSON Schema supplied in the Ollama `format` field and included in the prompt;
- fixed context size per candidate;
- one request per document;
- timeout `180` seconds;
- retry limit `0` for the primary score;
- three repetitions per approved candidate where runtime permits.
