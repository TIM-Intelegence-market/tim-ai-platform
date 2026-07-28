# TIM V2 Migration Strategy

## Principles

- additive before subtractive;
- observe before replace;
- dual-read before cutover;
- no silent historical rewrite;
- reversible migrations with explicit checkpoints;
- source evidence remains immutable;
- V1 remains available until V2 acceptance is complete.

## Migration sequence

1. Inventory V1 interfaces, schemas, stores and operating modes.
2. Define V2 schemas and compatibility adapters.
3. Replay representative V1 fixtures into an isolated V2 environment.
4. Compare hashes, counts, temporal behavior and known limitations.
5. Run dual-read shadow validation without changing V1 writers.
6. Approve a bounded consumer cutover.
7. Retain rollback to the prior consumer and schema.
8. Archive migration evidence and decision records.

## Schema evolution

- patch: documentation or constraints without payload change;
- minor: backward-compatible additive fields;
- major: incompatible semantics or required-field changes;
- migrations never mutate raw source evidence in place;
- every migration records old/new schema, code identity, row/artifact counts,
  hashes, failures and rollback status.

## Data migration

Runtime data is copied into isolated targets and validated before any pointer
change. Destructive transforms require separately retained originals and
restore verification. Historical Research and Evaluation results remain
immutable; corrected interpretations are new records linked by supersession.

## TIM-IM transition

TIM-IM V1 remains the accepted management layer. V2 Knowledge projections may
be exposed through versioned adapters only after equivalence, abstention,
contradiction and provenance tests pass. V1 snapshots stay readable.
