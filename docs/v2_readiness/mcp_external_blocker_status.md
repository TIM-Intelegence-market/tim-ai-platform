# TIM V2 Secure MCP External Blocker Status

Program ID: `TIM-V2-FINAL-READINESS-20260801`

Local evidence cut-off: `2026-08-01T15:30:11Z`

External account evidence cut-off: `2026-07-31T01:01:00+02:00`

Status: **BLOCKED — EXTERNAL OPENAI ACTION REQUIRED**

Data-readiness impact: **SEPARATE WORKSTREAM — NOT A COVERAGE EXCEPTION**

## Decision

The local TIM Graphify and gateway implementation is safely disabled and
passes its focused read-only security tests. Secure MCP cannot be enabled
because the existing OpenAI Platform organization cannot currently be
associated automatically with the existing ChatGPT Business workspace.

This external blocker does not justify a TIM V2 PASS, a coverage waiver, a new
workspace, a new organization, a reused broad API key, or any public listener.
Data quality, scientific readiness, and runtime reliability remain governed by
their own evidence.

## Verified external evidence

The account and UI evidence recorded on 2026-07-31 establishes:

- the user is Owner of the existing ChatGPT Business workspace;
- Developer Mode is enabled;
- the existing Platform organization role is Owner;
- the role explicitly includes Tunnels Read, Manage, and Use;
- organization-only creation of `tim-graphify-readonly` succeeded;
- adding the exact existing workspace ID and saving failed;
- the UI offered `Contact Support`.

The exact returned error was:

```text
We couldn't automatically verify the association between these workspaces
and organizations.
```

No missing permission name was reported. The evidence therefore localizes the
blocker to OpenAI's control-plane organization/workspace association, not TIM,
Graphify, Owner role, Developer Mode, or a missing Tunnels permission.

The authoritative detailed account identifiers and redacted tunnel ID remain
in:

- `docs/integrations/secure_mcp_permission_root_cause.md`;
- `docs/integrations/secure_mcp_permission_matrix.md`;
- `docs/integrations/secure_mcp_official_requirements.md`;
- `docs/integrations/secure_mcp_support_dossier.md`.

At `2026-08-01T15:29Z`, the official OpenAI Help Center was checked once in the
Codex in-app browser. The surface displayed a `Login` link, proving that this
browser session was not authenticated. The support chat was therefore not
opened and no dossier was transmitted. No later association success, support
response, or case identifier exists, so the blocker remains open.

## Local safe-state verification

| Check | Current evidence | Result |
|---|---|---|
| Graphify MCP enabled | `false` | PASS — safely disabled |
| Workspace gateway enabled | `false` | PASS — safely disabled |
| Allowed gateway clients | empty | PASS — fail-closed |
| Transport | local stdio; secure tunnel required at gateway boundary | PASS |
| Graph access | read-only exact allowlist; writes/unknown tools/shell interpolation denied | PASS |
| Graph integrity | configured SHA-256 matches `graphify-out/graph.json` | PASS |
| `tunnel-client` installed | not found on local `PATH` | BLOCKED / NOT STARTED |
| Tunnel/Graphify gateway process | none active | PASS — no premature exposure |
| Runtime key loaded into TIM | none detected | PASS — no premature credential |
| Custom MCP App | no completed-app evidence | BLOCKED / NOT CREATED |
| Public MCP listener | none | PASS |

The four blocker documents were reviewed for credential values and false PASS
claims, then committed and pushed as commit `9d0077a`. No API-key value,
runtime key, browser token, cookie, or private log was included.

## Test evidence

The focused Graphify/Gateway suite completed with 55 passes and no failures.
It covers:

- default disabled state;
- exact read-only tool allowlists;
- anonymous, unknown, and write denial;
- path and source exclusions;
- graph hash and provenance checks;
- prompt/shell inertness;
- schema, result-size, timeout, replay, timestamp, rate, and concurrency limits;
- crash/recovery and secret-redaction behavior.

These local tests cannot prove external workspace association or tunnel
operation.

## Support status

The support dossier is technically complete and contains the exact error,
existing workspace and organization context, verified permissions, desired
resolution, and explicit instruction not to create a new workspace or
organization. It contains no credential values.

No repository evidence records a submitted ticket, case ID, submission date,
or support response. Therefore:

- `support_dossier_prepared = true`;
- `support_ticket_submitted = false`;
- `case_id = none`;
- `external_resolution = pending`.

Authenticated-surface probe on `2026-08-01`: **UNAVAILABLE IN THE CHECKED
SESSION**. Exactly zero tickets were submitted. The required manual action is:
sign in at `https://help.openai.com/`, open the single support chat, submit the
redacted dossier in `docs/integrations/secure_mcp_support_dossier.md`, and copy
the resulting case ID into this file. Do not send a duplicate case.

Submission must be performed once through an authenticated support surface by
an authorized human or separately authorized agent, and the resulting case ID
and redacted status must be recorded. Duplicate tickets are prohibited.

## Actions prohibited while blocked

- Do not create a replacement ChatGPT workspace or Platform organization.
- Do not purchase or change a plan without explicit human authorization.
- Do not expose a local or public MCP listener as a workaround.
- Do not install an unverified tunnel client.
- Do not create or reuse a broad runtime API key.
- Do not enable Graphify, the gateway, or a custom MCP app.
- Do not copy credentials into reports, logs, prompts, or source control.

## Resume gate after OpenAI resolution

Only after the existing association is confirmed:

1. verify the association in the existing workspace and organization;
2. record the support case and resolution without secrets;
3. validate the official `tunnel-client` source, version, checksum, ownership,
   and installation path;
4. create a dedicated least-privilege runtime key without exposing its value;
5. keep Graphify and the gateway disabled while testing locally;
6. run the full 55-test security suite again;
7. perform one read-only canary through the private tunnel;
8. verify provenance, audit records, limits, no public listener, and zero graph
   mutation;
9. create a private draft app only after the canary passes;
10. require separate acceptance before any persistent enablement.

Until that evidence exists, Secure MCP remains **externally blocked and
locally safely disabled**.
