# TIM PostgreSQL administrator remediation bundle

Status: **prepared, not applied**. This repository process has no legitimate
PostgreSQL/macOS administrator capability. The running PostgreSQL 18 service
must not be stopped or edited by an unprivileged process.

The bundle is deliberately split into a desktop-user credential stage and a
legitimate administrator stage. No password is printed, committed, placed in
a plist, or passed as a command-line argument.

1. The TIM desktop owner runs `prepare_tim_credential.py prepare`. It creates a
   random password, stores it in macOS Keychain under service
   `com.tim.database` and account `tim`, and writes a private 0600 handoff that
   contains only the PostgreSQL SCRAM verifier.
2. The PostgreSQL administrator runs `inspect_postgres.sh` and independently
   confirms the returned config, HBA, data-directory and service paths. The
   current host observation is `system/postgresql-18`, but inspection output,
   not this note, is authoritative.
3. Only after confirming `TIM_DEDICATED`, the macOS/PostgreSQL administrator
   runs `apply_postgres_hardening.sh` with all inspected paths and the handoff.
   The script refuses other classifications, refuses non-admin execution,
   backs up both files, installs loopback-only listener and first-match HBA
   rules, applies the SCRAM verifier, restarts the inspected service and checks
   PostgreSQL's parsed HBA view.
4. The TIM desktop owner selects `TIM_DATABASE_SECRET_PROVIDER=keychain`, runs
   `verify_postgres_hardening.py --test-previous-credential`, then runs
   `scripts/timctl start` or `scripts/timctl verify-running`.
5. After all checks pass, the desktop owner runs
   `prepare_tim_credential.py finalize`. Finalization refuses to remove the
   handoff unless a private, bundle-matched PASS file proves listener, LAN,
   provider and legacy-credential rejection. It never removes the Keychain
   credential.

`rollback_postgres_hardening.sh` restores the exact backed-up configuration and
restarts the inspected service. It intentionally does not restore an old or
compromised credential.

Current blocker owner: the person with legitimate macOS administrator access
to `system/postgresql-18` and PostgreSQL superuser access. Codex must not run
the administrator stage, use `sudo`, guess configuration paths, or claim a
security pass before the independent listener, LAN, HBA, credential and
application checks all pass.
