# Secure MCP Official Requirements

Retrieval date: 2026-07-31  
Source policy: official OpenAI domains only.

## Sources and current requirements

| Official source | Relevant current requirement | TIM decision |
|---|---|---|
| [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels) | `tunnel-client` creates an outbound HTTPS connection to OpenAI and can forward to a private stdio or HTTP MCP server without an inbound firewall port. A tunnel ID, runtime API key, local MCP reachability, and outbound HTTPS are required. | Use the existing local stdio gateway. No public listener or third-party tunnel. |
| [Secure MCP Tunnel — permissions](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#permissions-and-access) | Creating/editing requires Tunnels Read + Manage. Running the client or selecting a tunnel requires Tunnels Read + Use. Platform tunnel permissions and ChatGPT Developer Mode are separate. | Verify both permission planes independently; never infer one from the other. |
| [Secure MCP Tunnel — association](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#associate-tunnels-with-the-right-organizations-and-workspaces) | A tunnel can be associated with Platform organizations and ChatGPT workspaces. The Platform organization that owns the tunnel and the ChatGPT workspace that should list it must be included. If automatic mapping cannot be verified, OpenAI directs the customer to request a reviewed manual association override. | Creating an organization-only tunnel is valid, but it cannot satisfy the ChatGPT integration until the existing Business workspace is associated. |
| [Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) | Local MCP servers cannot be connected directly. Business and Enterprise/Edu support developer-mode custom MCP apps. Admin/owner and RBAC rules differ by plan. Tool scanning precedes app creation. | A private draft app and Secure MCP Tunnel are mandatory. |
| [ChatGPT Workspace Agents](https://help.openai.com/en/articles/20001143/) | Agents can use apps and custom MCPs. Custom MCP setup remains owner-only in collaborative editing; previews and unsupported custom MCP setup require Agent Studio. | Confirm ownership and perform preview/UI steps only in authenticated Agent Studio. |
| [Admin controls for plugins and apps](https://help.openai.com/en/articles/11509118) | Business apps and plugins are enabled by default, while app access, action controls, and app permissions remain separate. Workspace Agents use per-agent controls configured by the builder. | Keep the app private during testing and restrict the existing agent to the exact read-only action set before publication. |

## Product/UI differences from the execution prompt

- Current official tunnel documentation places Developer Mode under
  a plan-specific workspace/user-settings flow. The live Business account also
  exposes the per-user switch under **Settings → Security and login**.
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
- the Owner role explicitly has Tunnels Read, Manage, and Use;
- an organization-only tunnel named `tim-graphify-readonly` was created
  successfully.

The tunnel-creation form does not require a ChatGPT workspace. However, the
Platform could not automatically verify the association when the created
tunnel was edited to include Workspace ID
`7c2db1f7-4bfe-48d8-a21d-7d7994ff9a50`. The current UI explicitly directs the
user to OpenAI Support, matching the official association guidance. Therefore
the integration is blocked before tunnel-client installation, runtime-key
handling, app creation, or agent mutation.
