# Mission 09.1 — Bugfixer foundation

## Scope and boundary

Application repository: `/Users/tim/Documents/TIM/tim`, verified at
`038f1360297994a53f66d5f203c4cc07b5424c73`. Mission memory remains in the
requested `/Users/tim/Documents/TIM/.codex`. This is one application repository;
mission memory is external and is not claimed to be committed.

The new observer is opt-in. It has no runtime startup integration, production
connection, queue mutation, code patcher or execution adapter. Existing runtime,
collector, ordering, recovery and decision behavior remains outside this change.

## Preflight / reuse matrix

| Area | Evidence | Decision |
|---|---|---|
| Git | Recorded candidate branch/HEAD and all 12 untracked entries match | Dedicated mission branch; preserve user files |
| Python | Existing .venv, Python 3.14.6, pytest 8.4.2, asyncpg 0.31.0 | No dependency install |
| Configuration | config/settings.py, config/secrets.py | Do not resolve credentials or load runtime config |
| PostgreSQL | src/database/connection.py, schema.sql, migrations/ | Source inventory only; no DB access |
| Test isolation | tests/conftest.py and src/database/safety.py | Existing guard; audit complete runtime identity comparison separately |
| Error classes | src/collection_reporting/errors.py | Reuse exact category vocabulary |
| Logging | src/operational/logging.py | Existing writer; independent stricter untrusted-input redactor required |
| Worker / recovery | src/data_ingestion/durable.py, recovery.py; recovery scripts | No modification; separate observer lifecycle |
| Incident storage | No src/bugfixer exists | New bounded SQLite observer store, separate from PostgreSQL |

## Decisions

DEC-002: Resolve original path blocker using the verified standalone repository
and matching checkpoint. User's resume instruction authorizes continuing its
saved task; no parent repository initialization or staging is needed.

DEC-003: SQLite is the observer's persistence only. Transactionally commit incident
counts and file offset together, preventing duplicate counting after crashes.
No migration of TIM data. Rollback consists of disabling the observer and retaining
its evidence store. Raw input never enters the database. Store path is explicit.

DEC-004: One worker per input/store transaction, bounded records and line size per
poll, polling delay; no source log modification. Persist identity, generation,
offset and previous-byte anchor. Rotation/truncation that cannot be proved lossless
must stop for operator reconciliation, never silently jump to new input.

DEC-005: Versioned fingerprints retain semantic numbers/error codes; normalize
only known volatile fields. Aggregate one incident per fingerprint while retaining
count, first/last timestamps, sample evidence and lifecycle history. No time-window
merging assumptions. Resolved recurrence requires a new investigation, never an
automatic claim that a fix remains effective.

DEC-006: Rule-based classification reuses categories, adds explicit confidence,
rule ID and reason. UNKNOWN escalates. Remediation is dry-run only in this version.
Reproduction reprocesses sanitized evidence in memory; it is not proof of an
underlying production defect or a successful repair.

## Data path

    explicit log file -> bounded reader -> parser -> redactor -> canonical event
       -> SHA-256/v1 -> rules -> incident + occurrence count + cursor (one tx)
       -> inspect/report -> isolated replay / remediation proposal

## Threat model

Logs are untrusted, including their strings, keys and paths. No shell evaluation,
LLM interpretation or automatic code execution. Redact before fingerprinting and
storage; constrain line size; suppress recursive observer-origin events; fail closed
on unsafe lifecycle transitions, corrupted cursors or uncertain rotation. Database
errors must not print payloads or source lines. Human review is necessary before
any runtime deployment or operational remediation. Source file permissions and
store access belong to the local operator; never point the store at an existing
TIM application database.

## DEC-007 — Sealed rotation protocol (9 September 2026)

Rename rotation now has an explicit producer/operator seal: old device/inode,
closed size and SHA-256, expected cursor generation, immediate successor identity,
writer_closed=true and contiguous_successor=true. These last two fields are
external attestations, not facts inferred from a digest or mtime. The producer
must have closed the old writer and preserve the append-only successor chain.

Reconciliation validates the old digest before and after a bounded tail batch,
checks that the source still names the declared successor, and atomically commits
incidents and cursor. Partial batches pin the entire seal digest, including the
successor identity. The cursor moves to generation+1 only after the complete old
segment. No path guessing or silently omitted generations. Hashing is bounded to
64 MiB per segment; unsupported compression, copytruncate, missing predecessors
and incomplete closed records remain blocked. No runtime producer integration
or automatic creation of attestations has been enabled.

## DEC-008 — Pending trace and portable evidence

Python traceback assembly persists sanitized lines and its initial timestamp in
the same cursor transaction. Line and byte budgets prevent unbounded buffering.
Incomplete traces remain pending at active EOF, including across sealed rotation;
an incompatible next record produces an UNKNOWN incident requiring review.

Content-addressed evidence exports contain one sanitized canonical event, schema,
incident fingerprint and integrity digest. Immutable file publication uses a
private temporary file, fsync and a no-overwrite hard link. SQLite stores the
bundle only after publication. A crash between publication and attachment may
leave a complete unattached export; retry is idempotent. Bundle hashes provide
integrity, not source authenticity or proof of a production root cause.

## DEC-009 — Credential adapter and deployment-independent config tests

The old single-line `security -w` mock did not model Apple's double getpass prompt.
The administrative writer now starts a dedicated isolated Python helper with a
bounded JSON stdin contract. It calls the installed macOS generic-password APIs
with byte lengths, wipes the native buffer, releases references and fails without
UI prompts. No secret argv, shell evaluation or real Keychain calls in tests.
The local macOS SDK SecKeychain.h / SecKeychainItem.h supplied ABI signatures.
These legacy Keychain APIs are deprecated; compatibility with existing item ACLs
must be assessed during a separately approved credential-operation acceptance.
No actual credential operation has been performed or claimed verified.

The historical argv leak remains a regression fixture. Current-source reproduction
must now return NOT_REPRODUCED and demonstrate secret delivery through stdin.
Security assertions are preserved while replacing the incorrect one-line prompt
expectation with the helper's actual structured input contract.

Graphify's committed deployment configuration explicitly enables it. Tests of a
disabled configuration now opt into an isolated disabled-input fixture. All their
protection assertions remain; additional parameterized tests cover both enabled
and disabled inputs and explicit invocation permission. Neither the deployment
configuration nor Graphify runtime source was changed.

## DEC-010 — Observable worker ownership and timing

A follow worker owns an OS file lock for its incident store; another follow
worker is rejected. Status probes this lock rather than trusting a persisted
running flag. Process exit automatically releases ownership. Checkpoints retain
raw line and ignored-line totals, pending trace state and sampled event lag.
Status reports oldest checkpoint age, sampled lag and future timestamps. Missing
samples are null, not zero. Legacy events use observation time, so their lag
is not a measurement of exchange feed latency. These metrics describe the observer.
