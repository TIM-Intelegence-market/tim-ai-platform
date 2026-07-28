# TIM Intelligence Manager — Pflicht-Akzeptanzmatrix

Prüfstand: 2026-07-28. Diese Matrix ordnet jedes der 20
Pflicht-Akzeptanzszenarien einem konkreten Test zu. Der Exit-Code des
Gesamtlaufs ersetzt nicht das Einzelergebnis. Nach der isolierten
S11-Korrektur besitzen alle 20 Szenarien einen bestandenen Testfall.

## Ausgeführte Befehle

`C-MATRIX`

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/tim_manager/test_mandatory_acceptance.py --junitxml=artifacts/tim_manager/reports/mandatory_acceptance.junit.xml
```

- Exit-Code: `0`
- Ergebnis: `20 passed, 1 warning`; JUnit: `20` Tests, `0` Fehler,
  `0` Skips/XFAIL
- Persistierte Evidenz:
  `artifacts/tim_manager/reports/mandatory_acceptance.junit.xml`

`C-PROTECTED`

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py protected
```

- Exit-Code: `0`
- Ergebnis:
  `SUMMARY same=44 changed=4 missing=0 denied=5 probes=5`.

`C-EXPORT`

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli export --output artifacts/tim_manager/reports/final_acceptance_snapshot_export.json
```

- Exit-Code: `0`
- Ergebnis: Export erzeugt.

`C-SCHEMA`

```text
PYTHONDONTWRITEBYTECODE=1 .venv-research/bin/python artifacts/tim_manager/reports/final_verification_probes.py schema
```

- Exit-Code: `0`
- Ergebnis: `VALIDATED_FILES 3`, `jsonschema 4.26.0`; aktueller Snapshot,
  versionierter Snapshot und Export validiert und bytegleich.

`C-CLI-DENY`

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli export --output data/tim_manager_forbidden_probe.json
```

- Exit-Code: `2`
- Ergebnis: `protected TIM V1 path`; Zieldatei nicht angelegt.

`C-CLI-INVALID`

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.tim_manager.cli does-not-exist
```

- Exit-Code: `2`
- Ergebnis: argparse meldet den ungültigen Befehl und die gültigen
  Alternativen.

`C-MCP`

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python artifacts/tim_manager/reports/final_verification_probes.py mcp
```

- Exit-Code: `0`
- Ergebnis: Server-Exit `0`, `11` Antworten, `6` Read-only-Werkzeuge,
  `0` exponierte Mutationswerkzeuge, unbekannte Schreibmethode `-32601`.
- Protected-Manifest vor/nach MCP:
  `413fef8c8794c618a805abb44a2d22ffa20834c88b5a983b3f03f54638da0d99`
  in beiden Messungen.
- Reproduzierbares Prüfskript:
  `artifacts/tim_manager/reports/final_verification_probes.py`,
  SHA-256
  `89f87e626d34565066c63f523cadea817ecc8b89c2f6f0cc1d754ceffc0f4815`.
- Persistierte Probe-Ausgaben:
  `artifacts/tim_manager/reports/final_verification_probe_results.md`,
  SHA-256
  `ec58de43f15372d8fdf9f9273b1144caffb3d4d133f4a96cbe18186d991acd0c`.

## Matrix

