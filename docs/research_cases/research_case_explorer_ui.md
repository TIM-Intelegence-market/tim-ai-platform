# Research Case Explorer UI (Phase 6)

Route `/cases`, nur Explorer-Scope (keine anderen Seiten angefasst).

- Filter: Status-Default `Alle aktiven / alle Status` (kein CONFIRMED-only),
  alle Lifecycle-Status wählbar; Zeitraum/Typ/Rule wie bisher.
- Statuskarten: Confirmed / Collecting Evidence / Total (+ ehrliche
  Fortschrittszeile, Quick Win).
- Zeilen: Case/Status/Dauer/Observations/Outcome/Missing/Types/Rule.
- Empty-State unterscheidet: Filter-leer vs. keine materialisierten Cases
  (kein Fake-Text).
- Detail (`/cases?id=`): Status, Dauer, Outcome, Missing, Rule Versions,
  Case-Hash (display-only, deterministisch), Evidence-Timeline,
  Review-History, READ-ONLY-Badge.
- Stand-Zeile: Timestamp, Builder-Version (ResearchCaseEngine/30min),
  OBSERVE-only-Quelle. OBSERVE/READ-ONLY-Badges bleiben sichtbar.
- Keine statischen Zahlen, keine Trading-Sprache.

## Erweiterung 2026-10-01

- Statuskarten: Bestätigt, Sammelt Belege, Fälle gesamt, Open, Review bereit,
  Verworfen, In Quarantäne (alle aus echten Counts).
- Bei 0 bestätigten Cases: Aktion „Alle aktiven Cases anzeigen“
  (`/cases?status=ACTIVE`), Hinweis, dass CONFIRMED nur per Review entsteht.
- Statusfilter mit `ALL ACTIVE`; `?status=` in der URL setzt den Filter.
- Detail: abgeleiteter Status, Outcome/Reife mit Fälligkeit, Fenster UTC,
  Datenqualität, Gaps, Replay (ausdrücklich nicht automatisch geprüft), Review,
  Builder/Schema, Provenienz, Content Hash.
- Stand-Zeile nennt Builder-Version und `OBSERVE / READ-ONLY`.
