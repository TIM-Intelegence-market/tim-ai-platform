# B2: Lese-Audit Datenherkunft, Aggressorflags und Point-in-Time (24.11.2026)

Mission 06/07 (#372), Uzi "B2 – GO READ-ONLY AUDIT". Nur lesend: kein Code geändert, keine Daten
geschrieben, keine Holdout-Daten gelesen, keine Studie neu gerechnet. Codestand: `platform-main` @ `e580732`.
Codex prüft unabhängig; jede Zeile ist eine Behauptung über Code, keine über Ergebnisse.

Bewertung je Befund:

- **CONFIRMED**: im Code nachgewiesen, mit Datei und Zeile.
- **POSSIBLE**: Codepfad erlaubt den Fehler; ob er in echten Daten auftrat, ist offen.
- **NOT_FOUND**: Pfad geprüft, Fehler nicht vorhanden.
- **UNKNOWN**: ohne Rohdaten oder Laufprotokoll nicht entscheidbar.

## 1. Aggressorflag (`is_buyer_maker` / `m`)

Die Regel lautet: Nur ein echtes Wahr oder Falsch ist bekannt. Jeder andere Wert ist UNKNOWN und darf nie als
Käufer zählen (Paket B).

| Pfad | Verhalten bei unerwartetem Wert | Befund |
|---|---|---|
| `src/research_lab/studies/s40_daten.py:116` | alles außer `true`/`1` wird zur Käuferseite (`+1`) | **CONFIRMED** Parser-Schwäche (wie Codex Mission 06). Wirkung auf S40-Ergebnisse **UNKNOWN** |
| `src/research_lab/fusion/historisch.py:70–71` (`_truthy`) | alles außer `true`/`1` wird zu `False`, also Käufer | **CONFIRMED**, gleiche Art wie S40. Betrifft die OF×Optionen×Gamma-Forschung (P0–P4). Wirkung **UNKNOWN** |
| `src/research_lab/depth/replay.py:107` | `bool(t["m"])`: der Text `"false"` würde zu Verkäufer | **POSSIBLE**. Binance-Websocket liefert JSON-Bool, nicht Text; ein Text-Wert wäre ein Aufnahmefehler |
| `src/research_lab/forward/live_recorder.py:66` | `"True" if trade["m"]`: Text oder `None` wird ungeprüft umgeschrieben | **POSSIBLE**. Schreibt CSV, die später streng gelesen wird; ein `None` würde als `False` gespeichert |
| `src/research_lab/studies/s2_orderflow.py:106–112` | unbekannter Wert wirft Fehler | **NOT_FOUND** (streng) |
| `src/research_lab/orderflow_ml/bars.py:121–127` | unbekannter Wert wirft Fehler | **NOT_FOUND** (streng) |
| `src/research_lab/data/aggtrades.py:188–190` | unbekannter Wert wirft Fehler | **NOT_FOUND** (streng) |
| `src/orderflow_scenario/adapters/generic.py:92` | nur Bool oder `true`/`false` | **NOT_FOUND** (streng) |
| `src/orderflow_scenario/footprint.py:198` | `None` wird übersprungen | **NOT_FOUND** |
| `src/research_lab/ki_filter/market.py:24` (SQL `CASE WHEN buyer_is_maker`) | `NULL` würde als Käufer zählen | **NOT_FOUND** in der Praxis: Spalte ist `BOOLEAN NOT NULL` (`src/database/schema.sql:15`), Einfügen prüft `None` (`src/database/repository.py:28`) |
| `src/orderflow/live_state.py:93` (Stand main) | `None` wird zu Käufer | **CONFIRMED** auf main, behoben in Paket B (#376), noch nicht gemergt |
| `src/research_lab/studies/s6_latency.py:94` | Flag wird nicht gelesen | NOT_FOUND (keine Seitenauswertung) |

Folgerung: Zwei historische Pfade (S40, Fusion) sind nachweislich nachsichtig. Ob echte Archive je einen
anderen Wert als `true`/`false` enthielten, ist UNKNOWN, solange niemand die Flag-Typen der Rohdateien zählt.

## 2. Point-in-Time in Studien

| Pfad | Zeitvertrag | Befund |
|---|---|---|
| Binance-Tagesarchive (S2, S40, orderflow_ml, data/aggtrades) | nur Eventzeit, keine Empfangszeit | **UNKNOWN** für die Verfügbarkeit. Für eine Rückrechnung ist "verfügbar ab Eventzeit plus Verzug" eine Annahme, kein Beleg |
| `src/research_lab/fusion/historisch.py:27` `LATENCY_MS = 2_000`, `fusion/of_features.py:41` | fester Verzug von 2 s für Zeilen ohne Empfangszeit | **POSSIBLE**: Verzug modelliert, nicht gemessen; echte Ausreißer (Stau, Neustart) fehlen |
| Footprint- und Perp-Stores (Live, Paket A/E) | Körbe werden in place überschrieben, ohne Empfangszeit je Zeile | **CONFIRMED** auf main; in A/E jetzt über den gemeinsamen Zeitvertrag (`pit_contract.RevisionLog`) abgefangen, persistent erst mit E2 (`pit_ledger`) |
| Gamma-Schnappschuss (`src/dashboard/gamma_data.py:81`) | `as_of` = Zeit nach der HTTP-Antwort, Quellzeit fehlt | **CONFIRMED** auf main; Paket C trennt jetzt Empfangszeit und Quellzeit |
| Holdout-Sperre (`fusion/historisch.py` `split`) | Zeilen ab Holdout-Start werfen Fehler | NOT_FOUND (Sperre greift im Code) |

## 3. Herkunft je Lauf (Lineage)

Für jede Studie gehören zu einem Ergebnis: Code-SHA, Parser-Version, Quelldateien mit Hash, Flag-Typen und
Zeitvertrag. Stand heute:

- S40: 3.031 von 3.031 geprüften Trainings-Bar-Dateien stimmten mit gespeicherten Hashes überein (Codex,
  Mission 06). Das belegt die Bars, nicht die Flag-Typen der Rohdateien und nicht die ganze Importkette:
  **UNKNOWN**.
- Übrige Studien: Lauf-Protokolle mit Code-SHA und Quell-Hashes sind nicht einheitlich vorhanden: **UNKNOWN**.

## 4. Nächste Schritte (nicht Teil dieses Audits)

1. Flag-Typen der Trainings-Rohdateien 2020–2023 zählen (nur lesend, auf dem Rechner mit den Archiven, ohne
   Holdout): Anzahl `true`, `false`, sonstige je Datei. Erst dann ist die Wirkung auf S40 und Fusion entscheidbar.
2. S40- und Fusion-Parser auf die strenge Regel umstellen (eigenes Paket, braucht Uzis Go).
3. Einheitliches Lauf-Manifest je Studie (Code-SHA, Parser, Quell-Hashes, Zeitvertrag).

## 5. Governance-Flake (getrennt)

`task_governance/test_create_authority.py::test_many_separate_registries_create_exactly_one_issue` fiel unter
Last einmal in 144 Läufen (Paket D), auf main 0 von 120. Ursache **UNKNOWN**; Codex hält einen Wettlauf zwischen
ADOPTED und BLOCKED für plausibel, nicht bewiesen. Der Test wurde nicht abgeschwächt. Braucht eine eigene
Diagnose mit deterministisch gesteuerter Reihenfolge.