| ID | Pflichtszenario | Testdatei und Testfunktion | Ausgeführter Befehl / Exit | Ergebnis | Erzeugte Evidenz und relevante Artefakte | Bekannte Einschränkung |
|---|---|---|---|---|---|---|
| S01 | Erster Scan erzeugt Artefakte, Events und Snapshot. | `tests/tim_manager/test_mandatory_acceptance.py` — `test_s01_first_scan_creates_artifacts_events_and_snapshot` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; isolierter Scan weist ein Artefakt, ein `artifact_added`-Event, eine Snapshot-ID sowie aktuelle und versionierte Snapshot-Dateien nach. | Die Testdateien liegen im pytest-Temp-Verzeichnis und werden nach dem Lauf nicht als Projektartefakte aufbewahrt. |
| S02 | Zweiter unveränderter Scan erzeugt keine Duplikate. | dieselbe Datei — `test_s02_second_unchanged_scan_has_no_duplicates` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; keine neuen/geänderten/gelöschten Einträge, keine Events, identische Artefakt-IDs. Reale Folge-Scans: `c681f93f-ff81-5df9-a426-ec785b58f7d0` und `148146d3-4ed2-5897-b1f7-f5b562adf70e`. | Der isolierte Test prüft zwei Läufe; die reale Prüfung ergänzt dies auf dem vollständigen Bestand. |
| S03 | Eine geänderte Datei erzeugt genau eine präzise Änderung. | dieselbe Datei — `test_s03_one_changed_file_emits_one_precise_change` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; exakt ein `artifact_changed`-Event mit Pfad und geändertem Content-Hash. | Kein Mehrdateien-Lasttest. |
| S04 | Entfernte Datei erzeugt einen persistenten Tombstone. | dieselbe Datei — `test_s04_removed_file_emits_persistent_tombstone` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; `artifact_deleted`, `tombstone=true`, ursprüngliche Artefakt-ID und persistierte Event-ID im neu geöffneten SQLite-Store. | Die Tombstone-Rekonstruktion nach einem vollständigen Datenbankverlust ist nicht Gegenstand des Tests. |
| S05 | Verschobene Datei bleibt über ihren Inhalt nachvollziehbar. | dieselbe Datei — `test_s05_moved_file_emits_move_with_same_content_hash` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; genau ein `artifact_moved`-Event, neuer Pfad und unveränderter Content-Hash. | Die geforderte Inhaltsnachvollziehbarkeit ist belegt. Das Event enthält kein eigenes `from_path`; der alte Pfad erhält zusätzlich einen Delete-Tombstone. |
| S06 | Fehlerhafte strukturierte Datei stoppt den Scan nicht. | dieselbe Datei — `test_s06_malformed_structured_file_does_not_stop_scan` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; gute und fehlerhafte Datei werden erfasst, ein Parserfehler, Status `invalid`, Fehlerzahl im Snapshot. | Deckt fehlerhaftes JSON ab, nicht jede unterstützte strukturierte Dateiform. |
| S07 | Fehlende Pflichtquelle wird als Data Gap sichtbar. | dieselbe Datei — `test_s07_missing_required_source_becomes_data_gap` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; Quellenstatus `missing`, `required_source_unavailable`, Evidenz `NO_ARTIFACTS_DISCOVERED` und Risiko-Referenz. | Prüft eine isolierte Filesystem-Pflichtquelle. Die produktive Konfiguration hat nur vier aggregierte Pflichtquellen. |
| S08 | Veraltete Quelle wird als stale markiert. | dieselbe Datei — `test_s08_stale_source_is_marked_stale` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; deterministische Drei-Stunden-Differenz gegen Zwei-Stunden-Policy ergibt `stale`. | Prüft die Freshness-Funktion direkt, nicht einen vollständigen produktiven Scan. |
| S09 | Nicht belegbare Managementfrage führt zur Enthaltung. | dieselbe Datei — `test_s09_unsupported_management_question_abstains` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; Status `unknown`, keine verifizierten Fakten, keine Evidenz. | Deterministische Query-Schicht; kein externes Sprachmodell. |
| S10 | Belegte Frage enthält konkrete Evidenz. | dieselbe Datei — `test_s10_grounded_question_has_concrete_evidence` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; Status `verified` und exakte Evidenzreferenz `artifact-1`. | Verwendet einen kontrollierten Snapshot-Fixture. |
| S11 | Widersprüchliche Quellen werden sichtbar. | dieselbe Datei — `test_s11_conflicting_sources_are_visible`; zusätzlich `tests/tim_manager/test_contradictions.py` | `C-MATRIX` / `0` | **PASS** | Zwei belegte Status-Claims zu `orderflow_pilot.status` erzeugen einen stabilen Contradiction Record im Snapshot; beide Werte und Evidenzreferenzen bleiben erhalten. Zusätzliche Tests belegen Query-/Report-Sichtbarkeit, Zeitauflösung, Supersession, Claim-Priorität, Messmethoden, Idempotenz und stabile ID. | Automatische Erkennung ist bewusst auf explizite `tim_manager_claims` und kontrollierte Status-/Boolean-Regeln beschränkt; Freitext wird nicht geraten. |
| S12 | Agentenbericht gilt nicht als Primärfakt. | dieselbe Datei — `test_s12_agent_report_is_not_primary_fact`; zusätzlich `test_model_interpretation_does_not_override_validated_result` | `C-MATRIX` / `0` | **PASS** | Agentenpfad bleibt `generated_artifact`; Claim-Prioritätsregel bewahrt Interpretationen, bevorzugt aber ein validiertes Resultat. | Kein eigener Agent-Output-Adapter; die Schutzgrenze wird durch Trust-Klasse und deterministische Claim-Priorität umgesetzt. |
| S13 | Modellausgabe verändert keine kanonischen Fakten. | dieselbe Datei — `test_s13_model_output_does_not_change_module_facts`; zusätzlich `test_model_interpretation_does_not_override_validated_result` | `C-MATRIX` / `0` | **PASS** | `model_used=None`; Modellpfad bleibt `generated_artifact`; ein `model_inference`-Konflikt überschreibt kein `validated_result` und beide Claims bleiben erhalten. | Kein dedizierter Model-Output-Adapter; externe Modelle sind deaktiviert. |
| S14 | Prompt-Injection in Dokumenten löst keine Aktion aus. | dieselbe Datei — `test_s14_prompt_injection_document_is_passive_data` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; Injection-Text wird ausschließlich als Markdown mit leerer Metadatenmenge und ohne Parseraktion behandelt. | Kein externes LLM ist aktiviert. |
| S15 | Geschützte TIM-V1-Pfade bleiben unverändert. | dieselbe Datei — `test_s15_protected_paths_remain_unchanged` | `C-MATRIX` / `0`; `C-PROTECTED` / `0` | **PASS — TIM-IM-SCHUTZGRENZE** | JUnit-Testfall; Schreibfreigabe verweigert und Bytes unverändert. Reproduzierbarer Probe-Lauf: fünf geprüfte Pfade verweigert; `44` Baseline-Dateien identisch, `0` fehlend. | Die vier bereits klassifizierten volatilen Runtime-Dateien wurden vom laufenden TIM-Prozess weitergeführt; keine TIM-IM-Schreibung wurde beobachtet. |
| S16 | TIM-IM importiert oder startet keine Trading-Komponente. | dieselbe Datei — `test_s16_scanner_import_does_not_load_trading_runtime` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; sauberer Unterprozess importiert den Scanner, ohne `src.paper.automation` zu laden. | Prüft die definierte Trading-Grenze; kein System-Call-Tracer. |
| S17 | Baseline-Scan benötigt kein Netzwerk. | dieselbe Datei — `test_s17_baseline_scan_requires_no_network` | `C-MATRIX` / `0` | **PASS** | JUnit-Testfall; `socket.create_connection`, `connect` und `connect_ex` sind im pytest-Prozess blockiert, lokaler Scan bleibt erfolgreich, Aufrufliste leer. | Der Git-Adapter nutzt nur einen lokalen `git`-Subprozess; optionale externe Adapter sind deaktiviert. |
| S18 | Snapshot und Export validieren. | dieselbe Datei — `test_s18_snapshot_and_export_validate` | `C-MATRIX` / `0`; `C-EXPORT` / `0`; `C-SCHEMA` / `0` | **PASS** | JUnit-Testfall plus formale JSON-Schema-Prüfung von aktuellem Snapshot, versionierter Kopie und Export; alle Datei-Hashes sind `73c6481e3f33ed0ccdc8514fa81bdaf481d104f1bf0b2002da211592b82ebb7d`. Ein historischer Schema-1.0-Snapshot validiert weiterhin. | Die Standard-`.venv` enthält `jsonschema` nicht; formale Prüfung erfolgte mit `.venv-research` und `jsonschema 4.26.0`. |
| S19 | CLI liefert aussagekräftige Exit-Codes. | dieselbe Datei — `test_s19_cli_returns_meaningful_exit_codes` | `C-MATRIX` / `0`; `C-CLI-DENY` / `2`; `C-CLI-INVALID` / `2` | **PASS** | JUnit-Testfall prüft `doctor=0`, fehlenden Snapshot `status=2`, ungültigen Befehl `2`. Reale CLI-Proben bestätigen Schreibschutz und argparse-Fehler; verbotene Datei fehlt. | `validate` und `doctor` führen derzeit dieselbe Checkliste aus. |
| S20 | MCP-Oberfläche ist vollständig read-only. | dieselbe Datei — `test_s20_mcp_surface_is_read_only` | `C-MATRIX` / `0`; `C-MCP` / `0` | **PASS — LOKALE MCP-GRENZE** | JUnit-Testfall ruft alle sechs Tools auf und vergleicht den Snapshot unverändert. Reales stdio-Protokoll: sechs Read-only-Tools, Ressource `tim://snapshot/current`, keine exponierten Mutationswerkzeuge, Protected-Hash und bestehender SQLite-Index vor/nach identisch. | `tim_search` öffnet den eigenen SQLite-Store nicht explizit im SQLite-Read-only-Modus; tatsächliche externe Client-/Agent-Anbindung ist separat und nicht getestet. |

## Ergebnis der Pflichtmatrix

- Konkrete Zuordnung: `20/20` Szenarien.
- Pytest-Testfunktionen bestanden: `20`.
- XFAIL/Skips: `0`.
- Pflichtszenarien PASS: `20/20`.
- Die verbleibenden Grenzen betreffen kontrollierte Erkennungsdomänen und
  externe, nicht angebundene Clients; sie ändern kein Pflichtszenario in einen
  Fehlschlag.
- Eine allgemeine Testsummen-Aussage wird für kein Szenario als alleinige Evidenz
  verwendet.
