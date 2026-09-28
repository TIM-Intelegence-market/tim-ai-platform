# Workspace Agent Capability Matrix

Date: 2026-07-29

Agent: `TIM Manager` (`agt_6a6852df446c81919556552d9ade11d8`)

Evidence combines the live editable agent configuration, its live channel
inventory, available workspace apps, and current official OpenAI product
documentation. No agent draft was changed.

| Capability | Supported | Evidence | Risk | Decision |
|---|---|---|---|---|
| Published Workspace Agent | yes | published version `agtv_6a68536271b08191a246dcb8c7402e3c` | low | retain |
| ChatGPT channel | yes | live agent configuration | low | retain |
| Attached apps/connectors | no | `connectors=[]`, `linked_connectors=[]` | none | no current data path |
| API trigger channel | available, not configured | agent channel API reports no channels | one-way trigger; no response retrieval | not a retrieval transport |
| Custom MCP app | product-supported | official Workspace Agent and developer-mode documentation | admin, tool, and data boundary | required future app |
| Direct local stdio from Workspace Agent | no | official documentation says local MCP is not directly reachable | impossible remote/local boundary | reject |
| Direct localhost/loopback | no | same product boundary; no agent connector exists | false connectivity claim | reject |
| Remote MCP endpoint | yes in product | custom app setup scans a supplied MCP endpoint | external exposure/auth | only through approved secure path |
| Secure MCP Tunnel | product-supported, not configured | official local-MCP guidance | workspace/org/admin setup | preferred external bridge |
| Streamable HTTP / SSE details | not proven in live agent config | no attached MCP app metadata | protocol mismatch | tunnel client must own translation |
| WebSocket | not evidenced | no configuration or documentation evidence found | unsupported assumption | reject |
| App authentication | yes | personal/end-user or shared/agent-owned modes; custom apps choose auth | credential scope | least privilege only |
| Tool action constraints | yes | workspace app controls expose `READ_ONLY`; official agent controls | response data is not filtered by action constraints | retain gateway filtering |
| User/admin confirmation | required for setup | developer mode and custom-app publishing require authorized user/admin | manual dependency | external pending |
| Secret storage | connection-managed for apps; no TIM secret configured | live configuration contains no links or tokens | unknown tunnel credential storage until setup | never version |
| Audit logs | product-dependent | Compliance API documented for Enterprise/Edu; current entitlement not proven | incomplete centralized audit | local structured audit plus admin verification |
| Execution location | Workspace Agent remote; TIM/Graphify local | live agent versus local repository/process evidence | trust boundary | tunnel required |

## Current agent state

The agent has instructions, starter prompts, persistent per-user memory, and a
ChatGPT deployment. It has no attached connector, no API channel, no Slack
deployment, no custom MCP, and no proof of any local repository binding.

The API trigger feature starts a Workspace Agent run but currently provides no
run ID or retrievable response. It cannot implement synchronous Graphify
retrieval.
