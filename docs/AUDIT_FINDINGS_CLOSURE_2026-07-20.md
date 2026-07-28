# TIM Audit Findings Closure — 2026-07-20

## Scope

Only AUD-001 through AUD-007 from the independent adversarial audit were changed. TIM remains OBSERVE-only. No execution or trading behavior was added.

## Closure matrix

| Finding | Root cause | Changed files | Adversarial regression | Result | Residual risk | Status |
|---|---|---|---|---|---|---|
| AUD-001 | Gap check covered only 1m/latest hour/>5m | `scripts/acceptance_check.py`, `tests/test_acceptance.py` | Old 2m 1m-gap and 10m 5m-gap | Official health now RED/DATA_GAP on the persisted eight gaps | Historical gaps remain and correctly keep Acceptance failed | CLOSED |
| AUD-002 | Governance absent at repository and schema boundaries | `src/database/repository.py`, `src/database/schema.sql`, `tests/test_repository_governance.py` | Future timestamps, `99x`, unknown provenance, invalid version, malformed and semantically wrong hashes | All original attacks rejected | Allowed values are intentionally strict to current production rules | CLOSED |
| AUD-003 | Composite key allowed one UUID at multiple timestamps | `src/database/schema.sql`, `tests/test_observation_id_uniqueness.py` | Same UUID inserted twice at different timestamps | Second insert raises `UniqueViolationError` | Observations are intentionally not a Timescale hypertable | CLOSED |
| AUD-004 | Observation and case used separate transactions | `src/database/repository.py`, `main.py`, `tests/test_atomic_persistence.py` | Injected case failure after observation insert | Both writes rolled back; zero orphan rows | Trigger documentation remains a later idempotent case update | CLOSED |
| AUD-005 | Restart reconstructed cases from observations | `src/database/repository.py`, `main.py`, `tests/test_restart_persisted_cases.py` | Persisted CLOSED case with outcome/documentation restored | 21 dashboard cases equal 21 database cases; zero field mismatches | Corrupt persisted JSON is rejected visibly | CLOSED |
| AUD-006 | Health trusted metadata suffix/existence | `src/research/module_b/agent.py`, `src/operational/research_health.py`, report metadata, `tests/test_research_health_integrity.py` | Content tamper + forged provenance + bad schema version | Tamper is RED; real reports pass 3/3 integrity/schema/version | Legacy metadata requires explicit migration | CLOSED |
| AUD-007 | Capped list lengths were presented without scope | `src/dashboard/app.py`, `tests/test_dashboard.py` | 70 records capped to 50 | API says `VISIBLE_RECENT_WINDOW`; UI says visible excerpt, not totals | Consumers must honor `count_scope` | CLOSED |

## Verification

- Focused adversarial suite: 33 passed.
- Complete suite: 103 passed.
- Original database attacks: all blocked.
- Audit residue: zero AUDITTEST candles, zero AUDITTEST observations, zero duplicate observation IDs.
- Dashboard/database Research Case mismatches: zero.
- Research reports: 3/3 readable, provenance-valid, integrity-valid, schema-valid, and version-valid.
- Runtime processes: exactly one TIM runtime and one validator.
- Dashboard: HTTP 200.

## Acceptance state

Acceptance remains **FAILED / RED**. The detector now correctly exposes the eight historical persisted candle gaps as `DATA_GAP`, and the real 72-hour deadline has not been reached. Closing the detector defect does not authorize deleting or fabricating missing market data.

## Independent re-audit result

The seven original implementation vulnerabilities could not be reproduced after remediation. The system cannot receive `ACCEPTANCE PASSED` because the historical dataset still contains real gaps and the required real runtime is incomplete.
