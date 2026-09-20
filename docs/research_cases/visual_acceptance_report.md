# Visuelle Abnahme (Phase 8)

Methode: Playwright Chromium Headless, isolierter Dashboard-Harness
(Port 18766, Cases aus Test-DB, kein Live-System berührt).

- `artifacts/research_cases/baseline/cases_1440x900.png` — Vorher:
  Live-Explorer mit Orderflow-Cases, altem Filter, ohne Statuskarten.
- `artifacts/research_cases/final/cases_1440x900.png` — Nachher:
  Statuskarten (0 Confirmed / 3 Collecting / 3 Total), ehrliche
  Fortschrittszeile, 3 echte Case-Zeilen mit Types/Rule/Missing,
  Stand-Zeile (Timestamp/Builder/Quelle), OBSERVE-Badge.
- `artifacts/research_cases/final/cases_1920x1080.png` — gleicher
  Stand in 1920×1080.
- Browser-E2E: `artifacts/research_cases/test_results/browser_e2e.json`
  — 16/16 Checks (Cards/Rows/Filter/Stand/API/Stats/Detail je Viewport,
  0 Console Errors, 0 failed Requests).

PASS nur mit gerenderten Screenshots — hiermit erbracht.
Mainline-Note: Die PNGs (`baseline/cases_1440x900.png`,
`final/cases_1440x900.png`, `final/cases_1920x1080.png`) sind bewusst
NICHT im Mainline-Manifest (REGENERATABLE via
`scripts/research_case_browser_e2e.py`); JSON-Evidenz liegt bei.
Bekannte Nicht-Regression: rotes Widget unten-links ist ein
vorbestehender Dashboard-Overflow, außerhalb Explorer-Scope.
