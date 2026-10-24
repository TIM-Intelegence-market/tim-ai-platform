# Contributing to TIM

TIM is an evidence-driven research system. Repository changes must preserve
determinism, provenance, protected components, and the current review findings.

## Workflow

1. Start from the approved base branch and create a narrowly scoped branch.
2. Use the branch prefixes defined in
   `docs/governance/repository_governance.md`.
3. Make only changes required by the approved scope.
4. Add or update tests and documentation.
5. Run Doctor, Validate, and the complete test suite.
6. Open a pull request with evidence, risks, and rollback notes.
7. Obtain the required independent review before merge.

Direct commits to `main`, removal of tests to obtain a passing result, silent
changes to historical evidence, and combining unrelated platforms in one pull
request are prohibited.

## Commit messages

Use `type(scope): message`, for example:

- `feat(dataset): validate manifest lineage`
- `fix(research): preserve replay ordering`
- `docs(governance): clarify review gate`
- `test(validation): cover invalid provenance`

Commits should be focused and should not contain generated data, secrets,
credentials, local databases, or virtual environments.

## License and sign-off

TIM is licensed under the Apache License, Version 2.0 (`LICENSE`, `NOTICE`).
By contributing, you agree that your contribution is licensed under the same
terms (Apache 2.0, section 5).

Every commit must carry a Developer Certificate of Origin sign-off
(<https://developercertificate.org/>). Add it with `git commit -s`, which
appends:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and e-mail must match the commit author. The repository is private;
access is granted only to people who actively work on TIM.

## Pull-request evidence

Every pull request must state:

- purpose and exact scope;
- changed and explicitly unchanged components;
- test, Doctor, and Validate commands with exit codes;
- security and data-handling impact;
- migration and rollback requirements;
- known limitations;
- related acceptance or architecture decision.

The repository owner retains final approval authority. A passing test suite is
necessary but does not override scientific, architecture, security, or trading
governance.
