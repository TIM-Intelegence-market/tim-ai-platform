# Secure MCP Support Dossier

Prepared: 2026-07-31 01:01 CEST
Status: **BLOCKED — VERIFIED OPENAI PLATFORM ISSUE**

## Verified account context

| Field | Value |
|---|---|
| ChatGPT workspace | `Üzeyir Aydin's Workspace` |
| ChatGPT plan | Business |
| Workspace role | Owner |
| Workspace ID | `7c2db1f7-4bfe-48d8-a21d-7d7994ff9a50` |
| Workspace organization ID | `org-ctdw3MDAgyYlyRWbxNyl0Buq` |
| Developer Mode | enabled |
| Platform organization | `Personal` |
| Platform organization ID | `org-tdyWfzuMoQX15UMYHTVrEay7` |
| Platform role | Owner |
| Tunnel permissions | Read, Manage, Use |
| Tunnel name | `tim-graphify-readonly` |
| Tunnel ID | `tunnel_6a6b…fa3c` |

## Reproduction

1. Sign in as the Owner of the existing ChatGPT Business workspace and the
   existing Platform organization.
2. Open Platform → Organization settings → Tunnels.
3. Create `tim-graphify-readonly` with the existing `Personal` organization.
4. Observe `Tunnel created successfully`.
5. Edit the created tunnel.
6. Add exact ChatGPT Workspace ID
   `7c2db1f7-4bfe-48d8-a21d-7d7994ff9a50`.
7. Save.

Actual result:

```text
We couldn't automatically verify the association between these workspaces
and organizations.
```

The UI provides a `Contact Support` link.

## Checks already completed

- Current user is Owner in both products.
- Developer Mode is enabled.
- Platform Owner role explicitly has Tunnels Read, Manage, and Use.
- Tunnel creation and edit controls work.
- No second Platform organization is available in the account selector.
- No new workspace or Platform organization is requested.
- Current official Secure MCP Tunnel documentation was reviewed.
- No runtime key, API-key value, browser token, cookie, or private log is
  included in this dossier.

## Requested technical resolution

Please review and manually associate, or provide the supported owner workflow
to associate, the existing Platform organization:

```text
org-tdyWfzuMoQX15UMYHTVrEay7
```

with the existing ChatGPT Business workspace:

```text
Workspace: Üzeyir Aydin's Workspace
Workspace ID: 7c2db1f7-4bfe-48d8-a21d-7d7994ff9a50
Workspace organization ID: org-ctdw3MDAgyYlyRWbxNyl0Buq
```

The goal is for this existing workspace to list and use the already-created
Secure MCP Tunnel. Please do not create or migrate us to a new workspace or a
new Platform organization.

## Support message

Subject: Secure MCP Tunnel cannot verify existing Business workspace association

Hello OpenAI Support,

I am the Owner of both my existing ChatGPT Business workspace and my existing
OpenAI Platform organization. My Platform Owner role explicitly includes
Tunnels Read, Manage, and Use. I successfully created the Secure MCP Tunnel
`tim-graphify-readonly`.

When I edit the tunnel, add my exact existing ChatGPT Workspace ID, and save,
the Platform returns:

> We couldn't automatically verify the association between these workspaces
> and organizations.

Please review and manually associate the existing Platform organization and
existing ChatGPT Business workspace listed above, or provide the supported
Owner workflow that resolves this mapping. I do not want a new workspace or a
new Platform organization.

No API keys, runtime keys, or private logs are included in this request.
