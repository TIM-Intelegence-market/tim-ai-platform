# TIM Manager Graphify MCP Client Acceptance

Date: 2026-07-29

## Acceptance status

**PASS**

## Implemented boundary

- minimal MCP client port and local stdio adapter;
- fixed static Graphify codegraph;
- Graphify read-only domain adapter;
- disabled-by-default configuration plus schema;
- seven-tool allowlist and three explicit network-tool denials;
- argument, response, provenance, size, timeout, and graph-integrity checks;
- structured security denials and secret redaction;
- explicit CLI integration only;
- deterministic normalized retrieval output;
- safe process shutdown and post-crash recovery.

## Targeted acceptance

The targeted suite covers configuration, default disablement, schema
constraints, allowlist, unknown/write/network-tool denial, timeout, malformed
and error results, oversized and empty results, missing provenance,
graph-hash mismatch, process shutdown, serialization, secret redaction,
handshake, discovery, live allowed and denied calls, crash/recovery, graph
immutability, prompt injection, inert tool names, inert shell fragments,
excluded paths, and global-configuration isolation.

## Final validation

Environment:

- Python `3.14.6`;
- pytest `8.4.2`;
- Graphify `0.9.29`.

| Validation | Command | Exit | Result | Runtime |
|---|---|---:|---|---:|
| Targeted client tests | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager/test_graphify_mcp_client.py` | 0 | 31 passed, 0 failed/skipped/XFAIL/XPASS, 1 warning | 3.25 s |
| TIM-IM tests | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager` | 0 | 89 passed, 0 failed/skipped/XFAIL/XPASS, 1 warning | 23.46 s |
| Complete TIM suite | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q` | 0 | 302 passed, 0 failed/skipped/XFAIL/XPASS, 145 warnings | 32.87 s |
| Doctor | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli doctor` | 0 | PASS | <1 s |
| Validate | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli validate` | 0 | PASS | <1 s |
| Config schema | Draft 2020-12 validation in isolated environment | 0 | PASS | <1 s |
| Repeated read | two explicit `KnowledgeRegistry` searches | 0 | normalized outputs byte-identical | <2 s |

The 145 complete-suite warnings are the previously recorded
`pytest-asyncio` deprecations. No dependency migration was performed.

## Protected state

Before/after graph SHA-256:

`60b11531c8cdbce3786d66f35cf4a5b649c95824271e1aed7682ff2b1702d513`

Counts remained 1,573 nodes, 3,355 relationships, and 84 communities. The
graph file timestamp did not change during the final test window.

Hash anchors for four Constitution files, the scientific reconciliation
report, the TIM-IM final acceptance report, and the graph matched the
`1225fd2b48794d4113aa4cf2f69e642a7097a782` baseline byte-for-byte. Git scope
contains only the optional client, its CLI route, versioned configuration and
schema, integration documentation, and client tests.

No global Claude, OpenCode, or ChatGPT configuration path is referenced by the
client, and no command in this implementation writes such a configuration.

## Acceptance boundaries

This PASS applies only to the local optional TIM Manager client and the existing
static codegraph. It does not change the earlier semantic backend NO-GO and
does not claim a ChatGPT Workspace Agent connection.
