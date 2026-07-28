# Sprint 01 Specification — Safety Contracts Only

## Status

Specification only; **not implemented**. A later implementation requires a new
explicit authorization. Maximum resulting capability remains L1.

## Sprint objective

Define additive, exchange-independent safety contracts that preserve the
invariant:

```text
No code path introduced by Sprint 01 can execute a real order.
```

## Scope

Exactly six contract areas:

1. Safety Contracts
2. Mode Definitions
3. Kill-Switch Contract
4. Risk-Limit Contract
5. Protected Path Registry
6. Audit Event Contract

Non-scope: strategy logic, exchange adapter, order implementation, positions,
credentials, private HTTP, shadow/live modes, migration and Core modification.

## Proposed additive files

These are proposals, not created by this baseline:

```text
src/safety/contracts.py
src/safety/modes.py
src/safety/kill_switch.py
src/safety/risk_limits.py
src/safety/protected_paths.py
src/safety/audit_contract.py
tests/test_safety_contracts.py
tests/test_mode_fail_closed.py
tests/test_kill_switch_contract.py
tests/test_risk_limit_contract.py
tests/test_protected_paths.py
tests/test_safety_audit_contract.py
```

No proposed module may import an exchange SDK or network client.

## Contract specifications

### 1. Safety decision

Input: mode, health verdict, data-quality verdict, replay/version verdict,
optional research decision ID and risk verdict.

Output:

```text
SafetyDecision {
  decision_id, evaluated_at_utc, mode, allowed,
  denial_reasons[], contract_version, input_hash, decision_hash
}
```

Invariant: missing/unknown inputs deny. A safety decision cannot authorize
anything beyond the explicitly represented non-live mode.

### 2. Mode definitions

Initial enum: `OBSERVE`, `RESEARCH`, `SIMULATE`, `PAPER`. Default `OBSERVE`.
Unknown serialized values fail validation. `SHADOW` and `LIMITED_LIVE` are not
valid Sprint 01 runtime values.

Transitions require an external approval reference; no transition is automatic.

### 3. Kill switch

States: `ENGAGED`, `RELEASE_PENDING`, `RELEASED`. Default `ENGAGED`.

Rules:

- ENGAGED denies every simulated/order-like action.
- Release requires explicit authorized role, reason, timestamp and audit hash.
- stale or unverifiable state is treated as ENGAGED.
- Sprint 01 release can at most permit contract evaluation; it cannot permit
  exchange execution.

### 4. Risk limits

Data model:

```text
RiskLimits {
  version, max_risk_per_trade, max_daily_loss,
  max_trades_per_day, max_position_notional, max_leverage,
  loss_streak_limit, cooldown_seconds,
  averaging_down_allowed=false, martingale_allowed=false
}
```

All limits are mandatory, finite and non-negative. Missing limit = deny. Risk
denial cannot be overridden by strategy output.

### 5. Protected path registry

Registry entries contain module/symbol pattern, owner, allowed callers, mode,
required approvals and contract version. Initial registry contains only
prohibitions for exchange/private/order/account/wallet capabilities. An
unregistered sensitive path is denied.

Static tests must detect forbidden imports and direct calls. No actual exchange
path is added.

### 6. Audit event

Canonical event:

```text
AuditEvent {
  event_id, correlation_id, event_type, occurred_at_utc,
  actor, mode, component, decision, reason_codes[],
  input_hash, previous_event_hash, event_hash,
  schema_version, contract_version, provenance
}
```

UTF-8 canonical JSON, sorted keys, fixed separators, RFC 3339 UTC timestamps,
Decimal strings and SHA-256. Missing correlation or previous hash is invalid
except for a declared genesis event.

Required event types: mode validation/denial, kill-switch state evaluation,
risk allow/deny, protected-path denial, malformed-contract denial and audit
integrity failure.

## Validation and fail-closed rules

- unknown mode/version/schema/provenance → deny;
- stale or missing health/quality → deny;
- replay or hash mismatch → deny;
- missing audit correlation → deny;
- kill switch not provably RELEASED → deny;
- any breached limit → deny;
- sensitive path absent from registry → deny;
- strategy output never overrides safety;
- exceptions convert to deterministic denial plus audit event.

## Tests

Unit:

- canonical serialization and stable hashes;
- every enum/version/schema boundary;
- limit equality and one-unit-over-boundary cases;
- kill-switch state transitions;
- audit-chain verification.

Integration:

- quality RED/UNKNOWN denies;
- replay mismatch denies;
- protected-path registry denies direct sensitive access;
- audit event links decision and denial;
- no safety module imports networking or exchange packages.

Negative security:

- missing and unknown mode;
- NaN/infinite/negative limits;
- forged approval or correlation;
- stale health;
- tampered previous hash;
- attempt to register a live exchange path;
- strategy tries to bypass risk denial.

## Acceptance criteria

1. All proposed safety tests pass deterministically.
2. Existing Core tests do not regress.
3. No existing Core file, schema or persisted data changes.
4. No network, exchange, credential or order dependency is added.
5. Default and error state is denial.
6. Static dependency test proves no Strategy/Research → Exchange edge.
7. Review confirms maximum capability remains L1.

## Stop conditions

Stop immediately if implementation would require:

- changing TIM Core 1.0;
- adding or reading exchange credentials;
- private API calls or an order model;
- enabling PAPER, SHADOW or LIVE runtime behavior;
- choosing financial limits without governance approval;
- weakening an existing OBSERVE-only invariant.

## Dependencies and open decisions

Dependencies: approved owners, contract version, canonical hash specification,
responsibility matrix and review authority.

Open decisions:

- governance role allowed to sign mode/kill-switch approvals;
- persistence location for future audit events;
- maximum freshness interval;
- exact risk values for a later paper study;
- whether contracts live outside the frozen Core repository.

No open decision may be silently defaulted in implementation.

