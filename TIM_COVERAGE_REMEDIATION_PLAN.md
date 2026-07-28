# TIM P0-001 — Continuous Coverage Remediation Plan

## Governing constraints

This plan changes no TIM Core 1.0 component and proposes no reconstruction,
backfill, denominator manipulation, or historical artifact rewrite. It is an
operational and governance plan only. No action in this document is
automatically executed.

## Required decision before measurement

Before a new qualifying run begins, Scientific Governance must record:

1. fixed UTC start;
2. fixed UTC end or minimum duration;
3. exact symbol and timeframe (`BTCUSDT`, `1m`);
4. numerator and denominator formula;
5. closed-candle inclusion rule;
6. treatment of exchange-confirmed zero-trade minutes, if such evidence is
   available;
7. permitted exclusions, preferably none;
8. acceptance threshold (`>=95.000 %`);
9. evidence cut-off and reviewer.

The interval must be declared prospectively. No best-window selection after
collection is acceptable.

## Prioritized remediation register

| ID | Cause | Priority | Effort | Risk | Scientific impact | Required measure |
|---|---|---|---|---|---|---|
| CR-001 | Raw input absent during 415 minutes | P0 | Medium | High | Direct denominator loss | Maintain continuous operation of the existing input runtime; alert on existing stream-inactive and stale-write states; restore the same runtime without creating a duplicate |
| CR-002 | `CG-023` physical cause unknown | P0 | Medium | High | Cause register incomplete | Correlate future occurrences with timestamped process, network, sleep/wake, endpoint, and persistence-boundary logs; retain UNKNOWN until proven |
| CR-003 | Qualifying interval undefined | P0 | Low | High | A favorable window could be selected post hoc | Approve and seal interval definition before collection |
| CR-004 | Gap event count is not canonical range count | P1 | Low | Medium | Reporting can overstate incident count | Report canonical distinct 1m ranges separately from raw multi-timeframe event records |
| CR-005 | Process/manual-stop causes lack direct evidence | P1 | Medium | Medium | Root cause cannot be assigned | Preserve timestamped external operational evidence; do not infer from restart counters |
| CR-006 | Historical gaps remain | P2 | None permitted | Accepted | Limits historical analysis | Preserve and disclose; never reconstruct |

## Operational sequence

### Phase 1 — Pre-registration

- Scientific Governance seals the qualifying interval and formula.
- Integrity records hashes of the starting readiness artifact, Core manifest,
  and formula implementation.
- Operations verifies exactly one existing TIM input runtime and records its
  PID and start time.
- Operations verifies that existing health reporting sees the stream active
  and the last persisted write as fresh.

Success criterion: a signed, timestamped measurement declaration exists
before the first qualifying minute.

### Phase 2 — Continuous collection

- Keep the host powered, awake, network-connected, and time-synchronized.
- Monitor existing stream activity and last-write freshness.
- If the existing input runtime exits, restart that runtime once only after
  confirming no duplicate is alive.
- Record every interruption without reconstructing missing minutes.
- Preserve source/persistence-boundary evidence for root-cause classification.

Success criterion: all operational events during the declared interval have
timestamped evidence and no duplicate runtime exists.

### Phase 3 — Read-only verification

- At the sealed end, calculate expected and observed closed 1m minutes in a
  read-only repeatable-read transaction.
- Repeat the identical calculation ten times.
- Independently generate the expected minute grid in SQL and compare it with
  persisted candle timestamps.
- For every missing minute, test raw AggTrade persistence and classify the
  causal boundary.

Success criterion: one deterministic result hash, no unexplained new gap, and
coverage at least `95.000 %`.

### Phase 4 — Independent review

- Integrity reviews formula, interval seal, hashes, gap register, and raw
  evidence.
- Scientific Review decides whether the interval length is scientifically
  sufficient.
- P0-001 may be moved only to `READY_FOR_VERIFICATION`; closure remains a
  separate governance action.

## Exact path from 60.659% to 95%

There are two valid paths. Neither is claimed complete.

### Preserve the existing denominator start

If the current interval remains cumulative and every appended minute is
complete, the smallest exact number of additional complete minutes is:

```text
(663 + x) / (1,093 + x) >= 0.95
x >= 7,507
```

At exactly 7,507 complete added minutes:

```text
observed = 8,170
expected = 8,600
coverage = 95.000 %
```

This is exact conditional arithmetic, not a forecast. Any additional missing
minute increases the requirement. It does not demonstrate future success.

### Start a prospectively declared new interval

The persisted dataset proves that real subwindows can exceed 95%:

- 506 minutes at 95.059%;
- a cut-off suffix of 128 minutes at 95.312%;
- a 226-minute partial UTC day at 100.000%.

A new interval can be used only if its duration and boundaries are approved
before collection. Existing evidence does not define the minimum acceptable
duration, so this plan cannot assert that any of those historical subwindows
is sufficient.

## Verification evidence required

- sealed interval definition and its hash;
- runtime identity evidence showing one input runtime;
- source and persistence health timeline;
- read-only SQL output;
- ten-run deterministic result hashes;
- canonical gap register;
- unchanged hashes for protected artifacts;
- independent reviewer sign-off.

## Remaining risks

- Network or endpoint interruptions can create new irreversible gaps.
- Host sleep, restart, or process loss may be indistinguishable without
  timestamped operational evidence.
- Stream-active health can be a false positive, as shown by `CG-023`.
- A short high-coverage interval may be operationally valid but scientifically
  insufficient.
- The cumulative path requires uninterrupted real collection; its arithmetic
  does not guarantee operational performance.

## Blocker status

**OPEN**

No prospective qualifying interval has yet completed and no success criterion
has been independently verified.
