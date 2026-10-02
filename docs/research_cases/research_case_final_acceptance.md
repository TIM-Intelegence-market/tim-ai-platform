# Finale Abnahme (Phase 9), Stand 2026-10-01

Vorheriger Stand (2026-09-20): Lifecycle, API und UI-Grundlagen vorhanden,
Materialisierung nur über Fixtures, Cases blieben dauerhaft `OPEN`.

## Root Cause und Behebung

| Verlustpunkt | Behebung |
|---|---|
| Kein Codepfad leitete Status ab; jeder Case blieb `OPEN` | `src/research/case_builder.py` (`assess`, `refresh_case`), live je Candle-Close in `main.py::_refresh_research_cases` |
| Materialisierung nur über synthetische Fenster | `scripts/materialize_research_cases.py --source db` liest vorhandene Observations, schreibt nur `research_cases` |
| Missing Evidence ohne Horizont, Gaps, Datenqualität, Review | zehn deterministische Gründe, siehe Domänenmodell |
| API ohne ACTIVE-, Datenqualitäts- und Review-Filter, Detail ohne Lifecycle | `src/dashboard/api.py` |
| UI ohne Karten für Open/Review/Rejected/Quarantined, keine Aktion bei 0 Confirmed | `src/dashboard/views.py`, `auto_refresh.html` |

## Nachweise

1. Case-Unit-Tests: `tests/test_research_case_builder.py` 15/15 (IDs/Hashes stabil
   und reihenfolgeunabhängig, Gruppierung, Status, Outcome pending/mature,
   Lücke im Horizont, Gap, Quarantäne, kein Look-Ahead, Idempotenz,
   Review-Sperre, Confirm nur nach Review, Laufzeit-Refresh).
2. Integration Observation → Builder → Persistenz: `tests/test_research_case_materialization_db.py`
   gegen isolierte PostgreSQL (`tim_test`): PASS.
3. API: Filter, Stats, Detail, 404 (Unit + Browser-E2E).
4. UI: Karten, Aktion „Alle aktiven Cases anzeigen“, Detail (Unit + Browser-E2E).
5. Browser-E2E: 38/38 in 1440×900 und 1920×1080, 0 Console-Fehler, 0 fehlerhafte Requests.
6. Dry Run (isolierte DB): 3 Observations → 3 Cases.
7. Apply: transaktional, nur `research_cases`, Observations-Fingerabdruck unverändert.
8. Validate: PASS, 0 Differenzen.
9. Zweiter Apply: 0 inserted, 0 updated, 3 unchanged, gleicher Manifest-Hash.
10. Volle Suite (`python -m pytest tests/ -q -m "not local_env"`, Python 3.13): 2827 passed, 67 skipped, 0 failed.
11. Doctor/Validate-Befehl: im Repo nicht vorhanden; Validierung über `--mode validate`.
12. OBSERVE-only: keine Order-, Paper-, Shadow- oder Live-Pfade berührt; keine
    Trading-Sprache, Outcome nur beschreibend.
13. Trading-Aktionen: 0.
14. Protected State: Raw-Daten, Candles und Observations werden nur gelesen.
15. CONFIRMED wird nie automatisch gesetzt; 0 Confirmed ist ein gültiges Ergebnis.

## Offen auf dem Server

Der produktive Lauf gegen die echte Datenbank (`--source db`, Dry Run → Apply →
Validate → zweiter Apply) gehört auf den Server und ist in
`research_case_materialization.md` beschrieben. Danach hält die Laufzeit die
aktiven Cases selbst aktuell.
