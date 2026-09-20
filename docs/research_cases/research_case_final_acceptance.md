# Finale Abnahme (Phase 9) — 2026-09-20

1. Case-Unit: 48 Tests PASS (Lifecycle 6 neu, API 5 neu, Bestand grün).
2. Integration: Observation→Builder→Persistence→API→UI via E2E-Harness.
3. API: /api/research-cases + /stats + /{id} live verifiziert (E2E).
4. UI: Filter/Details/Stand verifiziert (Screenshots).
5. Browser-E2E: 16/16 (1440×900 + 1920×1080, 0 Console/Request-Fehler).
6. Dry: 3 Windows → 3 Obs → 3 Cases (preview.json).
7. Apply: transaktional, Manifest-Hash 6092f14f….
8. Validate: 3 Cases/3 Obs persistiert, Status OPEN.
9. 2. Lauf: identischer Hash, 0 Changes (Idempotenz).
10. TIM-IM: N/A (kein separater TIM-IM-Gate in diesem Branch-Stand;
    Kern-Validierung über Unit/Integration/E2E erbracht).
11. Full Suite: forschungsrelevante Suite 68 PASS (research/dashboard/
    observation/atomicity); Gesamt-Suite außerhalb Scope (Prod-DB nötig).
12. Doctor: Isolierter Doctor-Lauf N/A (Dashboard-Health via /api/health
    lesend geprüft im E2E-Kontext); Installations-Doctor separat in TIM v1 RC1.
13. Validate: Hash-Gegenprobe DB-Roundtrip PASS (Float-Normalisierung).
14. OBSERVE-only: core_manifest operating_mode=OBSERVE; UI-Badges;
    keine Order-/Execution-Pfade angefasst.
15. Trading-Zähler: 0 Aktionen (kein Trading-Code berührt; EXECUTION
    DISABLED, TRADING LOCKED).
16. Protected: Tree enthält nur Scope-Dateien (s. Status); Prod-DB (5432)
    nie berührt; Test-DB nur isoliert (5433/tim_test).
17. Working-Tree: nach Commit sauber; Push nur opencode/research-case-results.

Root Cause (behoben): kein Lifecycle jenseits OPEN (kein CONFIRMED-Pfad),
keine Read-only-API, veraltete Filter/Stats, CHECK-Constraint blockierte
neue Status. Fix: Lifecycle + Transitions + Confirm-Kriterien, API-Endpunkte,
UI-Detail/Stand, Schema-Evolution (idempotent), Materialisierungs-Skript.
