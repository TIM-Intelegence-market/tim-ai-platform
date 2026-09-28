# TIM Constitution Band 8 — adoption record

Status: ADOPTED ON GOVERNANCE BRANCH

## Change request

### Problem and motivation

Bands 1–7 establish system, data, agent, security and lifecycle governance but
do not consolidate TIM's scientific method, evidence rules, statistical
reporting, bias controls, peer review and publication standard into one
authoritative Constitution document.

### Scope

- adopt the Band-8 scientific standard as a canonical Constitution document;
- link Band 8 in the authoritative Master Prompt precedence;
- document applicability, acceptance evidence and unresolved conformance work.

### Non-goals

- no Research, Knowledge, Dataset, Feature, Evaluation, Strategy or Decision
  implementation change;
- no alteration of historical data, scientific evidence or research results;
- no new experiment, evaluation, publication or scientific claim;
- no retrofit of existing records or schemas;
- no merge, tag or release.

### Affected platforms

Governance documentation only. Band 8 governs future scientific work and
scientific claims across TIM, but this adoption does not modify any platform.

### Risks and alternatives

The primary risk is treating adoption of the standard as proof that existing
research and platform implementations already conform. This report explicitly
rejects that interpretation.

Keeping scientific requirements distributed across platform prompts was
rejected because it would allow inconsistent evidence and validation standards.
Retrofitting implementations in this change was rejected because it would mix
governance adoption with scientific and platform modifications.

### Rollback

Revert the Band-8 governance commit. No runtime, schema or data migration is
required.

## Classification

GOVERNANCE and DOCUMENTATION.

## Review

- Architecture: confirmed research transitions through validation into
  Knowledge, not directly into Strategy or Decision.
- Constitution: explicit precedence extends Bands 1–7.
- Canonical data: observations, evidence, datasets, features, versions, hashes
  and lineage remain referenced rather than silently changed.
- Security: no access, secret, dependency, network or runtime control changes.
- Scientific integrity: negative results, bias, limitations and separation of
  observation, fact, interpretation and hypothesis are explicit.
- Scope: one Constitution document, one index update and one adoption record.

## Lifecycle applicability for this adoption

This is a documentation-only governance change. It performs no scientific
research and makes no scientific claim. Experiment-specific Replay, Cross
Validation, Walk Forward, Out-of-Sample, statistical, robustness and
sensitivity tests are therefore not applicable to this adoption itself.
They remain mandatory where applicable to future scientific work.

Executable regression risk is covered by Doctor, Validate and the complete TIM
test suite. Post-Merge Validation, Release, Monitoring and Maintenance remain
pending and are not reported as PASS.

## Acceptance criteria

- canonical Band-8 document exists;
- Master Index links Band 8 after Bands 1–7;
- scientific method, evidence, reproducibility, statistics, validation, peer
  review, negative results, bias and publication rules are explicit;
- full suite, Doctor and Validate pass;
- diff is documentation-only;
- current conformance is not overstated;
- no merge or tag is created.

## Known limitations and debt

Band 8 does not prove that historic Research artifacts or the existing
Research, Knowledge, Dataset, Feature and Evaluation implementations satisfy
every newly consolidated scientific requirement. Such a claim requires a
separate, evidence-based conformance inventory and bounded remediation.

Existing Band-6 Security Debt and Band-7 lifecycle automation gaps remain
unresolved. This adoption neither introduces nor resolves executable controls.

## Verification

| Gate | Result |
|---|---|
| Constitution file and Master Index link | PASS |
| Change classification and Change Request | PASS |
| Architecture, Constitution, canonical-data, security and scientific-integrity review | PASS |
| `git diff --check` | PASS |
| Doctor | PASS; exit code 0 |
| Validate | PASS; exit code 0 |
| Full TIM test suite | PASS; 271 passed, 0 failed, 0 skipped, 0 xfailed/xpassed; exit code 0 |
| Protected scope | PASS; documentation-only change |
| Merge and tag exclusion | PASS; neither created |
| Post-Merge Validation, Release, Monitoring, Maintenance | PENDING; not executed and not claimed |

The complete suite finished in 33.21 seconds according to the orchestration
record; pytest reported 271 passed and 145 warnings in 31.66 seconds. The 145
known `pytest-asyncio` deprecation warnings remain technical debt and are not
represented as resolved.

Reproducible test evidence:

- `artifacts/test_reports/scientific_band8_full_suite.junit.xml`
- `artifacts/test_reports/scientific_band8_full_suite.stdout.log`
- `artifacts/test_reports/scientific_band8_full_suite.stderr.log`

## Final adoption status

PASS
