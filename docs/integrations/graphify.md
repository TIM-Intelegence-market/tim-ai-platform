# Graphify Knowledge Integration

## Purpose and status

The intended information flow is:

`GitHub → Graphify → Knowledge Graph → TIM Manager`

This document defines a safe, platform-neutral indexing contract. On
2026-07-29, the official local Graphify CLI was installed and a deterministic
code graph was built from the GitHub-tracked Foundation branch. No hosted
Graphify service, credential, webhook, GitHub application, or TIM Manager
workspace connection was configured.

Current status: `LOCAL CODE GRAPH BUILT; FULL DOCUMENT INDEX FAILED
VALIDATION`. See `graphify_validation.md`.

## Index policy

| Mode | Paths | Meaning |
|---|---|---|
| Full content | `docs/`, `TIM_MASTER_PROMPTS/`, `schemas/`, `src/`, `tests/`, `config/` | Text and repository metadata may be indexed subject to file-level exclusions |
| Metadata only | allowlisted files under `artifacts/`, future `research/results/`, future `datasets/` | Only path, type, size, hash, version, timestamp, and relationships; never content |
| Excluded | `.env`, `.env.*`, `secrets/`, `keys/`, `wallet/`, `private/`, `backups/`, `raw_data/`, `data/`, output, databases, logs, caches | No discovery, content, embedding, snippet, or retention |

The repository uses `config/`, not `configs/`; Graphify must use the actual
directory and must not trigger a migration. Missing future directories are
`NOT CONFIGURED`, not silently treated as empty successful sources.

The machine-readable policy is
`config/integrations/graphify_index_policy.yaml`. Every connector must enforce
deny rules before allow rules and must fail closed when classification is
ambiguous.

## Entity contract

The knowledge graph may represent Modules, Platforms, Documents, Commits,
Branches, Tests, Acceptance Reports, and Architecture Decisions. Each entity
uses `schemas/integrations/knowledge_graph_entity.schema.json` and contains:

- stable ID, name, entity type, and version;
- repository-relative source and source hash;
- observed date;
- typed relationships;
- index mode and provenance.

Acceptance reports are evidence documents, not proof that the current branch
is accepted. Commits and branches are separate entities. A mutable branch name
must never replace an immutable commit hash as provenance.

## Recommended relationships

- module `DEFINED_BY` document or schema;
- platform `CONTAINS` module;
- test `VERIFIES` module or requirement;
- acceptance report `EVALUATES` commit;
- commit `PARENT_OF` commit and `MODIFIES` document;
- architecture decision `GOVERNS` module;
- branch `POINTS_TO` commit.

Contradictory claims and review outcomes remain distinct linked evidence.
Graphify must not synthesize a PASS or overwrite canonical repository content.

## Privacy and security

Never transmit secrets, credentials, private keys, wallet data, personal data,
raw market data, backups, local databases, private research content, prompt
credentials, or model-provider tokens. Hashes identify content but do not make
sensitive content safe to share.

Use a read-only GitHub integration with access limited to the TIM repository.
Store service credentials outside Git, apply retention limits, log access
without sensitive content, and support deletion/re-indexing. Complete a data
protection and vendor-retention review before activation.

## Activation checklist

1. Create and verify the authoritative GitHub repository and immutable commit
   provenance.
2. Approve licensing and data classifications.
3. Review the machine policy and deny-list against the hosted tree.
4. Configure a read-only Graphify identity with least privilege.
5. Run a dry-run inventory and inspect every metadata-only item.
6. Validate entity schema, hashes, relationships, deletion, and re-indexing.
7. Connect TIM Manager read-only and verify citations end to end.
8. Record the client, repository, commit, configuration hash, test evidence,
   operator, and date.

Until every step is evidenced, the integration status is `PARTIAL, NOT
ACCEPTED`.
