# Data Model

The canonical model consists of `SourceRecord`, `ArtifactRecord`,
`ProjectEvent`, `ClaimRecord`, `ModuleState`, risks and `ProjectSnapshot`.

Scientific facts, model inferences and human decisions remain distinct. The v1
scanner creates observed repository facts only. Unsupported claims remain
`unknown`. Stable IDs use UUIDv5; content identity uses SHA-256.

S11 contradiction detection consumes only explicit `tim_manager_claims` arrays
from JSON metadata. Each claim has a normalized subject and predicate, a value,
a claim class and at least one evidence reference. The deterministic detector
supports controlled status and Boolean incompatibilities, temporal overlap,
supersession, measurement-method separation and claim-class priority.
Contradiction records preserve both claims, use stable UUIDv5 identifiers and
remain visible even when one claim is provisionally preferred.
