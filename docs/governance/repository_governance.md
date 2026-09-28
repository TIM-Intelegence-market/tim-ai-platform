# TIM Repository Governance

## Authority

The standalone TIM Git repository is the source authority. A hosted GitHub
repository becomes an authorized collaboration mirror only after the owner
creates it, the remote URL is recorded, and the initial push is verified.
Neither a parent repository nor an unverified remote supplies TIM provenance.

## Branch strategy

| Branch | Purpose | Merge target |
|---|---|---|
| `main` | Accepted, stable integration state | — |
| `develop` | Optional coordinated integration when explicitly activated | `main` |
| `feature/*` | Product capability | approved integration branch |
| `research/*` | Research-platform implementation | approved integration branch |
| `experiment/*` | Isolated, non-production experiment | normally not merged without promotion review |
| `docs/*` | Documentation-only work | approved integration branch |
| `release/*` | Release candidate stabilization | `main` |
| `codex/*` | Codex task branch used by the current local workflow | approved integration branch |

Branches do not imply acceptance. One platform or governance objective is
handled per branch. Accepted platforms may change only for a demonstrated
regression and with explicit scope.

## Protection and merge rules

When GitHub is activated, protect `main` and any active integration branch:

- disallow direct pushes and force pushes;
- require pull requests and resolved conversations;
- require Doctor, Validate, complete tests, and security checks;
- require at least one independent reviewer and CODEOWNER review when defined;
- prevent authors and AI agents from self-approving;
- require an up-to-date branch and linear history or an approved merge policy;
- prohibit deletion of protected branches;
- record the reviewed commit in the acceptance evidence.

Default merge policy is squash for small focused changes and merge commit when
the branch history is itself auditable evidence. Rebase must not rewrite
accepted or published evidence. The maintainer selects the method before merge.

## Roles

| Role | Responsibility | Merge authority |
|---|---|---|
| Maintainer | Scope, access, protection, final repository decision | Yes, subject to gates |
| Developer | Implement and test an approved change | No self-approval |
| Reviewer | Independently evaluate evidence and risks | Approval only |
| Researcher | Own scientific assumptions and provenance | No repository bypass |
| AI Agent | Task-scoped analysis or changes under human oversight | Never |
| External Contributor | Propose a bounded change under contributor policy | Never |

Scientific, architecture, security, and trading boards retain their independent
decision rights. Implementation teams cannot weaken their findings.

## Commit and pull-request standards

Use `type(scope): message`. Allowed common types are `feat`, `fix`, `docs`,
`test`, `refactor`, `build`, `ci`, and `chore`. A commit must be cohesive,
reviewable, free of secrets, and accompanied by relevant tests or an explicit
documentation-only justification.

Pull requests use `.github/pull_request_template.md`. Required evidence includes
scope, protected paths, commands and exit codes, security/data impact,
compatibility, rollback, limitations, and review ownership.

## Repository contents

Commit source, schemas, configuration templates, tests, governance, and
reproducible small evidence. Do not commit virtual environments, credentials,
raw/local data, databases, backups, logs, caches, personal files, or large
generated outputs. Git LFS requires a separate decision; it is not currently
configured.

## Licensing

No `LICENSE` is currently present. The owner must choose a license based on
distribution, dependency, data, and contribution rights. Until then, public
reuse rights must not be inferred. Contributors must confirm they have the
right to submit their work.
