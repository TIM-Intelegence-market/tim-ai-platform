# Graphify TIM Manager End-to-End Report

Date: 2026-07-29

Status: **PASS**

Transport: local stdio

Client: TIM Manager `GraphifyReadOnlyClient`

Graph: static codegraph only

Graph SHA-256:
`60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513`

## Scenarios

Commands use:

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli graphify --enable`

| ID | Tool / input | Exit | Runtime | Result / provenance | Security and actual behavior |
|---|---|---:|---:|---|---|
| 01 | `query_graph`: `TIM Intelligence Manager scanner` | 0 | 832 ms | 1 bounded block, 16 source paths, truncation explicit | PASS; code components only |
| 02 | `query_graph`: `DatasetRegistry dataset platform` | 0 | 713 ms | 1 block, 4 source paths | PASS; Dataset code/tests located |
| 03 | `query_graph`: `KnowledgeRegistry dependencies` | 0 | 688 ms | 1 block, 3 source paths | PASS; Knowledge dependencies located |
| 04 | `query_graph`: `ResearchRegistry research platform` | 0 | 701 ms | 1 block, 4 source paths | PASS; Research code/tests located |
| 05 | `query_graph`: `Graphify integration schema` | 0 | 690 ms | 1 block, 4 source paths | PASS; only content present in frozen codegraph |
| 06 | `get_neighbors`: `KnowledgeRegistry` | 0 | 641 ms | 1 block, normalized module/test paths | PASS; module-to-test relationship visible |
| 07 | `get_community`: `8` | 0 | 676 ms | 46-node community, normalized source paths | PASS; bounded community result |
| 08 | `get_node`: unknown identifier | 0 | 655 ms | explicit not-found text; no source; warning | PASS; no invented node |
| 09 | denied `list_prs` request | nonzero | 86 ms | no MCP dispatch | PASS; structured `tool_not_allowlisted` log |
| 10 | prompt-injection text as search input | 0 | 654 ms | retrieval result remains untrusted text | PASS; no Git/tool/trading action |
| 11 | excluded-path terms | 0 | 751 ms | `No matching nodes found`; no source paths | PASS; excluded content unavailable |
| 12 | kill server, call, close, create new client | 0 | 1,650 ms | termination detected; new handshake succeeds | PASS; safe recovery without retry storm |

## Repeated query

Two independent `KnowledgeRegistry` queries were normalized by removing only
per-request UUID, timestamp, and the hash of raw order variance. The remaining
validated results were byte-identical:

`63a6c57c3616a8403606f2358811f02144c86a11773c84818c7ec80adcb5f576`

The graph remained byte-identical before and after. Query logging was disabled,
and no repository command or global agent configuration was executed or
modified.

## Scope distinction

- codegraph: operational;
- Graphify MCP server: operational locally;
- TIM Manager MCP client: connected and read-only locally;
- semantic document index: unavailable / NO-GO and not used;
- ChatGPT Workspace Agent: not connected and not part of this acceptance.
