# TIM V2 Governance Change
## Versioned Hash Contract Specification

**Document status:** Specification only  
**Hash Contract version:** `HC-1.0`  
**Target:** Future TIM V2 artifacts  
**Applicability:** Prospective only  
**TIM Core 1.0:** Frozen and explicitly out of scope

---

# 1. Motivation

TIM requires hashes for several distinct purposes: proving the integrity of an
artifact, identifying a source, describing a dataset, binding a replay to its
inputs and outputs, and identifying reports or snapshots.

A field name alone is insufficient to define a hash. A valid hash contract
must define:

- the semantic domain;
- the artifact type;
- the exact input;
- the canonical ordering;
- the serialization;
- the algorithm;
- the contract version;
- the scope in which comparison is valid.

`HC-1.0` makes those properties explicit and prohibits comparisons between
different domains.

# 2. Background and Root Cause Reference

The investigation documented in
`TIM_OUTPUT_HASH_ROOT_CAUSE_REPORT.md` established that the TIM Core 1.0
`OUTPUT_HASH_MISMATCH` was a deterministic hash-domain collision:

- an Insights output hash was propagated as a reference;
- a generic audit interpreted that reference as the self-hash of a different
  Readiness artifact;
- two hashes over two different inputs were compared;
- the underlying dataset, Insights output, Readiness artifact and replay were
  not shown to be nondeterministic or corrupt.

This specification prevents recurrence by requiring domain-tagged hash
descriptors and artifact-type-aware validation.

# 3. Normative Language

The terms **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT** and **MAY** are
normative.

An `HC-1.0` hash is valid only when all of the following match:

1. contract version;
2. hash domain;
3. artifact type;
4. algorithm;
5. canonicalization identifier;
6. input selection rules;
7. computed digest.

A 64-character hexadecimal value by itself is not a valid `HC-1.0` hash
descriptor.

# 4. Contract Identity

The first contract version is:

```text
HC-1.0
```

Every future V2 artifact governed by this specification MUST declare:

```json
{
  "hash_contract_version": "HC-1.0"
}
```

A validator MUST reject an undeclared or unsupported contract version. It
MUST NOT guess the version from field names or document structure.

# 5. Hash Descriptor

Every hash field governed by `HC-1.0` MUST be represented by a descriptor:

```json
{
  "contract_version": "HC-1.0",
  "domain": "artifact",
  "artifact_type": "tim.v2.example",
  "algorithm": "SHA-256",
  "canonicalization": "TIM-JCS-1",
  "digest": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
}
```

Required descriptor fields:

| Field | Definition |
|---|---|
| `contract_version` | Exact hash contract version |
| `domain` | One domain defined in this specification |
| `artifact_type` | Registered type of the hashed or referenced object |
| `algorithm` | `SHA-256` for `HC-1.0` |
| `canonicalization` | `TIM-JCS-1` or `TIM-BYTES-1` |
| `digest` | Lowercase 64-character hexadecimal SHA-256 digest |

Optional metadata such as a URI or logical identifier MAY accompany a
descriptor, but MUST NOT change its domain semantics.

# 6. Domain Separation

All structured domains use a domain envelope before hashing:

```json
{
  "contract_version": "HC-1.0",
  "domain": "<domain-name>",
  "artifact_type": "<registered-type>",
  "payload": "<domain-specific canonical input>"
}
```

The digest is:

```text
SHA-256(UTF8(TIM-JCS-1(domain-envelope)))
```

Including `contract_version`, `domain` and `artifact_type` in the hashed
envelope provides cryptographic domain separation. Identical payloads in two
different domains MUST therefore produce different digests.

For exact-byte domains, the input is:

```text
UTF8("HC-1.0\0<domain>\0<artifact-type>\0") || artifact-bytes
```

where `\0` is one zero byte.

# 7. Common Serialization Rules

## 7.1 TIM-JCS-1

`TIM-JCS-1` is the canonical structured serialization for `HC-1.0`.

Rules:

