# TIM V2 Security and Safe-State Acceptance

Program ID: `TIM-V2-FINAL-READINESS-20260801`

Report evidence cut-off: `2026-08-01T16:18:45Z`

Security/runtime point sample: `2026-08-01T15:47:20Z`  
Final runtime recheck: `2026-08-01T15:59:25.361892Z`

Decision: **FAIL — P1 NETWORK AND SAFE-DEACTIVATION FINDINGS OPEN**

This is an automated technical acceptance review. It grants no trading,
scientific, release, MCP, or V2 approval.

## Executive decision

TIM's active application path is currently constrained to public-data
observation and the dashboard is currently loopback-only. Those controls pass
at the observed instant. Overall Security/Safe State cannot pass because the
PostgreSQL service is reachable on the LAN without TLS, a default database
credential is stored in tracked source, and safe supervisor-level deactivation
is not fully documented and tested. Dashboard loopback is now enforced in code
and was loaded by the controlled restart.

The Phase 0 statement that the application database endpoint is
`127.0.0.1:5432` remains true, but it must not be interpreted as a server bind
assessment. PostgreSQL itself reports `listen_addresses='*'` and listens on
IPv4 and IPv6 wildcard port 5432.

## Acceptance matrix

| Control | Evidence | Result |
|---|---|---|
| OBSERVE-only active | API reports `OBSERVE` and `observe_only=true`; database mode constraints accept OBSERVE | PASS |
| Trading capability absent from active runtime | active imports use public stream, research, database, and dashboard; no broker/order execution path | PASS |
| Order endpoints inactive | dashboard has no order or execution controls; focused test passes | PASS |
| Exchange execution credentials loaded | no relevant TIM/API/key/token/secret environment names found in the active runtime | PASS — none detected |
| Dashboard current listener | only `127.0.0.1:8765` | PASS — current state |
| Dashboard loopback enforcement | explicit IP loopback validation; `0.0.0.0`, `::`, LAN IP and hostname negative tests pass; active listener remains 127.0.0.1 | PASS |
| PostgreSQL network boundary | wildcard IPv4/IPv6 listener; LAN TCP probe succeeds; SSL off | **FAIL — P1** |
| Database role | TIM role is not superuser and cannot create DBs or roles | PASS — least privilege at role level |
| Credential storage | tracked default database credential in `config/settings.py` | **FAIL — P1 contributor** |
| Common secret patterns in operational logs | zero OpenAI-key, GitHub-token, bearer, private-key, or credential-assignment matches | PASS — scoped scan |
| Common secret patterns in MCP reports | none identified in the four reviewed documents | PASS — scoped scan |
| Graphify read-only mode | disabled by default, exact tool allowlist, writes and shell interpolation denied | PASS |
| Workspace Gateway fail-closed | disabled, no allowed clients, anonymous/unknown/write operations denied | PASS |
| Graphify MCP client fail-closed | graph hash/provenance/size/tool limits enforced; disabled by default | PASS |
| Prompt-injection handling | tool output treated as untrusted data; focused adversarial tests pass | PASS — tested scope |
| Unknown tools | rejected by client and gateway tests | PASS |
| Protected paths | default-deny policy protects data, output, live, secret, environment, key, and wallet paths | PASS |
| Symlink escape and path traversal | normalization and focused tests reject escape | PASS |
| Dangerous Graphify configuration | executable/argument identity is not fully digest/owner/mode pinned | PARTIAL / HARDENING REQUIRED |
| Collector signal handling | `SIGINT`/`SIGTERM` request graceful stop | PARTIAL |
| Supervisor-aware stop/deactivation | launchd `KeepAlive`; no tested bootout/disable runbook found | FAIL |

## P1: PostgreSQL LAN exposure

Read-only server probes established:

- `listen_addresses='*'`;
- `ssl='off'`;
- wildcard IPv4 and IPv6 port 5432 listeners;
- a successful TCP connection to port 5432 through the host's LAN address.

