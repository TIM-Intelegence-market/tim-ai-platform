# Secure MCP Official Requirements

Retrieval date: 2026-07-31  
Source policy: official OpenAI domains only.

## Sources and current requirements

| Official source | Relevant current requirement | TIM decision |
|---|---|---|
| [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) | `tunnel-client` creates an outbound HTTPS connection to OpenAI and can forward to a private stdio or HTTP MCP server without an inbound firewall port. A tunnel ID, runtime API key, local MCP reachability, and outbound HTTPS are required. | Use the existing local stdio gateway. No public listener or third-party tunnel. |
| [Secure MCP Tunnel — permissions](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#permissions-and-access) | Creating/editing requires Tunnels Read + Manage. Running the client or selecting a tunnel requires Tunnels Read + Use. Platform tunnel permissions and ChatGPT Developer Mode are separate. | Verify both permission planes independently; never infer one from the other. |
| [Secure MCP Tunnel — association](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#associate-tunnels-with-the-right-organizations-and-workspaces) | The tunnel must be associated with the owning Platform organization and target ChatGPT workspace; a personal Platform association alone does not make it visible to an Enterprise/Edu workspace. | Require positive workspace and organization evidence before tunnel initialization. |
| [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) | Local MCP servers cannot be connected directly. Business and Enterprise/Edu support developer-mode custom MCP apps. Admin/owner and RBAC rules differ by plan. Tool scanning precedes app creation. | A private draft app and Secure MCP Tunnel are mandatory. |
| [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt) | Developer Mode is under Settings → Security and login. A tunnel-backed app is added from ChatGPT Plugins, then discovered metadata and tool selection must be reviewed and tested. | Run the exact eight-tool scan and chat canary before agent attachment. |
| [ChatGPT Workspace Agents](https://help.openai.com/en/articles/20001143/) | Agents can use apps and custom MCPs. Custom MCP setup remains owner-only in collaborative editing; previews and unsupported custom MCP setup require Agent Studio. | Confirm ownership and perform preview/UI steps only in authenticated Agent Studio. |
| [Admin controls for apps](https://help.openai.com/en/articles/11509118) | Admins can allow only read actions or a custom action set and can default future actions to disabled. Members cannot add custom apps without the required role. | Select exactly eight read-only actions and disable future actions by default. |

## Product/UI differences from the execution prompt

- Current official tunnel documentation places Developer Mode under
  **Settings → Security and login**. The Help Center also documents
  plan-specific admin entry points under Workspace Settings or Apps.
- Current tunnel setup is under Platform tunnel settings; ChatGPT app creation
  uses **Tunnel** as the connection method and either selects or accepts the
  tunnel ID.
- Workspace Agents custom MCP setup is explicitly owner-only even when another
  collaborator can edit and publish the agent.
- The Codex Workspace Agents control plane can inspect and edit ordinary apps,
  but unsupported custom MCP setup and preview remain Agent Studio workflows.

## Verified product state

Authenticated UI verification established:

- the existing ChatGPT workspace is `Üzeyir Aydin's Workspace` on Business;
- the current user is the Workspace Owner;
- Workspace Agents and Workspace Apps are available;
- the existing published `TIM Manager` is visible and editable;
- Developer Mode was available and was enabled by the Owner;
- the existing Platform organization is `Personal`
  (`org-tdyWfzuMoQX15UMYHTVrEay7`);
- the current Platform role is Owner;
- Tunnels Read and Manage are available.

The Platform could not automatically verify the association between that
existing Platform organization and Workspace ID
`7c2db1f7-4bfe-48d8-a21d-7d7994ff9a50`. The current UI explicitly directs the
user to OpenAI Support. Therefore Gate 3 is blocked before tunnel-client
installation, runtime-key handling, tunnel creation, app creation, or agent
mutation.
