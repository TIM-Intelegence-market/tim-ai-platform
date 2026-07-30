# Secure MCP Permission Matrix

Date: 2026-07-31  
Gate state: **BLOCKED — TUNNEL PERMISSION REQUIRED**

| Requirement | Present | Evidence | Blocker | Action |
|---|---:|---|---|---|
| TIM Manager exists | yes | Agent ID `agt_6a6852df446c81919556552d9ade11d8` returned by the Workspace Agents control plane and visible in ChatGPT | none | preserve |
| TIM Manager published | yes | published version 4, `agtv_6a68536271b08191a246dcb8c7402e3c` | none | preserve |
| TIM Manager editable | yes | current draft readable and existing agent visible to the current Owner | none | preserve |
| Workspace Agents enabled | yes | `Enable agents` is checked in Workspace Settings | none | preserve |
| Workspace name | yes | `Üzeyir Aydin's Workspace` shown in ChatGPT and Workspace Settings | none | preserve |
| Workspace type/plan | yes | Business | none | preserve |
| Workspace admin/owner role | yes | Members table shows `Üzeyir Aydin (You)` with disabled role value `Owner` | none | preserve |
| Developer Mode available | yes | Settings → Security and login exposes the switch | none | preserve |
| Developer Mode enabled | yes | changed from disabled to enabled by the verified Owner; `aria-checked=true` | none | preserve |
| Custom apps allowed | yes | Workspace Settings → Apps exposes `Create` | none at this gate | do not create until tunnel gate passes |
| `TIM Graphify Read-Only` exists | no | exact app-name search returned no match | app not created | create only after tunnel and scan gates |
| Platform organization selected | yes | existing `Personal` organization, ID `org-tdyWfzuMoQX15UMYHTVrEay7`; organization selector shows no second organization | none | preserve; do not create another organization |
| Platform role | yes | Platform People page shows the current user as `Owner` | none | preserve |
| Tunnels Read | yes | authenticated Tunnels page is readable | none | preserve |
| Tunnels Manage | yes | authenticated Tunnels page exposes an enabled `Create tunnel` action | none | preserve |
| Tunnels Use | not runtime-verified | no tunnel can be created until association succeeds | workspace association blocks runtime use | verify after association remediation |
| Workspace association | no | creation with the exact existing Workspace ID returned: `We couldn't automatically verify the association between these workspaces and organizations.` | Platform cannot verify the existing organization/workspace pair | OpenAI Support must verify or associate the existing pair |
| Tunnel `tim-graphify-readonly` | no | post-attempt tunnel list still reports `No tunnels yet` | workspace association failed | retry only after association remediation |
| `tunnel-client` installed | no | no executable on local `PATH` | Gate 3 blocks entry into Gate 4 | validate/install only after the association gate passes |

## Blocking association

The only Platform organization available to the authenticated account is:

```text
Personal
org-tdyWfzuMoQX15UMYHTVrEay7
```

The required existing ChatGPT workspace is:

```text
Üzeyir Aydin's Workspace
Workspace ID: 7c2db1f7-4bfe-48d8-a21d-7d7994ff9a50
Workspace organization ID: org-ctdw3MDAgyYlyRWbxNyl0Buq
```

The Platform creation form accepted both exact identifiers as inputs but
rejected the association verification. Its only offered remediation was
`Contact Support`.

No alternate organization was available in the authenticated Platform
organization selector. No new organization, workspace, tunnel, API key, app,
agent draft, global configuration, or external connection was created.

