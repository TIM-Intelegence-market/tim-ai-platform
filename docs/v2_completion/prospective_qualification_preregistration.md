# Prospective V2 qualification pre-registration

Dataset: `V2_PROSPECTIVE_QUALIFICATION_V1`

Status: **MACHINE WORK COMPLETE — START GATE BLOCKED**

The machine-readable pre-registration is
`artifacts/v2_completion/qualification_preregistration.json`. It fixes the
symbol, market, public data type, one-minute frequency, 95% coverage target,
1,000-case target, strict non-overlapping 30-minute independent unit, gap and
exclusion rules, quality rules, abort/restart rules, reviewer requirements,
configuration hash and software commit candidate.

## Duration

The mathematical lower bound for 1,000 non-overlapping 30-minute units is
30,000 minutes (20 days 20 hours). The current strict-unit evidence rate is
approximately 48.48 observed minutes per unit. Applying the larger requirement
and rounding upward to a complete UTC day pre-registers a minimum campaign
duration of **34 days / 48,960 minutes**.

Duration alone is insufficient. Completion additionally requires at least 95%
prospective coverage, 1,000 valid units, positive/negative/neutral-control
classes, required regime coverage, deterministic replay, look-ahead and
leakage passes, and real human review and approval.

## Start control

The campaign has no start timestamp and no expected end timestamp. This is
intentional. It cannot start until every following gate is PASS on one frozen
commit and configuration:

- PostgreSQL security;
- safe stop;
- durable ingestion and cursor;
- durable outbox;
- independent watchdog;
- log rotation;
- OBSERVE-only;
- full unfiltered test suite;
- configuration and commit freeze.

The current PostgreSQL listener is wildcard/LAN reachable, so the first gate
is failed. The campaign monitor refuses to create daily evidence before an
explicit valid activation. It cannot backdate the start.

Once the administrator closes the security gate and the final technical
acceptance is repeated, the release owner must freeze the exact implementation
commit, rebuild this registration with every gate PASS, review it, and invoke
an explicit activation. Only then may the one-shot daily monitor be scheduled.
