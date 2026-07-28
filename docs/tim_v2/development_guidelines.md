# TIM V2 Development Guidelines

## Python style

- target an explicitly supported Python matrix;
- use type hints for public interfaces;
- prefer immutable value records and pure deterministic functions;
- keep I/O at adapters and domain logic independent of frameworks;
- format and lint through versioned tooling;
- avoid implicit global state and import-time side effects.

## Architecture rules

- dependency direction follows the architecture baseline;
- TIM-IM, Knowledge and Research never import Execution;
- domain records cross modules through versioned interfaces;
- adapters isolate external systems;
- generated/model output is non-canonical until validated;
- failures produce typed states, not invented defaults.

## Dependency policy

- pin direct runtime and test dependencies through an approved lock strategy;
- document license, provenance and security posture;
- prefer standard-library and already-approved dependencies;
- no dependency upgrade is bundled with unrelated behavior work;
- produce an SBOM for releases;
- remove unused dependencies deliberately.

## Testing policy

- unit tests for deterministic rules;
- contract tests for every interface;
- integration tests use isolated stores and controlled fixtures;
- regression tests cover frozen V1 boundaries;
- temporal/leakage tests are mandatory for scientific features;
- property or fuzz tests protect parsers, IDs and migrations where useful;
- XFAIL requires an owner, reason and expiry; release blockers may not be
  hidden by XFAIL.

## Security

- default deny for writes, network and execution;
- secrets are externally injected and never committed;
- sanitize logs and model prompts;
- validate paths, symlinks, sizes and structured input;
- separate read, management and execution credentials;
- every privileged action is authenticated, authorized and audited.

## Logging

- structured JSON-compatible events with UTC timestamps;
- correlation, run and artifact IDs;
- no secrets, raw credentials or unnecessary personal data;
- distinguish domain events, audit events and diagnostic logs;
- define retention and rotation;
- logging failure must not silently enable execution.

## Configuration

- version defaults and schemas;
- inject environment/site overrides explicitly;
- keep secrets outside configuration files;
- compute an effective-configuration hash;
- reject unknown critical keys;
- document precedence and safe defaults.

## Versioning

- semantic versions for released components;
- annotated Git tags for releases;
- patch for compatible fixes, minor for compatible features, major for
  incompatible contracts;
- scientific model/data identities are versioned independently of software.

## Schema evolution

- additive minor changes are preferred;
- required/incompatible changes require a major schema version;
- consumers must state supported versions;
- retain migration and backward-read tests;
- never reuse field meaning.

## Migration

- migrations are idempotent or checkpointed;
- dry-run and rollback are mandatory;
- validate counts, hashes and invariants;
- keep source evidence and backups;
- migration code is reviewed like production code.

## Documentation

- architecture, interfaces and decisions change with code;
- state assumptions, limitations and non-goals;
- commands include expected exit codes;
- examples use synthetic/non-secret data;
- diagrams are maintained as text-based Mermaid where practical.

## Release process

1. confirm clean scoped branch;
2. verify version and change manifest;
3. run targeted and full regressions;
4. run security, protected-path and migration checks;
5. produce release notes and compatibility matrix;
6. commit intentionally;
7. create an annotated tag;
8. verify tag, tree and reproducibility;
9. publish only with explicit remote authority.

## Code review

- review correctness, boundaries, failure behavior and evidence;
- require specialist review for science, security and execution;
- no self-approval for critical promotion gates;
- comments are resolved or explicitly accepted as debt;
- verify that tests would fail without the intended behavior.

## Scientific validation

- pre-register hypothesis, dataset identity and evaluation method;
- separate train, validation, holdout and live observation periods;
- test temporal integrity and lookahead leakage;
- report negative and inconclusive results;
- preserve configurations, seeds and environment identity;
- distinguish statistical significance, robustness and operational utility;
- promotion requires independent reproduction.

## Branch strategy

The planned branch namespaces are:

- `main`: protected, releasable baseline;
- `release/*`: stabilization for a named release;
- `feature/*`: scoped product capability;
- `hotfix/*`: urgent compatible correction;
- `research/*`: governed research implementation;
- `experiment/*`: disposable/non-promotable exploration;
- `docs/*`: documentation-only work.

Branches are created only for authorized work. This foundation task creates no
automatic development branches.