- Encoding MUST be UTF-8 without BOM.
- JSON object keys MUST be strings.
- Object keys MUST be sorted by Unicode code-point order.
- Arrays preserve their supplied order unless the domain definition requires
  semantic sorting.
- No insignificant whitespace is emitted.
- Separators are exactly `,` and `:`.
- Strings use JSON escaping.
- `ensure_ascii` is false; Unicode is encoded directly as UTF-8.
- Duplicate JSON object keys are invalid.
- `NaN`, positive infinity and negative infinity are invalid.
- Boolean values are JSON `true` and `false`.
- Null values are JSON `null`.
- Missing optional fields and explicit null fields are different inputs.
- Implementations MUST NOT insert absent optional fields during hashing.
- Hash descriptor fields that are explicitly excluded by a domain definition
  MUST be absent from the domain payload, not set to null.

## 7.2 Decimal and Float Rules

- Binary floating-point values MUST NOT appear in a canonical hash input.
- Measurements MUST use decimal strings.
- Decimal strings MUST use plain notation, never exponent notation.
- Decimal strings MUST have no leading plus sign.
- Zero MUST be `"0"`.
- Negative zero MUST be normalized to `"0"`.
- Trailing fractional zeroes MUST be removed unless a registered schema
  explicitly declares fixed scale.
- Rounding MUST occur before hashing according to the producing schema.
- The rounding mode and scale belong to the artifact schema, not to the hash
  implementation.
- A validator MUST reject a binary float in a field whose schema requires a
  decimal string.

## 7.3 Time Rules

- Timestamps MUST be RFC 3339 UTC strings.
- UTC MUST be represented by `Z`.
- Required form:
  `YYYY-MM-DDTHH:MM:SS[.fraction]Z`.
- Offset timestamps such as `+01:00` MUST be normalized to UTC before the
  artifact is finalized.
- Fractional seconds MUST omit trailing zeroes.
- A timestamp MUST represent persisted domain data, not validation time,
  file creation time or filesystem modification time, unless that timestamp is
  explicitly part of the registered artifact schema.
- Validators MUST NOT inject the current time before recomputing a hash.

## 7.4 Arrays and Ordering

Each registered artifact schema MUST classify every array as either:

- **ordered:** original order is semantically meaningful and preserved; or
- **set-like:** elements are sorted by an explicitly declared stable key.

Set-like arrays MUST declare:

- the sort key;
- ascending or descending order;
- tie breakers;
- duplicate policy.

Filesystem enumeration order, database default order, dictionary insertion
order and concurrent completion order MUST NOT determine a hashed array.

## 7.5 TIM-BYTES-1

`TIM-BYTES-1` hashes finalized bytes.

Rules:

- Text artifacts MUST be UTF-8 without BOM.
- Text artifacts MUST use LF (`0x0A`) line endings.
- Whether the final LF is required MUST be specified by the artifact type.
- No Unicode normalization may be applied after finalization.
- Binary artifacts are hashed exactly as stored.
- Filesystem metadata, filename, permissions, creation time and modification
  time are excluded unless a separate manifest explicitly includes them.

# 8. Hash Domains

## 8.1 `artifact_hash`

| Property | Definition |
|---|---|
| Domain name | `artifact` |
| Purpose | Self-integrity of the current structured artifact |
| Input | Complete logical artifact excluding only its own `artifact_hash` descriptor |
| Ordering | Artifact schema plus TIM-JCS-1 |
| Serialization | TIM-JCS-1 |
| Algorithm | SHA-256 |
| Scope | One artifact instance of one registered artifact type |
| Version | HC-1.0 |

Rules:

- `artifact_hash` MUST hash the current artifact.
- It MUST NOT hash another document.
- All other hash descriptors, including source and dataset references, remain
  inside the artifact payload.
- A validator MUST remove only `artifact_hash` before recomputation.
- An artifact MUST contain no second field claiming the same self-integrity
  role.

## 8.2 `source_hash`

