# Security Policy

TIM is currently a local, research-only system. It must not contain production
exchange credentials, wallet material, private keys, personal access tokens, or
live-trading secrets.

## Reporting

Do not publish a suspected vulnerability or secret in an issue, pull request,
commit, chat transcript, or log. Report it privately to the repository
maintainer through an owner-approved private channel. A public security contact
will be added only after the authoritative GitHub repository exists.

Include the affected revision, component, reproduction conditions, impact, and
whether credentials or personal data may be involved. Do not include the secret
itself.

## Response

The maintainer will triage the report, contain exposure, preserve evidence,
rotate affected credentials outside Git, add a regression check, and document
the resolution. A secret committed to Git must be treated as compromised even
if a later commit removes it; history remediation requires explicit approval.

## Supported versions

No public production release is currently supported. The reviewed branch and
commit named in an acceptance report define the supported evaluation target.
Tags, hosted releases, and production readiness must not be inferred from this
file.

## Baseline controls

- `.env*`, local data, databases, logs, backups, and generated output are
  ignored.
- Pull requests require secret and large-file review.
- AI systems receive least-privilege, task-scoped access.
- Direct changes to `main` and bypass of required reviews are prohibited.
- Security findings cannot be weakened by an implementation team.
