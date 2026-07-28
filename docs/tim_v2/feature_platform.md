# TIM V2 Feature Platform

V2.0 defines feature contracts only; it calculates no feature.

A `FeatureDefinition` records its stable ID, semantic version, mathematical
definition, source dataset/fields, time alignment, computation contract,
dependency graph, code/config identity, determinism class, lookahead policy,
quality metrics, cost estimate, owner, validity range and deprecation state.

Feature definitions form a directed acyclic graph. A prospective feature is
rejected when any dependency has unknown provenance, incompatible schema,
unresolved temporal alignment or failed lookahead validation. Calculation
outputs (in a future release) must be separately versioned artifacts with a
dataset and configuration manifest; definitions never silently mutate.

No feature contract encodes strategy selection, order logic or execution.
