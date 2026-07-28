# TIM V2 Agent Platform

Agents are proposed, bounded workflow roles; none is implemented or granted
authority by V2.0. All use typed inputs/outputs, scoped tools, budget/timeout,
identity, audit trail and explicit abstention behavior.

| Agent | Mission | Inputs / outputs | Allowed | Forbidden |
|---|---|---|---|---|
| CEO | portfolio-level status | approved reports / priorities | read, route | alter science or execution |
| Manager | reconcile status and risks | TIM-IM views / management brief | read, request review | canonical writes |
| Research | organize hypotheses | evidence / research draft | read, draft | assert facts or run unapproved studies |
| Knowledge | link evidence/claims | sources / proposed links | propose | overwrite truth |
| Dataset | inspect catalog health | manifests / gap report | read, validate proposal | duplicate or alter data |
| Evaluation | prepare evaluation review | plans / review package | analyze proposal | promote results |
| Strategy | formulate candidate policy | approved features / draft | draft | place orders |
| Simulation | prepare scenario plan | decision package / plan | draft | execute simulation/live orders |
| Documentation | maintain drafts | approved facts / documents | write drafts | invent evidence |
| Infrastructure | report platform health | observability / report | read, propose | privileged changes |
| Risk | assess constraints | evaluation / risk view | recommend block | approve itself |
| Security | assess policy | audit/security state / finding | read, propose | disclose secrets |
| Memory | retrieve scoped context | approved memory / response | read | store secrets as default |
| Routing | choose approved route | task/policy / route decision | route | bypass policy |
| MCP | expose read tools | canonical views / response | read-only serve | mutation by default |

The orchestration policy records caller, delegated role, tool grants, inputs,
outputs, evidence references and termination. A policy/budget breach cancels
the task and preserves audit evidence.
