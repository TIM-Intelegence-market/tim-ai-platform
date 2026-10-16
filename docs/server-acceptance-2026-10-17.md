# Server reconciliation and functional health

## Source reconciliation (#79)

The closed PR #80 (`41438249e15548d4599eeb5942c5575a1ca42362`) contains portal files missing from `platform-main`. The same files exist byte-for-byte in the deployed portal source (`2fd86627924147256ede7fb4bcdb0ac0b2a4f009`). This change imports only `src/control_portal`, its runner, systemd template, documentation and tests. Source authorship: TIM Server Bootstrap. It preserves the unrelated historical branch.

The current worker lacked `_approved_experience`, required by the portal's original integration test. The bounded reader is restored without replacing the current documentation context or any safety gate. Malformed rows are ignored; at most four sanitized matching examples enter the prompt explicitly as untrusted context.

First-administrator HTTP bootstrap is now opt-in and incompatible with proxy-host/Secure-cookie configuration, so a new empty deployment cannot be claimed through its reverse proxy. Monitoring uses a configured loopback Ollama URL; the server service template selects `127.0.0.2:11434`.

Other old-only files were deliberately excluded: the legacy GitHub feeder and local worker entrypoints are replaced by the current issue pipeline; the network-governance worker would introduce another architecture not validated for the current Mac coordinator; historical generated evidence and obsolete server-state documents are not fresh runtime evidence. This is a bounded reconciliation, not a blanket merge of the old branch or a deployment of the portal.

## Actual server state (#78)

Observed on 17 October 2026, Europe/Berlin:

- Runtime, PostgreSQL, Ollama, `timec.service` and Caddy active.
- Portal application bound to loopback port 8090; Caddy bound only to the server LAN address port 443.
- The legacy server Qwen coordinator is disabled; the Mac handles GitHub writes while the server provides model responses.
- The installed September healthcheck probes the wrong Ollama address (`127.0.0.1`) and requires that obsolete coordinator.
- Daily database backup completed successfully on 16 October. The last isolated restore completed successfully on 11 October; this is historical evidence, not a new restore.
- Current runtime, 24-hour minute coverage and maintenance status pass. Historical gap readiness still fails; no qualification or trading activation is implied.

`scripts/tim_server_healthcheck.py` checks real services, the actual model endpoint, fresh Operations results, disabled execution, disk capacity and time synchronization. It reports historical data readiness and the patched source tree separately rather than turning them green.

The root installation is a separate, checksum-bound package under `/home/tim-server/tim-patches/server-acceptance-2026-10-17/`. It backs up the installed healthcheck, verifies the backup dump, invokes the existing bounded history-recovery installer and starts the existing isolated restore service. A passing read-only probe is not evidence that this root installation occurred.

## Remaining acceptance

Network access must follow the owner's current two-person terminal-access requirement. Applying a tailnet policy requires an authenticated admin session; an actual negative test requires a separate unauthorized identity. Encrypted offsite recovery requires an owner-selected destination. PERC battery status and encrypted reboot/unlock need hardware/console evidence and a verified return path. These remain explicit gates; no disk formatting, reboot or trading enablement is part of this code change.
