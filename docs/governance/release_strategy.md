# TIM Release Strategy

## Version model

TIM uses semantic versioning for declared releases:

- `v1.0.0`: TIM-IM release line;
- `v2.0.0`: TIM V2 foundation release line;
- `v2.x.y`: accepted platform increments and compatible fixes.

These names are planning conventions, not evidence that a tag or release
exists. No tag or release is created by this foundation.

## Release path

Development proceeds through implementation, full validation, independent
acceptance, an approved integration branch, post-merge validation, release
candidate review, and owner-approved publication. No stage is skipped.

A release candidate must identify:

- version, exact commit, branch, and schema versions;
- scope and protected components;
- release notes and changelog;
- complete test, Doctor, Validate, security, and acceptance reports;
- migrations, compatibility, rollback, recovery, and known limitations;
- artifact hashes and responsible approvers.

## Gates

A failing or incomplete scientific, architecture, security, or trading review
remains visible and constrains the release claim. Documentation-only or
research releases must not be described as production or trading ready.

Tags are annotated and created only after explicit owner authorization. A
release points to the reviewed commit; tags are never moved. Rollback selects a
known compatible prior release and follows its documented data and
configuration recovery procedure.

## Current state

Repository governance is prepared locally. GitHub publication, CI checks,
branch protection, license selection, tags, releases, and production readiness
remain unconfigured or unapproved.
