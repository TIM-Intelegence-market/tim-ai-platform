# Research Case Materialisierung (Phase 4)

Stand 2026-10-01, Builder `research-case-builder/1.0.0`.

## Was materialisiert wird

`src/research/case_builder.py` baut Research Cases deterministisch aus den
**vorhandenen, persistierten Observations** (nicht mehr nur aus Fixtures):

1. `observations_until(symbol, as_of)` liest alle Observations bis `as_of`
   (read-only). Spätere Observations werden mit `observed_after_as_of`
   ausgeschlossen (kein Look-Ahead).
2. `ResearchCaseEngine.ingest` gruppiert nach Symbol, Timeframe und
   30-Minuten-Fenster (`case_id = case_ + sha256(symbol:tf:fenster)[:16]`).
3. `assess`/`refresh_case` leiten Status, Missing Evidence und Outcome ab
   (siehe Domänenmodell). Gap Incidents und Candle-Closes werden gelesen.
4. `apply_research_cases` schreibt **nur** `research_cases`, in kurzen
   Transaktionen zu je `--batch-size` (Standard 500) Cases, damit die laufende
   Runtime nicht auf Zeilensperren wartet. Unveränderte Zeilen werden nicht
   angefasst; Zeilen, die die Runtime nach `as_of` erweitert hat
   (`updated_at > as_of`), bleiben unberührt (`skipped_newer`) und werden auch
   von `validate` ausgelassen.

Observations, Candles und Raw-Daten werden nie geschrieben. Das Skript nimmt
vor und nach dem Lauf einen Fingerabdruck (Anzahl + md5 über ID, Input-Hash,
Typ, Zeit) der Observations und bricht mit Exit 2 ab, wenn er sich ändert.

## Ablauf

```
python scripts/materialize_research_cases.py --source db --mode dry-run    # nur lesen, Preview
python scripts/materialize_research_cases.py --source db --mode apply      # transaktional, Manifest
python scripts/materialize_research_cases.py --source db --mode validate   # Rebuild == DB? sonst Exit 1
python scripts/materialize_research_cases.py --source db --mode apply      # 2. Lauf: 0 inserted/updated
```

`--as-of` (UTC) legt die Datenzeit fest; ohne Angabe: jetzt, auf die Minute
abgerundet. `validate` übernimmt `as_of` aus dem Manifest. Offline:
`--source jsonl --input export.jsonl` (ein `Observation.to_dict()` je Zeile)
und `--source fixtures` laufen nur als Dry Run.

Laufend hält die Laufzeit (`main.py::_refresh_research_cases`) die aktiven
Cases bei jedem geschlossenen Candle mit `as_of = close_time` aktuell. Der
Batch-Lauf ist für den Bestand und für Prüfungen da.

## Ausgaben (`artifacts/research_cases/`)

- `materialization_dry-run.json`, `materialization_manifest.json` (Apply):
  Builder-/Schema-Version, `as_of`, gelesene/ausgeschlossene Observations,
  Status-Counts, Case-IDs, `manifest_hash`, `changes`, Observations-Fingerabdruck
- `case_status_counts.json`, `exclusion_reasons.json`, `validation.json`
- `api_acceptance.json` (aus dem Browser-E2E: Stats, Liste, Detail, 404)
- `materialization_idempotency.json`: erster und zweiter Apply im Vergleich

## Nachweis in diesem Repo

Isolierte PostgreSQL-Testdatenbank (`tim_test`, Port 5433), befüllt über den
echten Pfad (Candles → `ObservationEngine` → `save_observation_with_case`) mit
den drei Fixture-Fenstern:

| Schritt | Ergebnis |
|---|---|
| Dry Run | 3 Observations → 3 Cases, alle `OPEN` (je 1 Observation) |
| Apply | 3 updated, Observations-Fingerabdruck unverändert |
| Validate | PASS, 0 Differenzen |
| 2. Apply | 0 inserted, 0 updated, 3 unchanged, gleicher `manifest_hash` |

Der Manifest-Hash ist identisch zum reinen In-Memory-Dry-Run über dieselben
Fixtures (`889272fd…`). Test: `tests/test_research_case_materialization_db.py`
(läuft, wenn `TIM_DURABLE_TEST_DATABASE_URL` gesetzt ist).

## Produktiver Lauf

Der produktive Apply läuft auf dem Server gegen die echte Datenbank mit den
vier Befehlen oben (Benutzer `tim`, `/opt/tim`, `EnvironmentFile=/etc/tim/tim.env`).
Er schreibt ausschließlich abgeleitete Research Cases und ist jederzeit
wiederholbar; ein Rollback ist ein erneuter Lauf mit früherem `--as-of` oder
das Zurückspielen des Backups der Tabelle `research_cases`.
