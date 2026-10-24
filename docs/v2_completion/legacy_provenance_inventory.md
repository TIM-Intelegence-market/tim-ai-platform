# Read-only legacy Module-A documentation inventory

B05 requires a counted inventory of historical provenance deficiencies. The
historical report names missing `artifact_hash`, `generator_version` and
`schema_version` fields in Module-A JSONL records. Its reported 1,602 records
are a historical observation, not a count to assume for a new input.

`scripts/v2_legacy_provenance_inventory.py` inventories one explicitly selected
frozen JSONL file. It imports no runtime configuration, contacts no database or
network, and writes only JSON to stdout. Supply the expected **file SHA-256**
from an independently frozen source manifest; an internal `artifact_hash` is
not a substitute. Do not silently compute a new expected value to make a
changed source match an old cutoff.

```sh
python scripts/v2_legacy_provenance_inventory.py \
  --input /path/to/frozen/module_a_cache.jsonl \
  --expected-sha256 <trusted-file-sha256> --max-examples 50
```

The report separates source binding from field completeness:

- `source_binding`: MATCH, MISMATCH or UNAVAILABLE. Only a completed read
  supplies an observed file hash. A read error leaves `read_complete=false`;
  any counters then describe only a partial read and cannot establish the population.
- `records_seen`: all nonblank lines, including malformed records. Blank
  lines, parsed object records and malformed records are counted separately.
- `missing_field_counts`: absent keys for the three documented fields.
  `invalid_field_counts`: non-string/blank values, plus malformed SHA-256
  syntax for `artifact_hash`. Duplicate JSON keys and invalid UTF-8 are
  malformed records; they cannot silently disappear from the denominator.
- `missing_field_combinations`: full counts grouped by missing keys. All
  records are counted even when issue examples are limited to 0–1,000 rows.
- `documentation_status`: COMPLETE, INCOMPLETE, NO_RECORDS or UNAVAILABLE.
  COMPLETE means only that these three fields have syntactically acceptable
  values. It does not verify their truth, their semantic hash domains or the
  rest of the research schema.

Exit 0 requires both MATCH and COMPLETE. All other source/documentation
outcomes return 2; invalid arguments also return 2. No output grants readiness:
`semantic_hash_verification=NOT_PERFORMED`, `classification_status=PENDING_HUMAN_REVIEW`,
`readiness_counted=false`, `v2_approved=false` remain explicit.

The report exposes field names and line numbers, not record values. It never
invents missing metadata, classifies a deficiency as permanently unrecoverable,
changes a historical audit, or repairs the known hash-domain false positive.
It is separate from the frozen Core 1.0 ResearchAuditEngine. A complete B05
acceptance still needs the actual frozen sources, dataset/cutoff mapping,
prospective-scope provenance inventory and independent human approval.

Offline tests use synthetic files, including a 1,602-record deficient fixture;
that fixture is not the historical dataset. Tests cover bounded examples,
malformed/duplicate-key records, source mismatch, missing files, partial read
failure, unchanged input bytes and command exit behavior.
