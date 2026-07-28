# TIM V2 Dataset Platform - implementation record

Status: implemented as an in-memory metadata registry on branch
`codex/dataset-platform`. It stores no raw dataset bytes, opens no source URI
and has no dependency on TIM-IM, research, knowledge or trading modules.

## Delivered contract

- Immutable `DatasetVersion` metadata with dataset/schema versions, content
  hash, source authorization, license, sensitivity, three temporal ranges,
  quality metrics, lineage, retention and supersession.
- Deterministic manifest SHA-256 over canonical JSON metadata.
- In-memory `DatasetRegistry` which preserves every attempted registration and
  marks invalid entries `QUARANTINED` with machine-readable reasons.
- JSON Schema: `schemas/tim_v2/dataset_manifest.schema.json`.

## Validation behavior

The registry validates metadata format, source authorization, temporal ordering,
quality metric ranges, unique lineage references and registered lineage/
supersession targets. It cannot verify a source's underlying bytes because raw
data is deliberately not opened or copied; the supplied content hash therefore
remains a declared external identity until a future authorized verifier exists.

## Explicit non-goals

No ingestion, persistence, data migration, feature calculation, research run,
knowledge write, simulation, broker connection or order behavior is included.