| Property | Definition |
|---|---|
| Domain name | `source` |
| Purpose | Identify the immediate input artifact |
| Input | The validated digest descriptor of the immediate source plus its logical source identifier |
| Ordering | Source identifier ascending when multiple sources are permitted |
| Serialization | TIM-JCS-1 |
| Algorithm | SHA-256 |
| Scope | Immediate dependency edge, not the full transitive dependency graph |
| Version | HC-1.0 |

Rules:

- A single-source artifact MAY use `source_hash: null` when it has no source.
- Null and an empty list have different meanings and MUST follow the artifact
  schema.
- Multiple sources MUST use `source_hashes`, an array sorted by
  `(artifact_type, logical_source_id, digest)`.
- A source hash is a reference hash and MUST NOT be validated as the current
  artifact's self-hash.
- The referenced source MUST be validated under its declared domain and
  contract version before the reference is accepted.

## 8.3 `dataset_hash`

| Property | Definition |
|---|---|
| Domain name | `dataset` |
| Purpose | Identify the complete logical dataset used by a computation |
| Input | Dataset schema, selection boundary, ordered record descriptors and record content |
| Ordering | Explicit dataset key and tie breakers |
| Serialization | TIM-JCS-1 |
| Algorithm | SHA-256 |
| Scope | One immutable dataset view |
| Version | HC-1.0 |

The dataset payload MUST include:

```json
{
  "dataset_schema": "registered-schema-version",
  "selection": {
    "symbol": "BTCUSDT",
    "start_inclusive": "2026-01-01T00:00:00Z",
    "end_exclusive": "2026-02-01T00:00:00Z"
  },
  "record_order": [
    "exchange_timestamp ASC",
    "aggregate_trade_id ASC"
  ],
  "records": []
}
```

Rules:

- Selection boundaries MUST be explicit.
- Database queries MUST use the declared complete `ORDER BY`.
- Record schemas and versions MUST be included.
- Missing intervals and exclusion rules MUST be represented in dataset
  metadata.
- Pagination boundaries MUST NOT change the final dataset hash.
- The dataset hash MUST NOT include query runtime, host, PID or filesystem
  metadata.

## 8.4 `replay_hash`

| Property | Definition |
|---|---|
| Domain name | `replay` |
| Purpose | Identify one reproducible replay result |
| Input | Dataset hash descriptor, manifest hash descriptor, executable component versions, replay configuration and ordered output descriptors |
| Ordering | Components by registered name; outputs by artifact type and logical ID |
| Serialization | TIM-JCS-1 |
| Algorithm | SHA-256 |
| Scope | One replay definition and its outputs |
| Version | HC-1.0 |

Replay runtime, machine name, PID, wall-clock duration and invocation time
MUST NOT enter the replay hash. They MAY exist outside the hashed replay
payload as operational metadata.

## 8.5 `manifest_hash`

| Property | Definition |
|---|---|
| Domain name | `manifest` |
| Purpose | Identify the exact Core manifest used |
| Input | Complete manifest excluding only its own manifest hash descriptor |
| Ordering | TIM-JCS-1 |
| Serialization | TIM-JCS-1 |
| Algorithm | SHA-256 |
| Scope | One immutable manifest version |
| Version | HC-1.0 |

The hash MUST include component versions, operating mode, governance state
and rule/validation version bindings defined by the manifest.

## 8.6 `report_hash`

| Property | Definition |
|---|---|
| Domain name | `report` |
| Purpose | Identify the finalized rendered report bytes |
| Input | Exact finalized report bytes with domain prefix |
| Ordering | Already represented by byte order |
| Serialization | TIM-BYTES-1 |
| Algorithm | SHA-256 |
| Scope | One rendered report file |
| Version | HC-1.0 |

Rules:

- `report_hash` verifies a report's exact representation.
- Markdown reports require UTF-8, LF and a final LF.
- PDF and other binary reports are hashed byte-for-byte.
- A report's metadata sidecar is not part of `report_hash`.
- `artifact_hash` of a report metadata object and `report_hash` of the report
  bytes are different domains and MUST produce different digests.
