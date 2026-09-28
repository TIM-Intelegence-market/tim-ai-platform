# Secure MCP external status

Status: **BLOCKED — EXTERNAL OPENAI ACTION REQUIRED**

This is a separate workstream. It neither passes nor waives TIM Core security,
coverage, runtime, data or science gates.

## Local completion

The existing Graphify MCP client and workspace gateway remain disabled by
default, read-only and fail-closed. No public MCP listener, tunnel process,
runtime key or private app was enabled. The redacted support dossier remains
complete at `docs/integrations/secure_mcp_support_dossier.md`.

Prior verified account evidence remains unchanged:

- the existing ChatGPT Business workspace and Platform organization are the
  intended pair;
- the owner role and Developer Mode are present;
- Tunnels Read, Manage and Use are present;
- automated organization/workspace association failed in the provider control
  plane;
- no new organization, workspace or second TIM Manager was created.

## Current support-surface check

At `2026-08-01T21:21:19.978Z`, the official OpenAI Help Center was checked in
the in-app browser. The page exposed a `Login` link. Opening the support chat
showed the explicit request to log in for support. The session was therefore
not authenticated.

Consequences:

- an existing-ticket search was not available;
- no dossier was transmitted;
- zero tickets were submitted in this program;
- no support case ID exists;
- no browser cookie, token or credential was read or recorded.

The machine evidence is
`artifacts/v2_completion/mcp_external_status.json`.

## Exact remaining action

Owner: **an authorized human signed into the existing OpenAI Help Center
account**.

The owner must log in at `https://help.openai.com/`, search for an existing TIM
workspace/organization association case, and submit the redacted dossier only
if no existing case exists. Exactly one case is allowed. The returned case ID
and redacted resolution must then be recorded before the tunnel/client can be
validated and any private app can be considered.

Until then, Secure MCP remains externally blocked and locally safely disabled.