The effective host-based authentication rules could not be read with the
non-superuser TIM role, so they cannot be credited as a compensating control.
The role is appropriately non-superuser but owns the six TIM application
tables. A tracked default database credential in `config/settings.py` raises
the impact of the network exposure. The credential value is intentionally not
reproduced in this report.

Required remediation:

1. Bind PostgreSQL to loopback only unless a separately approved private
   database network is required.
2. Verify effective `pg_hba.conf` and host firewall rules with authorized
   administrative access.
3. Rotate the TIM database password after the listener boundary is closed.
4. Remove the tracked operational credential default and require secret
   injection through an approved local mechanism.
5. Prove that `127.0.0.1:5432` succeeds and the host LAN address fails.

## Application safe state

The active runtime consumes an unauthenticated public Binance aggregate-trade
stream. No authenticated exchange client, order placement, broker, wallet,
position, or capital allocation interface is active. The paper automation
module defaults disabled and has no exchange interface. Operational log scans
found no execution events.

The dashboard's current listener is correctly restricted to loopback. The
candidate now rejects non-loopback IPs and arbitrary hostnames before server
construction; negative tests cover `0.0.0.0`, `::`, a LAN address and an
external hostname. The controlled restart loaded this invariant and the live
listener remains `127.0.0.1:8765`.

The dashboard exposes local POST research endpoints without authentication.
They do not trade, but rate limiting and a local request-origin or CSRF-style
guard should be considered to reduce local abuse and compute-exhaustion risk.

## Graphify and gateway boundary

The current Graphify MCP and workspace-gateway configuration is safely
disabled. The gateway has an empty client allowlist, requires a secure MCP
tunnel authentication boundary, rejects anonymous callers, exposes only
read-only operations, and audits a hash rather than the raw client ID. The
configured frozen graph hash matches the graph on disk.

Focused security tests cover default disablement, client allowlisting,
unknown/write denial, schema and prompt/shell inertness, protected source
paths, replay/rate/timestamp checks, timeouts, provenance, graph hash,
crash/recovery behavior, and secret redaction. All 55 focused tests passed.

Remaining defense-in-depth work:

- pin the canonical Graphify executable and exact arguments, including digest,
  owner, and safe file mode;
- extend redaction to standalone OpenAI-style and other supported credential
  formats;
- normalize and enforce repository-root/exclusion policy on source references
  returned by the untrusted tool, not only on input queries;
- terminate timed-out workers and retain the concurrency permit until actual
  completion;
- hard-disable or harden the older `src/tim_manager/mcp_server.py`, which can
  return raw exception text, so it cannot be selected accidentally.

These hardening items do not override the current disabled/fail-closed PASS,
but they must be resolved before external enablement.

## Stop and safe deactivation

The runtime installs graceful signal handlers, while its launch agent uses
`KeepAlive`. Sending a signal alone therefore does not constitute safe
deactivation because the supervisor can relaunch the process. No tested
repository runbook was found that performs supervisor bootout/disable,
verifies port and process shutdown, preserves cursor state, and documents
rollback.

The main agent's active `caffeinate -dimsu -w 19210` guard is a reversible
availability mitigation only. It is not a security control or a safe-stop
mechanism and terminates with the referenced runtime.

Required acceptance evidence:

1. documented supervisor-aware stop and start commands with exact service
   identity;
2. state/cursor preservation before stop;
3. verification that runtime, dashboard, and collector are down;
4. rollback and restart verification without loss, duplicates, or cursor
   rewind;
5. negative proof that no execution component appears during any transition.

## Test evidence

- 55 Graphify MCP client and workspace-gateway tests: PASS.
- 59 selected runtime, dashboard, restart-state, policy and persistence tests:
  PASS.
- Complete isolated suite: 362 passed, zero failures/skips/XFAIL.
- Common high-risk token pattern scan of tracked MCP reports and operational
  logs: zero matches in the tested patterns.

The scans are bounded evidence, not a proof that every possible secret format
is absent. No secret values were read into this report.

## Final status

Current OBSERVE behavior and the live dashboard binding pass, but the P1
database network boundary and safe-deactivation gaps prevent overall
acceptance. Security/Safe State remains **FAIL** until remediation and
independent retest.