- Regenerating visually equivalent bytes does not preserve the report hash
  unless the bytes are identical.

## 8.7 `snapshot_hash`

| Property | Definition |
|---|---|
| Domain name | `snapshot` |
| Purpose | Identify the logical state captured by a snapshot |
| Input | Snapshot schema, cut-off, dataset/source descriptors, version bindings, counts and persisted snapshot payload |
| Ordering | Snapshot schema plus TIM-JCS-1 |
| Serialization | TIM-JCS-1 |
| Algorithm | SHA-256 |
| Scope | One snapshot at one explicit cut-off |
| Version | HC-1.0 |

Rules:

- The cut-off timestamp MUST be explicit and persisted.
- `snapshot_hash` excludes only its own descriptor.
- `artifact_hash` may additionally protect the complete snapshot envelope.
- Because the domain tags differ, `snapshot_hash` and `artifact_hash` MUST
  differ even if their remaining payloads are otherwise identical.

## 8.8 `integrity_hash`

`integrity_hash` is optional.

| Property | Definition |
|---|---|
| Domain name | `integrity` |
| Purpose | Bind a declared set of already validated integrity descriptors |
| Input | Named member descriptors and a declared policy identifier |
| Ordering | `(member_role, artifact_type, digest)` ascending |
| Serialization | TIM-JCS-1 |
| Algorithm | SHA-256 |
| Scope | One integrity bundle |
| Version | HC-1.0 |

Example payload:

```json
{
  "policy": "tim.v2.scientific-review-integrity-1",
  "members": [
    {
      "member_role": "dataset",
      "hash": {
        "contract_version": "HC-1.0",
        "domain": "dataset",
        "artifact_type": "tim.v2.orderflow-dataset",
        "algorithm": "SHA-256",
        "canonicalization": "TIM-JCS-1",
        "digest": "..."
      }
    }
  ]
}
```

An integrity hash MUST NOT replace validation of its members. Each member
descriptor must first be validated independently.

# 9. Registered Artifact Types

Every V2 artifact type MUST have a registry entry containing:

- stable artifact type identifier;
- schema version;
- permitted hash domains;
- required hash descriptors;
- canonicalization method;
- self-hash exclusion rule;
- array ordering rules;
- decimal rules;
- timestamp rules;
- optional field rules;
- reference resolution rules.

A validator MUST reject:

- an unregistered artifact type;
- a domain not permitted for that type;
- multiple competing self-hash fields;
- a descriptor whose declared artifact type differs from the artifact;
- an implicit or inferred domain.

# 10. Validator Rules

A future `HC-1.0` validator MUST execute these steps in order:

1. Parse the artifact without modifying it.
2. Validate its artifact schema.
3. Read `hash_contract_version`.
4. Reject missing or unsupported contract versions.
5. Resolve the artifact type in the registry.
6. Validate every hash descriptor's structure.
7. Verify that each descriptor's domain is permitted for the field and
   artifact type.
8. Validate referenced artifacts using their own descriptors and domains.
9. Recompute each self-hash using only the exclusion rule for that domain.
10. Compare hashes only when contract version, domain, artifact type,
    algorithm and canonicalization all match.
11. Reject cross-domain comparisons before comparing digest strings.
12. Record a structured validation result without changing the artifact.

Required failure codes:

| Code | Meaning |
|---|---|
| `HASH_CONTRACT_MISSING` | No contract version declared |
| `HASH_CONTRACT_UNSUPPORTED` | Unknown contract version |
| `HASH_DESCRIPTOR_INVALID` | Descriptor schema invalid |
| `HASH_DOMAIN_UNKNOWN` | Unknown domain |
| `HASH_DOMAIN_NOT_ALLOWED` | Domain invalid for field/artifact type |
| `HASH_ARTIFACT_TYPE_MISMATCH` | Descriptor and artifact types conflict |
| `HASH_CANONICALIZATION_MISMATCH` | Wrong canonicalization method |
| `HASH_ALGORITHM_UNSUPPORTED` | Unsupported algorithm |
| `HASH_REFERENCE_UNRESOLVED` | Referenced artifact unavailable |
| `HASH_REFERENCE_INVALID` | Referenced artifact failed validation |
| `HASH_SELF_MISMATCH` | Validly scoped self-hash does not match |
| `HASH_CROSS_DOMAIN_COMPARISON` | A comparison crossed hash domains |
| `HASH_AMBIGUOUS_ROLE` | Field could be interpreted in multiple roles |

