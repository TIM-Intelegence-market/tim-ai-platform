# TIM AI Access Governance

## Common controls

AI access is least-privilege, time-bounded, task-scoped, and human-supervised.
An AI system may read only the sources required for its task and may write only
to an approved branch and path set. It must preserve provenance, disclose
limitations, run required validation, and stop at approval boundaries.

No AI system may directly change `main`, merge, release, create tags, weaken
security, remove tests to obtain a pass, alter protected evidence, override an
independent review, expose secrets, or activate trading.

## System responsibilities

| System | Intended task | Allowed access | Boundaries and responsibility |
|---|---|---|---|
| Codex | Repository implementation, review, tests, documentation | Local task branch; approved files and commands | Human approves external publication and irreversible actions |
| Claude Code | Equivalent bounded repository assistance | Local clone/task branch after explicit grant | Same gates as a developer; no independent approval of own work |
| Claude Desktop | Read-oriented analysis and MCP-assisted context | Explicit read-only sources by default | Client connection must be verified; example config is not proof |
| OpenCode | Bounded local coding workflow | Local task branch after explicit grant | No unreviewed merge or credential access |
| ChatGPT | Management discussion and evidence synthesis | Approved workspace sources; read-only by default | Workspace-agent connection must be technically demonstrated |
| Local models | Offline classification or explanation | Explicit local inputs, no network by default | Outputs are generated evidence, never canonical facts by themselves |

## Data classes

- **Public repository metadata:** may be shared after publication approval.
- **Internal source and governance:** task-scoped access.
- **Metadata-only evidence:** names, hashes, types, dates, and relationships;
  content remains excluded.
- **Restricted:** secrets, credentials, wallet material, personal data, raw
  data, backups, and private research inputs; no AI indexing.

## Prompt and output provenance

Record the tool/system, model where available, task, input-source references,
branch, commit, timestamp, output hash, reviewer, and acceptance status.
Generated text is an artifact, not a validated fact. Claims must link to
repository evidence and retain conflicts rather than silently resolving them.

## Access lifecycle

The maintainer grants access for a named task, verifies configuration, monitors
the result, and revokes access when the task ends. Suspected exposure triggers
immediate stop, containment, evidence preservation, credential rotation where
applicable, and an incident review.
