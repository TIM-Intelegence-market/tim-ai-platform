# Research Case Explorer — Baseline (Phase 0)

Datum: 2026-09-20 · Worktree: `research-case-e2e` @ `opencode/research-case-results` (d353641)
Live-Referenz: Dashboard http://127.0.0.1:8765 (PID 96443, Catchup-Worktree, NICHT modifiziert)

## Beobachteter Ist-Zustand (read-only)

- `/api/state`: `case_counts = {active: 277, closed: 4672, total: 4949}`
  (altes Format, keine Status-Aufschlüsselung), 50 sichtbare Cases, alle OPEN.
- `/cases`: Tabelle rendert Orderflow-Cases (`ofcase_*`, je 1 Observation,
  Dauer `0h 0m`, Outcome `—`, Missing `subsequent_orderflow_context`).
  Filter alt (Alle/OPEN/MONITORING/CONFIRMED/INVALIDATED/CLOSED).
  OBSERVE/READ-ONLY-Badge sichtbar, TRADING LOCKED.
- `/api/research-cases*`: 404 (Lücke bestätigt).
- Test-DB `tim_test:5433`: 0 observations / 0 cases / 0 candles (leer).
- Branch-Stand d353641: Quick Win (ehrliche Counts, Default-Sichtbarkeit)
  vorhanden; Materialisierung/API/Browser-DoD fehlt.

## Root-Cause-Hypothesen (zu verifizieren)

1. Kein CONFIRMED/REJECTED/QUARANTINED-Lifecycle: `case_engine.close()`
   kennt nur OPEN→CLOSED; nichts bestätigt je einen Case (sichtbar: 0 CONFIRMED).
2. Fehlende Read-only-API (`GET /api/research-cases*`).
3. Veraltete Filter/Stats im Explorer (Quick Win nur im Branch, nicht live).
4. Dauer/Outcome werden nie gesetzt (immer `0h 0m` / `—`).

## Verfahren

Isolierter Worktree, keine Prod-DB (5432 tabu), Test-DB nur isoliert,
Dry-Run zuerst, idempotente Apply, Manifeste, Screenshots als Beweis.
TRADING_AUTHORIZED=NO.

Screenshot: `artifacts/research_cases/baseline/cases_1440x900.png`