The validator MUST NOT:

- treat every field named `output_hash` as a self-hash;
- compare raw digest strings without descriptor validation;
- repair or rewrite an artifact;
- normalize historical content in place;
- substitute an unsupported contract version;
- turn a failed validation into PASS based on filename or context.

# 11. Examples

## 11.1 Valid Self-Hash and Source Reference

```json
{
  "hash_contract_version": "HC-1.0",
  "artifact_type": "tim.v2.readiness-report",
  "schema_version": "2.0.0",
  "source_hash": {
    "contract_version": "HC-1.0",
    "domain": "artifact",
    "artifact_type": "tim.v2.research-insights",
    "algorithm": "SHA-256",
    "canonicalization": "TIM-JCS-1",
    "digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  },
  "artifact_hash": {
    "contract_version": "HC-1.0",
    "domain": "artifact",
    "artifact_type": "tim.v2.readiness-report",
    "algorithm": "SHA-256",
    "canonicalization": "TIM-JCS-1",
    "digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
}
```

The source descriptor is validated against the Insights artifact. The
artifact descriptor is recomputed from the Readiness report. They are never
compared to each other.

## 11.2 Forbidden Ambiguous Field

```json
{
  "output_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

This is invalid under `HC-1.0` because it lacks contract version, domain,
artifact type, algorithm and canonicalization.

## 11.3 Cross-Domain Rejection

Even if these two descriptors contain the same digest, comparison is invalid:

```text
domain=dataset  versus  domain=artifact
```

The validator returns `HASH_CROSS_DOMAIN_COMPARISON` without treating equality
of the digest strings as proof of equality of the underlying objects.

# 12. Test Matrix

| Test | Expected result |
|---|---|
| Identical artifact input under the same type/domain/version | Identical hash |
| One-byte or one-field artifact change | Different hash |
| Same payload in `artifact` and `dataset` domains | Different hashes |
| Same payload under HC-1.0 and a future contract | Different hashes |
| Dictionary insertion order changes | Identical TIM-JCS-1 hash |
| Set-like array input order changes | Identical hash after specified sorting |
| Ordered array input order changes | Different hash |
| Float supplied where decimal string is required | Rejected |
| Negative zero decimal string | Normalized before artifact finalization |
| NaN or infinity | Rejected |
| Equivalent offset timestamp after producer normalization | Identical finalized value |
| Runtime timestamp inserted during validation | Validator failure |
| LF report regenerated byte-identically | Identical report hash |
| CRLF substituted for LF | Different byte hash and invalid report serialization |
| Source reference presented as artifact self-hash | `HASH_DOMAIN_NOT_ALLOWED` |
| Cross-domain digest comparison | `HASH_CROSS_DOMAIN_COMPARISON` |
| Missing contract version | `HASH_CONTRACT_MISSING` |
| Unsupported contract version | `HASH_CONTRACT_UNSUPPORTED` |
| Wrong artifact type in descriptor | `HASH_ARTIFACT_TYPE_MISMATCH` |
| Invalid self-hash | `HASH_SELF_MISMATCH` |
| Unresolvable reference | `HASH_REFERENCE_UNRESOLVED` |
| Manipulated referenced artifact | `HASH_REFERENCE_INVALID` |
| Historical Core 1.0 artifact presented to HC-1.0 validator | Classified legacy; not rewritten |
| Core 1.0 artifact bytes before and after V2 validation | Byte-identical |
| Ten identical V2 replays | Identical dataset, replay and output descriptors |
| Concurrent completion in different orders | Identical result after declared semantic sorting |

# 13. Prospective Adoption Concept

This section is a future migration concept, not an authorized migration.

## Phase 0 — Specification Freeze

- Approve `HC-1.0` as a V2 governance document.
- Assign the specification its own immutable document hash outside Core 1.0.
- Freeze the artifact-type registry and conformance fixtures for the first V2
  implementation.

## Phase 1 — Isolated V2 Implementation

- Implement canonicalization and validators in a V2-only namespace or
  repository.
- Do not import the V2 validator into the Core 1.0 runtime.
- Use synthetic conformance fixtures and newly generated V2 test artifacts.
- Prohibit production writes during conformance testing.

## Phase 2 — Dual Read, Single Write

- V2 MAY read Core 1.0 artifacts as explicitly classified legacy inputs.
- Core 1.0 artifacts retain their original bytes and hashes.
- V2 writes only new V2 artifacts using `HC-1.0`.
- A V2 source reference to a legacy artifact records the legacy hash
  algorithm and legacy contract identifier in a dedicated legacy-reference
  descriptor; it does not relabel that hash as HC-1.0.

## Phase 3 — V2 Cut-over

- Establish an explicit V2 start timestamp.
- Generate no HC-1.0 descriptors for pre-cut-over artifacts.
- Keep Core 1.0 and V2 analyses partitioned by core, schema and hash contract
  versions.
- Require manual governance approval before V2 artifacts enter a scientific
  review.

No phase permits backfill, historical rewriting or automatic migration.

# 14. Backward Compatibility

TIM Core 1.0 remains unchanged.

Rules:

- Existing Core 1.0 hashes retain their original semantics.
- Existing files remain byte-identical.
- Historical reports are not regenerated.
- Historical snapshots and reconciliation reports are not amended.
- No Core 1.0 hash is renamed or wrapped in place.
- No HC-1.0 validator may claim that a Core 1.0 artifact conforms to HC-1.0.
- A future system may label it `LEGACY_CORE_1_0` in an external V2 index,
  without editing the historical artifact.
- Cross-version analyses must preserve explicit version partitions.

# 15. Non-Goals

`HC-1.0` does not:

- modify TIM Core 1.0;
- resolve historical audit statuses;
- convert historical NO-GO results to GO;
- repair or replace historical hashes;
- define market rules, metrics, outcomes or validation thresholds;
- introduce forecasts, signals, strategies or execution;
- authorize a database migration;
- authorize a production deployment;
- define retention or deletion policy;
- prove truth of source data beyond the declared integrity boundary.

# 16. Known Limitations

- SHA-256 proves identity/integrity relative to an input; it does not prove
  that the source was truthful or complete.
- Dataset reproducibility still depends on a complete registered schema and
  deterministic selection boundary.
- Exact-byte report hashing requires reproducible renderers if regenerated
  binary reports are expected to match.
- `HC-1.0` does not define distributed consensus or a trusted timestamping
  service.
- External source artifacts may be unavailable for later reference
  validation.
- Cross-language implementations require a shared conformance suite,
  especially for Unicode, decimals and timestamps.
- Other operating systems and language runtimes must pass the same
  conformance fixtures before being accepted.
- Algorithm agility is versioned but not exercised in HC-1.0; SHA-256 is the
  only permitted algorithm.
- Legacy Core 1.0 artifacts remain governed by their historical semantics and
  may continue to surface the documented P0 audit false positive.

# 17. Governance Decision Required Before Implementation

This specification becomes implementable only after explicit approval of:

1. the `HC-1.0` contract;
2. the artifact-type registry;
3. canonical conformance fixtures;
4. a V2-only implementation boundary;
5. the V2 cut-over policy;
6. the prohibition on Core 1.0 mutation and historical backfill.

Until then this document is design evidence only.

# STATUS

**HASH CONTRACT SPECIFICATION READY**
