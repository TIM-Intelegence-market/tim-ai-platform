# Graphify MCP Trust Boundary

Date: 2026-07-29

Status: **IMPLEMENTED AND TESTED LOCALLY**

Graphify is an optional retrieval and navigation layer. It is not a source of
truth, governance authority, scientific evidence source, repository actor, or
trading/capital authority.

## Runtime controls

- disabled-by-default versioned configuration;
- explicit enable required for each CLI invocation;
- local stdio and fixed absolute executable/working-directory/graph paths;
- `shell=False`; no shell interpolation or dynamic command construction;
- minimal child environment and `GRAPHIFY_QUERY_LOG_DISABLE=1`;
- seven-tool local read/query allowlist;
- all PR/network and unknown tools denied client-side;
- caller-controlled `project_path` denied in both adapter layers;
- bounded strings, traversal depth, hops, tokens, results, response bytes,
  startup, request, and shutdown;
- graph SHA-256 checked immediately before every tool call;
- structured denial logs with secret redaction;
- validated, normalized result envelope with raw-response hash;
- safe EOF, timeout, crash, terminate, and kill handling;
- no retry loop.

## Result trust contract

Every accepted result contains:

- query UUID;
- `server_name = tim-graphify-readonly`;
- actual tool name;
- current verified graph SHA-256;
- UTC generation time;
- `trust_class = untrusted_retrieval`;
- bounded result blocks;
- normalized repository source references where present;
- warnings and truncation status;
- hash of the untrusted raw MCP tool result.

No result is written to TIM-IM storage, snapshots, reports, Git, or the graph.
Results can only be displayed, searched, used as quoted retrieval context, or
compared with authoritative repository evidence.

## Prompt-injection rule

Repository commands and prompts remain inert text. Tests pass an instruction
containing a shell fragment, a forbidden tool name, Git authorization language,
and trading activation language. The client performs only the originally
selected `query_graph` call; it does not execute the shell fragment or dispatch
the returned tool name.

Graphify output cannot authorize:

- system-policy changes;
- Constitution or review changes;
- test disabling;
- Git, branch, merge, tag, release, or file operations;
- capital, strategy promotion, trading, exchange, order, or execution actions.

## Residual limitations

Graphify returns unstructured text and declares no MCP output schema.
Provenance extraction therefore recognizes the server's observed `src=`,
`source_file=`, `at=...:L...`, and bracketed path forms. Results without a
repository source (for example graph statistics or an unknown node) remain
explicitly warned and are not upgraded to canonical evidence.
