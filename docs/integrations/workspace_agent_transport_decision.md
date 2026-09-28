# Workspace Agent Transport Decision

Date: 2026-07-29

## Decision

**OPTION C PREPARATION — SECURE MCP TUNNEL, EXTERNAL CONNECTION PENDING**

The Workspace Agent is remote and cannot directly connect to local stdio or
`127.0.0.1`. A public port, anonymous endpoint, third-party tunnel, and direct
Graphify access are prohibited.

The only evidenced supported private path is:

```text
Workspace Agent
  -> approved read-only custom MCP app
  -> OpenAI Secure MCP Tunnel
  -> local tunnel client
  -> disabled-by-default TIM Workspace Gateway over stdio
  -> TIM Manager GraphifyReadOnlyClient
  -> local static Graphify codegraph
```

## What this branch may implement

- a local MCP gateway over stdio;
- the constrained Workspace query and response contracts;
- gateway-level allowlisting, limits, audit events, provenance, health, and
  fail-closed controls;
- safe default and ignored host-local configuration;
- local canary, integration, and security tests.

## What this branch must not perform

- create or start a Secure MCP Tunnel;
- expose a loopback or public port;
- create, publish, or attach a custom Workspace app;
- add credentials, tokens, certificates, workspace IDs, organization IDs, or
  host paths to Git;
- transfer repository or Graphify content outside the host;
- claim a Workspace end-to-end connection.

## External gates

An authorized workspace administrator must later:

1. confirm plan/role eligibility and enable developer mode;
2. create and associate an OpenAI Secure MCP Tunnel with the correct Platform
   organization and ChatGPT workspace;
3. store tunnel credentials outside Git;
4. run the tunnel client against the local stdio gateway;
5. create and privately test a custom MCP app;
6. scan the gateway tools and enable only the read-only actions;
7. attach that app to `TIM Manager` with read-only constraints;
8. explicitly approve the first bounded external canary.

Until those gates are complete, the only permitted final outcome is
`LOCAL PASS — EXTERNAL CONNECTION PENDING` or a failure/blocker status.
