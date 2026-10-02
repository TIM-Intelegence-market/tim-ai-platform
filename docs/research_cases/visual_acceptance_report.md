# Visuelle Abnahme (Phase 8), Stand 2026-10-01

Methode: `scripts/research_case_browser_e2e.py` (Playwright Chromium headless).
Ein isolierter DashboardServer auf 127.0.0.1 liest die Cases aus der
isolierten Testdatenbank `tim_test`; ein zweiter Server ohne Cases prüft den
Empty State. Kein Live-System wird berührt.

Datensatz (8 Cases): 3 aus dem echten Fixture-Pfad (Candles → ObservationEngine
→ Persistenz, Symbol BTCUSDT) und 5 TEST_ONLY-Cases (Symbol E2ETEST, per
`--seed-test-cases` über den echten Builder erzeugt), damit jeder Status einmal
gerendert wird: 4 OPEN, 2 COLLECTING_EVIDENCE (davon 1 mit Gap), 1
READY_FOR_REVIEW, 1 QUARANTINED, 0 CONFIRMED.

Ergebnis: **38/38 Checks PASS** in 1440×900 und 1920×1080
(`artifacts/research_cases/test_results/browser_e2e.json`): Seite lädt, Default
nicht CONFIRMED-only, Karten und reale Zeilen sichtbar, Filter ACTIVE/OPEN/
READY_FOR_REVIEW/CONFIRMED korrekt, Empty State, Detail mit Lifecycle und
Missing Evidence, Quarantäne-Grund sichtbar, API-Liste/Stats/Detail/404,
OBSERVE/READ-ONLY und Builder-Version sichtbar, 0 Console-Fehler, 0 fehlerhafte
Requests.

Screenshots (je Viewport): `default`, `all_active`, `open`, `ready_for_review`,
`confirmed` (0 Treffer), `empty_state`, `case_detail`, `missing_evidence`
unter `artifacts/research_cases/final/`. Die PNGs (zusammen ca. 9 MB) werden
wie bisher nicht eingecheckt und lassen sich mit dem Skript neu erzeugen; die
Abnahme-Screenshots vom 2026-10-01 liegen im Projektordner unter
`research-cases/`.

Neu erzeugen:
```
TIM_E2E_CHROMIUM=/pfad/zu/chromium   # nur nötig, wenn der Playwright-Build abweicht
python scripts/research_case_browser_e2e.py --database-url postgresql://tim_test:…@127.0.0.1:5433/tim_test --seed-test-cases
```
Das Skript verweigert Datenbanken, deren Name nicht `test`, `pytest` oder
`isolated` enthält.
