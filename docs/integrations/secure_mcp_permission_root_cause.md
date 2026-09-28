# Secure MCP Permission Root-Cause Review

Review time: 2026-07-31 01:01 CEST
Status: **BLOCKED — VERIFIED OPENAI PLATFORM ISSUE**

## Decision

The original blocker is **not** a missing `Tunnels Use` permission.

The authenticated OpenAI Platform preset Owner role explicitly reports:

```text
Tunnels
Read, Manage, Use
```

The verified blocker is OpenAI's inability to automatically associate the
existing Platform organization with the existing ChatGPT Business workspace.

## Permission matrix

| Permission | Required for | Present | Tested | Evidence |
|---|---|---:|---:|---|
| Read | view/select tunnel | yes | yes | Tunnel settings and tunnel list are readable; Owner role lists Read |
| Manage | create/edit tunnel | yes | yes | `tim-graphify-readonly` was created successfully and its edit dialog is available |
| Use | run client/select tunnel | yes | role-verified, runtime pending | Owner role explicitly lists Use; runtime cannot be proven before workspace association and runtime-key setup |

## Organization and project context

| Field | Verified value |
|---|---|
| Platform organization | `Personal` |
| Platform organization ID | `org-tdyWfzuMoQX15UMYHTVrEay7` |
| Current Platform role | Owner |
| Alternate Platform organization | none visible |
| Existing project | `Default project` |
| Project ID | `proj_aNEeiYnmgqdgpzVbeHYeGCOy` |
| Project geography | Global |
| Existing project key | present, not read, copied, or used |

Tunnel permissions are organization-level. No new project, organization, API
key, or workspace was created.

## Tunnel-creation probe

| Check | Result |
|---|---|
| Tunnel settings accessible | PASS |
| Display name accepted | PASS |
| Description accepted | PASS |
| Existing Platform organization selected | PASS |
| Project required | no |
| ChatGPT workspace required to create tunnel | no |
| Organization-only tunnel creation | PASS |
| Created tunnel | `tim-graphify-readonly` |
| Tunnel ID | `tunnel_6a6b…fa3c` |

The successful creation proves that Read and Manage are effective and that the
prior failure did not prevent tunnel creation itself.

## Workspace-association probe

The created tunnel was edited and the exact existing Workspace ID was selected:

```text
7c2db1f7-4bfe-48d8-a21d-7d7994ff9a50
```

Saving returned:

```text
We couldn't automatically verify the association between these workspaces
and organizations.
```

No permission name was reported as missing. The UI offered `Contact Support`.
The official Secure MCP Tunnel documentation independently states that a
reviewed manual association override is required when the organization and
workspace mapping cannot be verified automatically.

## Root cause

```text
Existing Platform organization
        ↓
Tunnels Read + Manage + Use present
        ↓
Organization-only tunnel creation succeeds
        ↓
Existing Business workspace association requested
        ↓
OpenAI association verification fails
```

This is an OpenAI control-plane organization/workspace mapping issue. It is
not a TIM defect, local MCP defect, missing Owner role, missing Developer Mode,
or missing Tunnels permission.

No `tunnel-client`, runtime key, custom app, agent mutation, public listener,
or external MCP request was started after the failure.
