# Secure MCP Permission Matrix

Date: 2026-07-31  
Gate state: **BLOCKED — VERIFIED OPENAI PLATFORM ISSUE**

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
| Tunnels Read | yes | preset Owner role explicitly reports `Tunnels: Read, Manage, Use`; tunnel list is readable | none | preserve |
| Tunnels Manage | yes | preset Owner role explicitly reports `Tunnels: Read, Manage, Use`; tunnel creation succeeded | none | preserve |
| Tunnels Use | yes, not yet runtime-tested | preset Owner role explicitly reports `Tunnels: Read, Manage, Use` | workspace association blocks ChatGPT selection and later runtime proof | runtime-test after association remediation |
| Platform projects | yes | one existing `Default project`, ID `proj_aNEeiYnmgqdgpzVbeHYeGCOy` | none | preserve; tunnels remain organization-scoped |
| API-key/project context | present but not used | one active key is assigned to `Default project`; no secret was read or copied | existing key is broader than the planned dedicated runtime key | do not reuse; create least-privilege runtime key only after the gate |
| Workspace association | no | editing the created tunnel with the exact Workspace ID returns: `We couldn't automatically verify the association between these workspaces and organizations.` | OpenAI cannot verify the existing organization/workspace pair | request reviewed manual association |
| Tunnel `tim-graphify-readonly` | yes | organization-only tunnel creation returned `Tunnel created successfully`; ID recorded only in redacted form as `tunnel_6a6b…fa3c` | target ChatGPT workspace is not associated | preserve pending support resolution |
| `tunnel-client` installed | no | no executable on local `PATH` | Phase 4 requires stop before supply-chain and runtime-key work | validate/install only after association confirmation |

## Root-cause correction

The original status incorrectly grouped the failure under a generic tunnel
permission blocker. Current official documentation and authenticated UI
evidence establish:

1. The active Owner role has all three permissions: Read, Manage, and Use.
2. A tunnel can be created with the existing Platform organization alone.
3. ChatGPT workspace association is not a mandatory tunnel-creation field.
4. The organization-only tunnel was created successfully.
5. Adding the existing Business workspace afterward fails at OpenAI's
   association-verification step.

The only Platform organization available to the authenticated account remains:

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

The Platform edit form accepted the exact Workspace ID but returned:

```text
We couldn't automatically verify the association between these workspaces
and organizations.
```

The UI offers `Contact Support`. The official Secure MCP Tunnel documentation
also directs customers to request a reviewed manual association override when
the mapping cannot be verified automatically.

No alternate organization was available in the authenticated Platform
organization selector. No new organization, workspace, API key, app, agent
draft, public listener, or external MCP runtime was created.
