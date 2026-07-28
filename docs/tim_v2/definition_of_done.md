# TIM V2 Definition of Done

A V2 change is done only when:

- implementation matches approved interfaces and dependency rules;
- code, schemas, migrations and configuration are versioned;
- deterministic unit, integration and acceptance tests pass;
- full affected regression suites pass;
- scientific changes have independent validation;
- security and secret scans pass;
- provenance captures code, configuration, data and model identity;
- logs, metrics, traces and failure behavior are verified;
- migration and rollback were rehearsed;
- protected V1 hashes or boundaries were checked;
- no unauthorized Trading or Execution capability was introduced;
- documentation, decision log, risk register and technical debt are updated;
- release notes and version increment are correct;
- reviewer approvals are recorded;
- the release artifact is reproducible from its tag.

Passing tests alone is insufficient when evidence, rollback or governance is
missing.
